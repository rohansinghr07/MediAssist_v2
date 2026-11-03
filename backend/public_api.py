"""Public (no login) API for the clinic website: clinic details, doctors & timings, and status tracking.

Tracking works with a tracking ID OR a mobile number. Patient names are masked (R**** S.) and calls
are rate-limited per visitor, so the page can't be used to collect patient details.
"""
import json
import re
import time
from collections import defaultdict, deque
from datetime import timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

import db
from config import settings
from validators import clean_phone

router = APIRouter(prefix="/api/public")
TZ = ZoneInfo(settings.CLINIC_TZ)
SEED = Path(__file__).resolve().parent / "data" / "seed_data.json"
_hits: dict[str, deque] = defaultdict(deque)
TRACK_LIMIT, TRACK_WINDOW = 20, 600   # 20 lookups per 10 minutes per visitor ...
GLOBAL_LIMIT = 600                    # ... and at most 600 per 10 minutes for the whole site


def _clinic():
    clinic = json.loads(SEED.read_text(encoding="utf-8")).get("clinic", {})
    phone = settings.CLINIC_PHONE
    clinic["phone"] = None if not phone or "0000000000" in phone or "X" in phone.upper() else phone  # hide placeholders
    clinic["name"] = settings.CLINIC_NAME or clinic.get("name")
    return clinic


@router.get("/info")
async def info(request: Request):
    depts = await db.departments.find({}).sort("order", 1).to_list(None)
    doctors = await db.doctors.find({"active": True}).sort("_id", 1).to_list(None)
    return {
        "clinic": _clinic(),
        "bot_username": getattr(request.app.state, "bot_username", None) or settings.TELEGRAM_BOT_USERNAME or None,
        "departments": [{"id": d["_id"], "name": d["name_en"], "name_hi": d.get("name_hi"),
                         "doctors": sum(1 for x in doctors if x["department"] == d["_id"])} for d in depts],
        "doctors": [{"id": d["_id"], "name": d["name"], "department": d["department"],
                     "experience_years": d.get("experience_years"), "slots": d.get("slots", {})} for d in doctors],
    }


class TrackIn(BaseModel):
    q: str | None = None      # a tracking ID (APT-0001 / ISS-0001 / CMP-0001) OR a 10-digit mobile number
    id: str | None = None     # older page versions sent id + phone separately - still accepted
    phone: str | None = None


def _limit(request: Request):
    from api import client_ip  # same IP rule as the login lockout (can't be faked with a header)
    now = time.time()
    for key, limit in ((client_ip(request), TRACK_LIMIT), ("*all*", GLOBAL_LIMIT)):
        q = _hits[key]
        while q and q[0] < now - TRACK_WINDOW:
            q.popleft()
        if len(q) >= limit:
            raise HTTPException(429, "Too many attempts. Please try again in a few minutes.")
    for key in (client_ip(request), "*all*"):
        _hits[key].append(now)
    if len(_hits) > 5000:  # forget old visitors
        for key in [k for k, q in _hits.items() if not q or q[-1] < now - TRACK_WINDOW]:
            _hits.pop(key, None)


def _iso(dt):
    return db.aware(dt).astimezone(TZ).isoformat() if dt else None


def _mask(name):
    """'Rohan Singh' -> 'R**** S.' - enough for the patient to recognise, not enough for a stranger."""
    parts = (name or "").split()
    if not parts:
        return ""
    first = parts[0][0] + "*" * max(len(parts[0]) - 1, 2)
    return first + (f" {parts[-1][0]}." if len(parts) > 1 else "")


async def _appt_view(doc):
    status = doc.get("status", "booked")
    if status == "booked" and db.aware(doc.get("start")) and db.aware(doc["start"]) < db.utcnow():
        status = "past"
    dept = await db.departments.find_one({"_id": doc.get("department")})
    return {
        "kind": "appointment", "id": doc["_id"], "patient": _mask(doc.get("patient_name")), "status": status,
        "doctor": doc.get("doctor_name"), "department": (dept or {}).get("name_en", doc.get("department")),
        "start": _iso(doc.get("start")), "booked_at": _iso(doc.get("created_at")),
        "booked_via": {"reception": "Clinic reception", "website": "Website chat"}.get(doc.get("source"), "Telegram"),
        "cancelled_by": doc.get("cancelled_by"), "attendance_confirmed": bool(doc.get("attendance_confirmed")),
        "moves": [{"to": _iso(h.get("to")), "by": h.get("by")} for h in doc.get("history") or [] if h.get("to")],
    }


def _ticket_view(doc, details=True):
    """details=False for a lookup by ID only (IDs are easy to guess) - then the patient's problem and the
    clinic's replies are not shown; they appear when the patient searches with their own mobile number."""
    return {
        "kind": doc.get("type", "issue"), "id": doc["_id"], "patient": _mask(doc.get("name")),
        "status": doc.get("status", "pending"), "category": doc.get("category"),
        "summary": doc.get("ai_summary") if details else None,
        "raised_at": _iso(doc.get("created_at")), "updated_at": _iso(doc.get("updated_at") or doc.get("created_at")),
        "notes": [{"text": n.get("text", ""), "at": _iso(n.get("at"))} for n in (doc.get("notes") or [])[-3:]] if details else [],
        "details_hidden": not details,
    }


@router.post("/track")
async def track(body: TrackIn, request: Request):
    """Track by tracking ID, or by mobile number (lists that number's recent bookings and tickets)."""
    _limit(request)
    text = (body.q or body.id or body.phone or "").strip()
    m = re.search(r"\b(APT|ISS|CMP)\s*-?\s*(\d{1,6})\b", text.upper())
    if m:
        tid = f"{m.group(1)}-{int(m.group(2)):04d}"
        coll = db.appointments if tid.startswith("APT") else db.tickets
        doc = await coll.find_one({"_id": tid})
        if not doc:
            raise HTTPException(404, f"No booking or ticket found with ID {tid}. Check the number, or search with your mobile number.")
        return {"items": [await _appt_view(doc) if tid.startswith("APT") else _ticket_view(doc, details=False)]}

    phone = clean_phone(text)
    if not phone:
        raise HTTPException(400, "Enter a tracking ID like APT-0001, or the 10-digit mobile number you gave us.")
    since = db.utcnow() - timedelta(days=60)  # recent history only
    appts = await db.appointments.find({"phone": phone, "$or": [{"start": {"$gte": since}}, {"created_at": {"$gte": since}}]}) \
        .sort("start", -1).limit(10).to_list(None)
    tickets = await db.tickets.find({"phone": phone, "created_at": {"$gte": since}}).sort("created_at", -1).limit(5).to_list(None)
    if not appts and not tickets:
        raise HTTPException(404, "Nothing found for this mobile number in the last 60 days.")
    # upcoming bookings first (soonest first), then the rest
    now = db.utcnow()
    upcoming = sorted([a for a in appts if a.get("status") == "booked" and db.aware(a["start"]) >= now], key=lambda a: db.aware(a["start"]))
    others = [a for a in appts if a not in upcoming]
    return {"items": [await _appt_view(a) for a in upcoming + others] + [_ticket_view(t) for t in tickets]}
