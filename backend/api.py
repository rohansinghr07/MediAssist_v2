"""REST API for the clinic dashboard (React) + Cal.com webhook.

All /api routes except /api/auth/login and /api/webhooks/calcom need:  Authorization: Bearer <token>
"""
import hashlib
import hmac
import json
import logging
import time
from collections import defaultdict, deque
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

import calcom
import db
from config import settings

log = logging.getLogger("api")
router = APIRouter(prefix="/api")
bearer = HTTPBearer(auto_error=False)
TZ = ZoneInfo(settings.CLINIC_TZ)


# ------------------------------------------------------------------ helpers
def _clean(doc):
    """Make Mongo docs JSON-friendly (datetimes -> ISO strings in clinic time)."""
    if isinstance(doc, list):
        return [_clean(d) for d in doc]
    if isinstance(doc, dict):
        return {k: _clean(v) for k, v in doc.items()}
    if isinstance(doc, datetime):
        return db.aware(doc).astimezone(TZ).isoformat()
    return doc


def _day_range(day: str):
    d = date.fromisoformat(day)
    start = datetime(d.year, d.month, d.day, tzinfo=TZ)
    return start, start + timedelta(days=1)


def _engine(request: Request):
    engine = request.app.state.engines.get("engine")
    if engine is None:
        raise HTTPException(503, "Bot is not running")
    return engine


# ------------------------------------------------------------------ auth
class LoginIn(BaseModel):
    username: str
    password: str


_failed_logins: dict[str, deque] = defaultdict(deque)
LOGIN_MAX_FAILS, LOGIN_WINDOW = 5, 900  # 5 wrong passwords -> locked for 15 minutes


def client_ip(request: Request) -> str:
    """Real visitor IP. Behind a host's proxy the LAST X-Forwarded-For entry is the one the proxy added
    (earlier entries can be typed in by the visitor, so they are ignored)."""
    direct = request.client.host if request.client else "?"
    if not settings.TRUST_PROXY:
        return direct
    fwd = [p.strip() for p in request.headers.get("x-forwarded-for", "").split(",") if p.strip()]
    return fwd[-1] if fwd else direct


@router.post("/auth/login")
async def login(body: LoginIn, request: Request):
    ip, now = client_ip(request), time.time()
    fails = _failed_logins[ip]
    while fails and fails[0] < now - LOGIN_WINDOW:
        fails.popleft()
    if len(fails) >= LOGIN_MAX_FAILS:
        raise HTTPException(429, "Too many wrong attempts. Try again in 15 minutes.")
    username = (body.username or "").strip()
    password = (body.password or "").strip()
    ok_user = hmac.compare_digest(username.encode(), settings.ADMIN_USERNAME.encode())
    ok_pass = hmac.compare_digest(password.encode(), settings.ADMIN_PASSWORD.encode()) or (
        settings.ADMIN_PASSWORD == "change-me" and password in ("change-me", "admin")
    )
    if not (ok_user and ok_pass):
        fails.append(now)
        log.warning("dashboard login failed from %s (username: %s)", ip, username)
        raise HTTPException(401, "Wrong username or password")
    _failed_logins.pop(ip, None)
    exp = datetime.now(ZoneInfo("UTC")) + timedelta(hours=settings.JWT_HOURS)
    token = jwt.encode({"sub": username, "exp": exp}, settings.JWT_SECRET, algorithm="HS256")
    return {"token": token, "expires_at": exp.isoformat()}


async def require_staff(creds: HTTPAuthorizationCredentials = Depends(bearer)):
    if not creds:
        raise HTTPException(401, "Login required")
    try:
        payload = jwt.decode(creds.credentials, settings.JWT_SECRET, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(401, "Session expired, please log in again")
    return payload["sub"]


# ------------------------------------------------------------------ overview
@router.get("/stats")
async def stats(user=Depends(require_staff)):
    today = datetime.now(TZ).date().isoformat()
    start, end = _day_range(today)
    return {
        "appointments_today": await db.appointments.count_documents(
            {"status": "booked", "start": {"$gte": start, "$lt": end}}),
        "upcoming": await db.appointments.count_documents({"status": "booked", "start": {"$gte": db.utcnow()}}),
        "cancelled_today": await db.appointments.count_documents(
            {"status": "cancelled", "cancelled_at": {"$gte": start, "$lt": end}}),
        "open_issues": await db.tickets.count_documents({"type": "issue", "status": {"$ne": "resolved"}}),
        "open_complaints": await db.tickets.count_documents({"type": "complaint", "status": {"$ne": "resolved"}}),
        "new_alerts": await db.alerts.count_documents({"status": "new"}),
        "patients": await db.patients.count_documents({}),
        "doctors_active": await db.doctors.count_documents({"active": True}),
        "booked_today_via_bot": await db.appointments.count_documents(
            {"created_at": {"$gte": start, "$lt": end}}),
        "server_time": datetime.now(TZ).isoformat(),
    }


# ------------------------------------------------------------------ overview (charts, doctors today, activity)
_WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def _on_duty(slots_text: str, now_local: datetime) -> bool:
    for part in filter(None, (p.strip() for p in (slots_text or "").split(","))):
        start, end = part.split("-")
        if start <= now_local.strftime("%H:%M") < end:
            return True
    return False


@router.get("/overview")
async def overview(user=Depends(require_staff)):
    now_local = datetime.now(TZ)
    today = now_local.date()
    depts = {d["_id"]: d.get("name_en", d["_id"]) for d in await db.departments.find({}).to_list(None)}

    # appointments per day for the next 7 days (by visit date)
    start = datetime(today.year, today.month, today.day, tzinfo=TZ)
    window = await db.appointments.find({"start": {"$gte": start, "$lt": start + timedelta(days=7)}}).to_list(None)
    days = []
    for i in range(7):
        d0 = start + timedelta(days=i)
        d1 = d0 + timedelta(days=1)
        in_day = [a for a in window if d0 <= db.aware(a["start"]) < d1]
        days.append({"date": d0.date().isoformat(),
                     "booked": sum(a["status"] in ("booked", "completed", "no_show") for a in in_day),
                     "cancelled": sum(a["status"] == "cancelled" for a in in_day)})

    # upcoming bookings by department
    upcoming = await db.appointments.find({"status": "booked", "start": {"$gte": db.utcnow()}}).to_list(None)
    by_dept = {}
    for a in upcoming:
        name = depts.get(a.get("department"), a.get("department") or "Other")
        by_dept[name] = by_dept.get(name, 0) + 1
    by_department = [{"department": n, "count": by_dept.get(n, 0)} for n in depts.values()]

    # doctors today
    weekday = _WEEKDAYS[today.weekday()]
    end = start + timedelta(days=1)
    todays = [a for a in window if start <= db.aware(a["start"]) < end and a["status"] != "cancelled"]
    doctors = []
    for doc in await db.doctors.find({"active": True}).sort("name", 1).to_list(None):
        slots_today = (doc.get("slots") or {}).get(weekday, "")
        doctors.append({"_id": doc["_id"], "name": doc["name"], "department": depts.get(doc["department"], doc["department"]),
                        "experience_years": doc.get("experience_years"), "today": slots_today,
                        "on_duty": _on_duty(slots_today, now_local),
                        "booked_today": sum(a.get("doctor_id") == doc["_id"] for a in todays)})

    # next patient today
    nxt = next((a for a in sorted(todays, key=lambda a: db.aware(a["start"]))
                if a["status"] == "booked" and db.aware(a["start"]) >= db.utcnow()), None)

    # recent activity feed (newest first)
    activity = []
    for a in await db.appointments.find({}).sort("created_at", -1).limit(8).to_list(None):
        activity.append({"kind": "booking", "id": a["_id"], "at": a.get("created_at"),
                         "text": f"{a['patient_name']} booked {a['doctor_name']}", "status": a["status"]})
        if a.get("cancelled_at"):
            activity.append({"kind": "cancel", "id": a["_id"], "at": a["cancelled_at"],
                             "text": f"{a['patient_name']}'s booking cancelled ({a.get('cancelled_by', '')})"})
    for t in await db.tickets.find({}).sort("created_at", -1).limit(6).to_list(None):
        activity.append({"kind": t["type"], "id": t["_id"], "at": t.get("created_at"),
                         "text": f"{t['name']}: {t.get('ai_summary') or t.get('category')}", "priority": t.get("priority")})
    for al in await db.alerts.find({}).sort("created_at", -1).limit(4).to_list(None):
        activity.append({"kind": "alert", "id": al["_id"], "at": al.get("created_at"),
                         "text": f"Emergency message from {al.get('name') or 'a patient'}", "status": al.get("status")})
    activity = sorted([x for x in activity if x.get("at")], key=lambda x: db.aware(x["at"]), reverse=True)[:10]

    return _clean({"days": days, "by_department": by_department, "doctors_today": doctors,
                   "next_patient": nxt, "activity": activity, "weekday": weekday})


@router.get("/search")
async def search(q: str, user=Depends(require_staff)):
    """Search bookings + tickets by number, patient name or phone (top bar search)."""
    import re as _re
    q = q.strip()
    if len(q) < 2:
        return []
    rx = {"$regex": _re.escape(q), "$options": "i"}
    appts = await db.appointments.find({"$or": [{"_id": rx}, {"patient_name": rx}, {"phone": rx}]}
                                       ).sort("start", -1).limit(6).to_list(None)
    tickets = await db.tickets.find({"$or": [{"_id": rx}, {"name": rx}, {"phone": rx}]}
                                    ).sort("created_at", -1).limit(6).to_list(None)
    out = [{"type": "appointment", "id": a["_id"], "title": a["patient_name"],
            "sub": f"{a['doctor_name']} · {a['status']}", "at": a["start"]} for a in appts]
    out += [{"type": t["type"], "id": t["_id"], "title": t["name"],
             "sub": f"{t.get('category')} · {t['status']}", "at": t["created_at"]} for t in tickets]
    return _clean(out)


# ------------------------------------------------------------------ appointments
@router.get("/appointments")
async def list_appointments(day: str | None = None, doctor_id: str | None = None, status: str | None = None,
                            upcoming: bool = False, user=Depends(require_staff)):
    query = {}
    if day:
        start, end = _day_range(day)
        query["start"] = {"$gte": start, "$lt": end}
    elif upcoming:
        query["start"] = {"$gte": db.utcnow()}
    if doctor_id:
        query["doctor_id"] = doctor_id
    if status:
        query["status"] = status
    docs = await db.appointments.find(query).sort("start", 1 if (day or upcoming) else -1).limit(500).to_list(None)
    return _clean(docs)


class BookIn(BaseModel):
    doctor_id: str
    start: str           # ISO time of a free slot from /doctors/{id}/slots
    name: str
    phone: str
    email: str | None = None
    reason: str


@router.post("/appointments")
async def staff_book(body: BookIn, request: Request, user=Depends(require_staff)):
    """Walk-in / phone booking made by clinic reception."""
    from validators import clean_email, clean_name, clean_phone
    name, phone = clean_name(body.name), clean_phone(body.phone)
    if not name:
        raise HTTPException(400, "Please enter a valid patient name")
    if not phone:
        raise HTTPException(400, "Please enter a valid 10-digit mobile number")
    email = None
    if body.email and body.email.strip():
        email = clean_email(body.email)
        if not email:
            raise HTTPException(400, "Email address doesn't look right")
    if len(body.reason.strip()) < 3:
        raise HTTPException(400, "Please enter the reason for the visit")
    try:
        start = datetime.fromisoformat(body.start.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(400, "Invalid start time")
    try:
        appt = await _engine(request).staff_book(body.doctor_id, start, name, phone, email, body.reason.strip()[:300], user)
    except ValueError as exc:
        raise HTTPException(404, str(exc))
    except LookupError as exc:
        raise HTTPException(409, str(exc))
    except calcom.CalError as exc:
        raise HTTPException(502, f"Cal.com error: {exc}")
    return _clean(appt)


@router.get("/patients/lookup")
async def patient_lookup(phone: str, user=Depends(require_staff)):
    """Find an existing patient by mobile number (Telegram patients + earlier walk-ins)."""
    from validators import clean_phone
    p = clean_phone(phone)
    if not p:
        return {"found": False}
    tg = await db.patients.find_one({"phone": p})
    last = await db.appointments.find({"phone": p}).sort("created_at", -1).limit(1).to_list(None)
    visits = await db.appointments.count_documents({"phone": p})
    if not tg and not last:
        return {"found": False, "phone": p}
    return _clean({"found": True, "phone": p, "name": (tg or {}).get("name") or last[0]["patient_name"],
                   "email": (tg or {}).get("email") or (last[0].get("email") if last else None),
                   "telegram": bool(tg and tg.get("phone_verified")), "visits": visits})


class CancelIn(BaseModel):
    reason: str | None = None
    notify_patient: bool = True


@router.post("/appointments/{appt_id}/cancel")
async def staff_cancel(appt_id: str, body: CancelIn, request: Request, user=Depends(require_staff)):
    try:
        appt = await _engine(request).staff_cancel(appt_id, body.reason, user, body.notify_patient)
    except ValueError as exc:
        raise HTTPException(404, str(exc))
    except calcom.CalError as exc:
        raise HTTPException(502, f"Cal.com error: {exc}")
    return _clean(appt)


class RescheduleIn(BaseModel):
    start: str  # ISO time of the new slot, exactly as returned by /doctors/{id}/slots
    notify_patient: bool = True


@router.post("/appointments/{appt_id}/reschedule")
async def staff_reschedule(appt_id: str, body: RescheduleIn, request: Request, user=Depends(require_staff)):
    try:
        new_start = datetime.fromisoformat(body.start.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(400, "Invalid start time")
    try:
        appt = await _engine(request).staff_reschedule(appt_id, new_start, user, body.notify_patient)
    except ValueError as exc:
        raise HTTPException(404, str(exc))
    except LookupError as exc:
        raise HTTPException(409, str(exc))
    except calcom.CalError as exc:
        raise HTTPException(502, f"Cal.com error: {exc}")
    return _clean(appt)


class AppointmentStatusIn(BaseModel):
    status: str  # completed | no_show


@router.patch("/appointments/{appt_id}")
async def update_appointment(appt_id: str, body: AppointmentStatusIn, user=Depends(require_staff)):
    if body.status not in ("completed", "no_show"):
        raise HTTPException(400, "Status must be completed or no_show (cancel/reschedule in Cal.com)")
    res = await db.appointments.update_one({"_id": appt_id, "status": "booked"},
                                           {"$set": {"status": body.status, "status_by": user, "status_at": db.utcnow()}})
    if not res.matched_count:
        raise HTTPException(404, "Appointment not found or not active (cancelled bookings can't be marked)")
    return {"ok": True}


# ------------------------------------------------------------------ tickets (issues + complaints)
@router.get("/tickets")
async def list_tickets(type: str | None = None, status: str | None = None, user=Depends(require_staff)):
    query = {}
    if type:
        query["type"] = type
    if status:
        query["status"] = status
    docs = await db.tickets.find(query).sort("created_at", -1).limit(500).to_list(None)
    return _clean(docs)


class TicketUpdateIn(BaseModel):
    status: str  # pending | in_progress | resolved
    note: str | None = None
    notify_patient: bool = True


@router.patch("/tickets/{ticket_id}")
async def update_ticket(ticket_id: str, body: TicketUpdateIn, request: Request, user=Depends(require_staff)):
    if body.status not in ("pending", "in_progress", "resolved"):
        raise HTTPException(400, "Invalid status")
    update = {"$set": {"status": body.status, "updated_at": db.utcnow()}}
    note = (body.note or "").strip()[:1000]
    if note:
        update["$push"] = {"notes": {"text": note, "by": user, "at": db.utcnow()}}
    res = await db.tickets.update_one({"_id": ticket_id}, update)
    if not res.matched_count:
        raise HTTPException(404, "Ticket not found")
    ticket = await db.tickets.find_one({"_id": ticket_id})
    if body.notify_patient:
        try:
            translated = await _engine(request).notify_ticket_status(ticket, note or None)
            if translated and ticket.get("notes"):
                idx = len(ticket["notes"]) - 1
                await db.tickets.update_one({"_id": ticket_id}, {"$set": {f"notes.{idx}.translated": translated}})
                ticket = await db.tickets.find_one({"_id": ticket_id})
        except Exception:
            log.exception("could not notify patient about %s", ticket_id)
    return _clean(ticket)


# ------------------------------------------------------------------ emergency alerts
@router.get("/alerts")
async def list_alerts(status: str | None = None, user=Depends(require_staff)):
    query = {"status": status} if status else {}
    return _clean(await db.alerts.find(query).sort("created_at", -1).limit(200).to_list(None))


@router.patch("/alerts/{alert_id}")
async def ack_alert(alert_id: str, user=Depends(require_staff)):
    res = await db.alerts.update_one({"_id": alert_id},
                                     {"$set": {"status": "seen", "seen_by": user, "seen_at": db.utcnow()}})
    if not res.matched_count:
        raise HTTPException(404, "Alert not found")
    return {"ok": True}


# ------------------------------------------------------------------ doctors + departments
@router.get("/departments")
async def list_departments(user=Depends(require_staff)):
    return _clean(await db.departments.find({}).sort("order", 1).to_list(None))


@router.get("/doctors")
async def list_doctors(user=Depends(require_staff)):
    return _clean(await db.doctors.find({}).sort("name", 1).to_list(None))


@router.get("/doctors/{doctor_id}/slots")
async def doctor_slots(doctor_id: str, request: Request, user=Depends(require_staff)):
    """Free slots (from Cal.com) + booked appointments (from our DB) for the next BOOKING_DAYS_AHEAD days."""
    doctor = await db.doctors.find_one({"_id": doctor_id})
    if not doctor:
        raise HTTPException(404, "Doctor not found")
    free, error = {}, None
    if doctor.get("cal_event_type_id"):
        try:
            free = await _engine(request).fetch_slots(doctor)
        except calcom.CalError as exc:
            error = str(exc)
    else:
        error = "No Cal.com event type linked to this doctor"
    now = db.utcnow()
    booked = await db.appointments.find(
        {"doctor_id": doctor_id, "status": "booked",
         "start": {"$gte": now, "$lt": now + timedelta(days=settings.BOOKING_DAYS_AHEAD + 1)}}
    ).sort("start", 1).to_list(None)
    return {"doctor": _clean(doctor), "free": free, "booked": _clean(booked), "error": error,
            "days_ahead": settings.BOOKING_DAYS_AHEAD}


# ------------------------------------------------------------------ Cal.com sync (no public URL needed)
@router.post("/sync/calcom")
async def sync_calcom(request: Request, user=Depends(require_staff)):
    """Check Cal.com now for bookings cancelled / moved outside our system. Also runs automatically."""
    return await _engine(request).sync_with_calcom()


# ------------------------------------------------------------------ Cal.com webhook (optional)
def _parse_dt(value):
    if not value:
        return None
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


@router.post("/webhooks/calcom")
async def calcom_webhook(request: Request):
    raw = await request.body()
    if not settings.CAL_WEBHOOK_SECRET:
        # without a secret anyone could post fake "cancelled" events - the 5-minute sync covers it instead
        raise HTTPException(404, "Webhook not enabled (set CAL_WEBHOOK_SECRET)")
    sent = request.headers.get("x-cal-signature-256", "")
    expected = hmac.new(settings.CAL_WEBHOOK_SECRET.encode(), raw, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sent, expected):
        raise HTTPException(401, "Bad signature")
    try:
        body = json.loads(raw or b"{}")
    except ValueError:
        raise HTTPException(400, "Invalid JSON")
    event = body.get("triggerEvent")
    payload = body.get("payload") or {}
    engine = request.app.state.engines.get("engine")
    handled = False
    if engine and event == "BOOKING_CANCELLED" and payload.get("uid"):
        handled = await engine.on_clinic_cancelled(payload["uid"])
    elif engine and event == "BOOKING_RESCHEDULED":
        old_uid = (payload.get("rescheduleUid") or payload.get("fromReschedule")
                   or (payload.get("originalRescheduledBooking") or {}).get("uid"))
        start = _parse_dt(payload.get("startTime"))
        if old_uid and payload.get("uid") and start:
            handled = await engine.on_clinic_rescheduled(old_uid, payload["uid"], start,
                                                         _parse_dt(payload.get("endTime")))
    log.info("Cal.com webhook %s handled=%s", event, handled)
    return {"ok": True, "handled": handled}
