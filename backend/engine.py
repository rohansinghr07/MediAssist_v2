"""MediAssist chat engine - the "boss" that makes every decision.

It does not know about Telegram. It receives (chat_id, text) or (chat_id, button_data)
and sends replies through `sender(chat_id, text, buttons)`.
buttons = list of rows, each row = list of (label, callback_data).

Session (MongoDB `sessions`, _id = chat_id):
  state    current step, e.g. "pick_doctor"
  data     values collected so far (flow, doctor_id, start, ...)
  stack    previous prompts, used by the Back button
  allowed  button prefixes valid right now (old buttons are rejected)
"""
import asyncio
import functools
import html
import logging
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import ai
import calcom
import db
from config import settings
from texts import CATEGORIES, Raw, dept_name, fmt_date, fmt_time, t
from validators import clean_email, clean_name, clean_phone

log = logging.getLogger("engine")
TZ = ZoneInfo(settings.CLINIC_TZ)

GLOBAL_PREFIXES = {"menu", "back", "resume", "lang", "rem", "tr", "vc"}
TEXT_STATES = {"symptoms", "ask_name", "ask_phone", "ask_email", "ask_reason", "ticket_desc", "track_id"}
TRACK_RE = re.compile(r"\b(APT|ISS|CMP)\s*-?\s*(\d{1,6})\b", re.IGNORECASE)
TRACK_WORDS = {"/track", "track", "status", "track status"}


def find_tracking_id(text):
    """'iss 1', 'ISS-0001', 'apt0003' -> 'ISS-0001' / 'APT-0003'."""
    m = TRACK_RE.search(text or "")
    if not m:
        return None
    return f"{m.group(1).upper()}-{int(m.group(2)):04d}"
MENU_WORDS = {"/start", "/menu", "menu", "main menu", "मेनू", "मुख्य मेनू"}
LANG_WORDS = {"/language", "language", "change language", "bhasha", "भाषा"}


def _rows(buttons, per_row):
    return [buttons[i:i + per_row] for i in range(0, len(buttons), per_row)]


class Ctx:
    def __init__(self, chat_id, patient, sess):
        self.chat_id = chat_id
        self.patient = patient
        self.sess = sess

    @property
    def lang(self):
        return self.patient.get("language") or "en"

    @property
    def data(self):
        return self.sess.setdefault("data", {})

    def t(self, key, **kw):
        return t(self.lang, key, **kw)


PARTS = ("morning", "afternoon", "evening")


def _part_of_day(iso):
    hour = datetime.fromisoformat(iso).astimezone(TZ).hour
    return "morning" if hour < 12 else "afternoon" if hour < 16 else "evening"


UTC = ZoneInfo("UTC")


def is_web(chat_id):
    """Website chat users have ids like "web:3f9a..."; Telegram users have numbers."""
    return isinstance(chat_id, str) and chat_id.startswith("web:")


def _per_chat(fn):
    """One message at a time per patient (a double tap can't run the same step twice),
    while different patients are served in parallel."""
    @functools.wraps(fn)
    async def wrapper(self, chat_id, *args, **kwargs):
        async with self._lock(self._chat_locks, chat_id):
            return await fn(self, chat_id, *args, **kwargs)
    return wrapper


class Engine:
    def __init__(self, sender):
        self.sender = sender
        self._chat_locks = {}
        self._slot_locks = {}

    @staticmethod
    def _lock(table, key):
        lock = table.get(key)
        if lock is None:
            lock = table[key] = asyncio.Lock()
        return lock

    def _slot_lock(self, doctor_id, start):
        """Only one booking / reschedule at a time for the same doctor + time (bot and reception share it)."""
        return self._lock(self._slot_locks, (doctor_id, start.astimezone(UTC).isoformat()))

    async def slot_free(self, doctor, start, ignore_appt=None):
        """Free in our database AND offered by Cal.com. Call inside _slot_lock."""
        clash = await db.appointments.find_one({"doctor_id": doctor["_id"], "status": "booked",
                                                "start": start.astimezone(UTC), "_id": {"$ne": ignore_appt}})
        if clash:
            return False
        return await self.slot_still_free(doctor, start)

    # ================================================================ plumbing
    async def send(self, chat_id, text, buttons=None, **kw):
        # kw: contact_button="label" (Telegram "share my number" keyboard) or remove_keyboard=True
        if is_web(chat_id):  # website chat: the browser picks the message up from the database
            await db.web_messages.insert_one({
                "chat_id": chat_id, "from": "bot", "text": text, "created_at": db.utcnow(),
                "buttons": [[[label, data] for label, data in row] for row in (buttons or [])]})
            return
        await self.sender(chat_id, text, buttons or None, **kw)

    # ================================================================ phone sharing (links reception bookings)
    async def ask_share_phone(self, ctx):
        """One-tap 'Share my number' button. Telegram only gives the bot the patient's verified number."""
        if is_web(ctx.chat_id):
            return  # a website can't verify a phone number, so there is nothing to share here
        await self.send(ctx.chat_id, ctx.t("share_prompt"), contact_button=ctx.t("btn_share_phone"))

    @_per_chat
    async def handle_contact(self, chat_id, phone_text, own: bool, tg_name=None):
        ctx = await self._load(chat_id, tg_name)
        if not own:
            return await self.send(chat_id, ctx.t("share_own_only"), contact_button=ctx.t("btn_share_phone"))
        phone = clean_phone(phone_text)
        if not phone:
            return await self.send(chat_id, ctx.t("bad_phone"), remove_keyboard=True)
        update = {"phone": phone, "phone_verified": True}  # Telegram confirms this number belongs to the user
        if not ctx.patient.get("name") and tg_name:
            update["name"] = tg_name
        await db.patients.update_one({"_id": chat_id}, {"$set": update})
        ctx.patient.update(update)
        await self.send(chat_id, ctx.t("phone_saved", phone=phone), remove_keyboard=True)
        linked = await self.link_desk_bookings(chat_id, phone)
        if ctx.sess.get("state") == "ask_phone" and self._is_fresh(ctx):  # shared while filling in details
            ctx.data["phone"] = phone
            await self.ask(ctx, "ask_email", ctx.t("ask_email"), [[(ctx.t("btn_skip"), "email:skip")]])
        else:
            if not linked:
                await self.send(chat_id, ctx.t("phone_no_desk"))
            await self.show_menu(ctx)
        await self._save(ctx)

    async def _load(self, chat_id, tg_name=None):
        patient = await db.patients.find_one({"_id": chat_id})
        if not patient:
            patient = {"_id": chat_id, "language": None, "name": None, "phone": None, "email": None,
                       "telegram_name": tg_name, "created_at": db.utcnow()}
            await db.patients.insert_one(dict(patient))
        sess = await db.sessions.find_one({"_id": chat_id}) or {"_id": chat_id, "state": "idle", "data": {}, "stack": []}
        sess.setdefault("data", {})
        sess.setdefault("stack", [])
        return Ctx(chat_id, patient, sess)

    async def _save(self, ctx):
        await db.sessions.update_one(
            {"_id": ctx.chat_id},
            {"$set": {"state": ctx.sess.get("state", "idle"), "data": ctx.sess.get("data", {}),
                      "stack": ctx.sess.get("stack", []), "allowed": ctx.sess.get("allowed", []),
                      "voice_pending": ctx.sess.get("voice_pending"), "updated_at": db.utcnow()}},
            upsert=True,
        )
        await db.patients.update_one({"_id": ctx.chat_id}, {"$set": {"last_seen": db.utcnow()}})

    def _is_fresh(self, ctx):
        updated = db.aware(ctx.sess.get("updated_at"))
        if not updated:
            return False
        return db.utcnow() - updated < timedelta(minutes=settings.SESSION_TIMEOUT_MINUTES)

    async def ask(self, ctx, state, text, buttons=None, nav=True):
        """Send a prompt, remember it (for Back / resume) and set the allowed buttons."""
        rows = [list(r) for r in (buttons or [])]
        if nav:
            rows.append([(ctx.t("btn_back"), "back"), (ctx.t("btn_menu"), "menu")])
        prompt = {"state": state, "text": text, "buttons": rows}
        stack = ctx.sess.setdefault("stack", [])
        if stack and stack[-1]["state"] == state:
            stack[-1] = prompt
        else:
            stack.append(prompt)
        del stack[:-12]
        self._apply_prompt(ctx, prompt)
        await self.send(ctx.chat_id, text, rows)

    def _apply_prompt(self, ctx, prompt):
        ctx.sess["state"] = prompt["state"]
        ctx.sess["allowed"] = sorted({data.split(":")[0] for row in prompt["buttons"] for _, data in row})

    async def resend_current(self, ctx):
        stack = ctx.sess.get("stack") or []
        if not stack:
            return await self.show_menu(ctx)
        prompt = stack[-1]
        self._apply_prompt(ctx, prompt)
        await self.send(ctx.chat_id, prompt["text"], prompt["buttons"])

    async def go_back(self, ctx):
        stack = ctx.sess.get("stack") or []
        if len(stack) <= 1:
            return await self.show_menu(ctx)
        stack.pop()
        await self.resend_current(ctx)

    # ================================================================ entry points
    @_per_chat
    async def handle_text(self, chat_id, text, tg_name=None):
        ctx = None
        try:
            ctx = await self._load(chat_id, tg_name)
            await self._handle_text(ctx, (text or "").strip())
            await self._save(ctx)
        except Exception:
            log.exception("handle_text failed for %s", chat_id)
            await self.send(chat_id, t(ctx.lang if ctx else "en", "error"))

    @_per_chat
    async def handle_start(self, chat_id, payload, tg_name=None):
        """/start <payload> from the website's buttons (t.me/<bot>?start=book, doc_DR001, track, appts, issue, complaint).
        A brand-new patient picks a language first; the action runs right after."""
        ctx = None
        try:
            ctx = await self._load(chat_id, tg_name)
            payload = re.sub(r"[^A-Za-z0-9_]", "", payload or "")[:40]
            if not ctx.patient.get("language"):
                ctx.patient["pending_start"] = payload
                await db.patients.update_one({"_id": chat_id}, {"$set": {"pending_start": payload}})
                await self.ask_language(ctx)
            else:
                await self.run_start_action(ctx, payload)
            await self._save(ctx)
        except Exception:
            log.exception("handle_start failed for %s", chat_id)
            await self.send(chat_id, t(ctx.lang if ctx else "en", "error"))

    async def run_start_action(self, ctx, payload):
        if payload == "book":
            return await self.start_booking(ctx)
        if payload.startswith("doc_"):
            doctor = await db.doctors.find_one({"_id": payload[4:], "active": True})
            if not doctor:
                return await self.start_booking(ctx)
            ctx.sess.update({"data": {"flow": "book", "dept": doctor["department"]}, "stack": []})
            return await self.on_btn_doc(ctx, doctor["_id"])
        if payload == "track":
            return await self.start_track(ctx)
        if payload == "appts":
            return await self.my_appointments(ctx)
        if payload in ("issue", "complaint"):
            return await self.start_ticket(ctx, payload)
        return await self.show_menu(ctx)

    @_per_chat
    async def handle_button(self, chat_id, data, tg_name=None):
        ctx = None
        try:
            ctx = await self._load(chat_id, tg_name)
            await self._handle_button(ctx, data or "")
            await self._save(ctx)
        except Exception:
            log.exception("handle_button failed for %s", chat_id)
            await self.send(chat_id, t(ctx.lang if ctx else "en", "error"))

    @_per_chat
    async def handle_non_text(self, chat_id):
        ctx = await self._load(chat_id)
        await self.send(chat_id, ctx.t("non_text"))

    @_per_chat
    async def handle_voice(self, chat_id, audio: bytes, duration: int = 0, filename="voice.ogg", tg_name=None):
        """Voice note -> AI speech-to-text -> AI fixes mishearings -> "Did I hear you right?" [Yes][No].
        The reply language follows the language the patient spoke."""
        ctx = None
        try:
            ctx = await self._load(chat_id, tg_name)
            if duration and duration > settings.MAX_VOICE_SECONDS:
                return await self.send(chat_id, ctx.t("voice_too_long", seconds=settings.MAX_VOICE_SECONDS))
            raw = await ai.transcribe(audio, filename)
            if not raw:
                return await self.send(chat_id, ctx.t("voice_failed"))
            text, lang = await ai.clean_transcript(raw)
            await self.set_language_quietly(ctx, lang)
            ctx.sess["voice_pending"] = text
            await self.send(chat_id, ctx.t("voice_confirm", text=text),
                            [[(ctx.t("btn_heard_yes"), "vc:yes"), (ctx.t("btn_heard_no"), "vc:no")]])
            await self._save(ctx)
        except Exception:
            log.exception("handle_voice failed for %s", chat_id)
            await self.send(chat_id, t(ctx.lang if ctx else "en", "error"))

    async def on_btn_vc(self, ctx, arg):
        text = ctx.sess.pop("voice_pending", None)
        if not text:
            await self.send(ctx.chat_id, ctx.t("expired_btn"))
            return await self.show_menu(ctx)
        if arg == "yes":
            return await self._handle_text(ctx, text, from_voice=True)
        await self.send(ctx.chat_id, ctx.t("voice_retry"))

    async def set_language_quietly(self, ctx, lang):
        """Reply in the language the patient is using (Hindi/Hinglish -> hi, English -> en)."""
        if lang in ("en", "hi") and lang != ctx.patient.get("language"):
            ctx.patient["language"] = lang
            await db.patients.update_one({"_id": ctx.chat_id}, {"$set": {"language": lang}})

    # ---------------------------------------------------------------- text
    async def _handle_text(self, ctx, text, from_voice=False):
        low = text.lower()
        if not from_voice:
            ctx.sess.pop("voice_pending", None)  # typed instead of confirming the voice note

        # New user (or language never chosen) -> always start with language choice
        if not ctx.patient.get("language"):
            return await self.ask_language(ctx)

        if low in MENU_WORDS:
            if low == "/start" and ctx.patient.get("name"):
                await self.send(ctx.chat_id, ctx.t("welcome_back", name=ctx.patient["name"]))
            return await self.show_menu(ctx)
        if low in LANG_WORDS:
            return await self.ask_language(ctx)
        if low in TRACK_WORDS:
            return await self.start_track(ctx)

        # Safety first: emergency words are checked on every message
        if ai.is_emergency(text):
            return await self.emergency(ctx, text)

        state = ctx.sess.get("state", "idle")
        fresh = self._is_fresh(ctx)

        # A tracking number sent at any time (e.g. "ISS-0001") -> show its status
        track_id = find_tracking_id(text)
        if track_id and not (fresh and state in TEXT_STATES - {"track_id"}):
            return await self.show_track(ctx, track_id)

        # Waiting for typed input (name, phone, symptoms...)
        if fresh and state in TEXT_STATES:
            return await getattr(self, f"on_text_{state}")(ctx, text)

        # Reply in the language the patient is writing in (not for names/descriptions typed into a form step)
        await self.set_language_quietly(ctx, ai.guess_language(text))

        # Waiting for a button press, but user typed something
        if fresh and state not in ("idle", "menu"):
            intent = ai.keyword_intent(text)
            if intent:
                return await self.route_intent(ctx, intent, text)
            await self.send(ctx.chat_id, ctx.t("resume_q"),
                            [[(ctx.t("btn_continue"), "resume"), (ctx.t("btn_start_over"), "menu")]])
            return

        # Idle, on the menu, or old session -> greet (returning user) and detect intent
        if (not fresh or state == "idle") and ctx.patient.get("name") and not from_voice:
            await self.send(ctx.chat_id, ctx.t("welcome_back", name=ctx.patient["name"]))
        intent = await ai.detect_intent(text)
        if not intent and text.rstrip().endswith("?"):
            intent = "faq"
        if intent:
            return await self.route_intent(ctx, intent, text)
        if state == "menu" and fresh:
            await self.send(ctx.chat_id, ctx.t("use_buttons"))
        return await self.show_menu(ctx)

    async def route_intent(self, ctx, intent, text=""):
        ctx.sess["stack"] = []
        if intent == "book":
            return await self.start_booking(ctx)
        if intent == "appointments":
            return await self.my_appointments(ctx)
        if intent in ("issue", "complaint"):
            return await self.start_ticket(ctx, intent)
        if intent == "symptoms":
            ctx.sess["data"] = {"flow": "book"}
            return await self.on_text_symptoms(ctx, text)
        if intent == "faq":
            return await self.answer_question(ctx, text)
        return await self.show_menu(ctx)

    # ================================================================ AI FAQ (answers only from clinic_info.md)
    @staticmethod
    def clinic_info():
        path = Path(__file__).resolve().parent / "data" / "clinic_info.md"
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            return ""
        text = re.sub(r"<!--.*?-->", "", text, flags=re.S)  # drop editor notes
        return text.replace("{CLINIC_PHONE}", settings.CLINIC_PHONE).replace("{CLINIC_NAME}", settings.CLINIC_NAME)

    async def answer_question(self, ctx, question):
        found, answer = await ai.answer_faq(question, self.clinic_info(), ctx.lang)
        if found:
            await self.send(ctx.chat_id, f"ℹ️ {html.escape(answer)}\n\n<i>{ctx.t('faq_footer')}</i>")
        else:
            await self.send(ctx.chat_id, ctx.t("faq_unknown", phone=settings.CLINIC_PHONE))
        await self.show_menu(ctx)

    # ---------------------------------------------------------------- buttons
    async def _handle_button(self, ctx, data):
        prefix, _, arg = data.partition(":")

        if prefix == "lang":
            return await self.set_language(ctx, arg)
        if not ctx.patient.get("language"):
            return await self.ask_language(ctx)

        if prefix not in GLOBAL_PREFIXES and prefix not in (ctx.sess.get("allowed") or []):
            await self.send(ctx.chat_id, ctx.t("expired_btn"))
            return await self.show_menu(ctx)

        handler = getattr(self, f"on_btn_{prefix}", None)
        if handler is None:
            return await self.show_menu(ctx)
        return await handler(ctx, arg)

    async def on_btn_menu(self, ctx, arg):
        await self.show_menu(ctx)

    async def on_btn_back(self, ctx, arg):
        await self.go_back(ctx)

    async def on_btn_resume(self, ctx, arg):
        await self.resend_current(ctx)

    # ================================================================ language + menu
    async def ask_language(self, ctx):
        ctx.sess.update({"data": {}, "stack": []})
        await self.ask(ctx, "lang", t("en", "welcome", clinic=settings.CLINIC_NAME),
                       [[("English", "lang:en"), ("हिंदी", "lang:hi")]], nav=False)

    async def set_language(self, ctx, lang):
        lang = lang if lang in ("en", "hi") else "en"
        ctx.patient["language"] = lang
        await db.patients.update_one({"_id": ctx.chat_id}, {"$set": {"language": lang}})
        await self.send(ctx.chat_id, ctx.t("lang_set"))
        if not ctx.patient.get("phone"):
            await self.ask_share_phone(ctx)
        pending = ctx.patient.pop("pending_start", None)
        if pending:  # came from a website button -> continue with that action
            await db.patients.update_one({"_id": ctx.chat_id}, {"$unset": {"pending_start": ""}})
            return await self.run_start_action(ctx, pending)
        await self.show_menu(ctx)

    async def show_menu(self, ctx):
        ctx.sess.update({"data": {}, "stack": []})
        buttons = [
            [(ctx.t("m_book"), "m:book")],
            [(ctx.t("m_appts"), "m:appts")],
            [(ctx.t("m_issue"), "m:issue")],
            [(ctx.t("m_complaint"), "m:complaint")],
            [(ctx.t("m_track"), "m:track")],
            [(ctx.t("m_lang"), "m:lang")],
        ]
        await self.ask(ctx, "menu", ctx.t("menu_title"), buttons, nav=False)

    async def on_btn_m(self, ctx, arg):
        if arg == "book":
            return await self.start_booking(ctx)
        if arg == "appts":
            return await self.my_appointments(ctx)
        if arg in ("issue", "complaint"):
            return await self.start_ticket(ctx, arg)
        if arg == "lang":
            return await self.ask_language(ctx)
        if arg == "track":
            return await self.start_track(ctx)
        return await self.show_menu(ctx)

    # ================================================================ tracking (bookings + tickets)
    async def start_track(self, ctx):
        """Show the patient's recent numbers as buttons, or let them type one."""
        ctx.sess.update({"data": {}, "stack": []})
        tickets = await db.tickets.find({"chat_id": ctx.chat_id}).sort("created_at", -1).limit(5).to_list(None)
        appts = await db.appointments.find({"chat_id": ctx.chat_id}).sort("created_at", -1).limit(5).to_list(None)
        items = sorted(tickets + appts, key=lambda d: db.aware(d.get("created_at")) or db.utcnow(), reverse=True)[:6]
        buttons = []
        for d in items:
            label = self._status_label(ctx.lang, d)
            buttons.append([(f"{d['_id']} · {label}", f"tr:{d['_id']}")])
        await self.ask(ctx, "track_id", ctx.t("track_prompt" if buttons else "track_prompt_none"), buttons)

    def _status_label(self, lang, doc):
        if doc["_id"].startswith("APT"):
            status = doc.get("status", "booked")
            if status == "booked" and db.aware(doc.get("start")) and db.aware(doc["start"]) < db.utcnow():
                status = "past"
            return t(lang, f"appt_status_{status}")
        return t(lang, f"status_{doc.get('status', 'pending')}")

    async def on_text_track_id(self, ctx, text):
        track_id = find_tracking_id(text)
        if not track_id:
            return await self.send(ctx.chat_id, ctx.t("track_bad"))
        await self.show_track(ctx, track_id)

    async def on_btn_tr(self, ctx, track_id):
        await self.show_track(ctx, track_id)

    async def show_track(self, ctx, track_id):
        coll = db.appointments if track_id.startswith("APT") else db.tickets
        doc = await coll.find_one({"_id": track_id, "chat_id": ctx.chat_id})  # only your own numbers
        if not doc:
            await self.send(ctx.chat_id, ctx.t("track_not_found", tid=track_id))
            return await self.start_track(ctx)
        lang = ctx.lang
        if track_id.startswith("APT"):
            local = db.aware(doc["start"]).astimezone(TZ)
            dept = await db.departments.find_one({"_id": doc.get("department")})
            lines = [ctx.t("track_appt", tid=track_id, status=self._status_label(lang, doc), doctor=doc["doctor_name"],
                           dept=dept_name(dept, lang), date=fmt_date(local, lang), time=fmt_time(local, lang),
                           booked=fmt_date(db.aware(doc["created_at"]).astimezone(TZ), lang))]
            for h in doc.get("history") or []:
                if h.get("to"):
                    to = db.aware(h["to"]).astimezone(TZ)
                    who = ctx.t({"clinic": "by_clinic", "calcom": "by_calcom"}.get(h.get("by"), "by_you"))
                    lines.append(ctx.t("track_moved", who=who, date=fmt_date(to, lang), time=fmt_time(to, lang)))
            if doc.get("status") == "cancelled":
                who = {"clinic": "by_clinic", "calcom": "by_calcom"}.get(doc.get("cancelled_by"), "by_you")
                lines.append(ctx.t("track_cancelled_by", who=ctx.t(who)))
            elif doc.get("attendance_confirmed"):
                lines.append(ctx.t("track_attendance"))
        else:
            kind = ctx.t(f"kind_{doc['type']}")
            updated = db.aware(doc.get("updated_at") or doc["created_at"]).astimezone(TZ)
            created = db.aware(doc["created_at"]).astimezone(TZ)
            category = doc.get("category", "-")
            en_list = CATEGORIES.get(doc["type"], {}).get("en", [])
            if category in en_list and lang in CATEGORIES[doc["type"]]:
                category = CATEGORIES[doc["type"]][lang][en_list.index(category)]
            lines = [ctx.t("track_ticket", tid=track_id, kind=kind, status=self._status_label(lang, doc),
                           category=category,
                           raised=f"{fmt_date(created, lang)} {fmt_time(created, lang)}",
                           updated=f"{fmt_date(updated, lang)} {fmt_time(updated, lang)}")]
            notes = doc.get("notes") or []
            if notes:
                lines.append(ctx.t("track_notes_title"))
                for n in notes[-3:]:
                    at = db.aware(n["at"]).astimezone(TZ)
                    note_text = n.get("translated") if lang == "hi" and n.get("translated") else n.get("text", "")
                    lines.append(ctx.t("track_note", date=fmt_date(at, lang), text=note_text))
        await self.send(ctx.chat_id, "\n".join(lines))
        await self.show_menu(ctx)

    # ================================================================ booking
    async def start_booking(self, ctx):
        ctx.sess["data"] = {"flow": "book"}
        await self.ask(ctx, "book_know", ctx.t("know_q"),
                       [[(ctx.t("know_yes"), "know:yes")], [(ctx.t("know_no"), "know:no")]])

    async def on_btn_know(self, ctx, arg):
        if arg == "yes":
            return await self.ask_department(ctx)
        await self.ask(ctx, "symptoms", ctx.t("ask_symptoms"))

    async def active_departments(self):
        active = set(await db.doctors.distinct("department", {"active": True}))
        depts = await db.departments.find({}).sort("order", 1).to_list(None)
        return [d for d in depts if d["_id"] in active]

    async def ask_department(self, ctx, intro_key="pick_dept"):
        depts = await self.active_departments()
        if not depts:
            await self.send(ctx.chat_id, ctx.t("no_depts", phone=settings.CLINIC_PHONE))
            return await self.show_menu(ctx)
        buttons = [(dept_name(d, ctx.lang), f"dept:{d['_id']}") for d in depts]
        await self.ask(ctx, "pick_dept", ctx.t(intro_key), _rows(buttons, 2))

    async def on_text_symptoms(self, ctx, text):
        if len(text) < 3:
            return await self.send(ctx.chat_id, ctx.t("symptoms_short"))
        depts = await self.active_departments()
        if not depts:
            await self.send(ctx.chat_id, ctx.t("no_depts", phone=settings.CLINIC_PHONE))
            return await self.show_menu(ctx)
        key, emergency = await ai.suggest_department(text, depts)
        if emergency:
            return await self.emergency(ctx, text)
        if key is None:
            # fallback: general physician if the clinic has one, otherwise let the patient choose
            general = next((d for d in depts if "general" in d["_id"]), None)
            if general is None:
                ctx.data["symptoms"] = text[:500]
                return await self.ask_department(ctx, "no_match")
            key = general["_id"]
        ctx.data.update({"symptoms": text[:500], "suggested": key, "dept": key})
        dept = next(d for d in depts if d["_id"] == key)
        doctors = await db.doctors.find({"department": key, "active": True}).sort("name", 1).to_list(None)
        if not doctors:
            await self.send(ctx.chat_id, ctx.t("no_doctors"))
            return await self.ask_department(ctx)
        # Suggestion + doctor list in ONE step (no extra "Yes" tap)
        buttons = [[(ctx.t("doctor_btn", name=d["name"], exp=d.get("experience_years", "-")), f"doc:{d['_id']}")]
                   for d in doctors]
        buttons.append([(ctx.t("btn_other_dept"), "sug:no")])
        await self.ask(ctx, "pick_doctor", ctx.t("suggest_doctors", dept=dept_name(dept, ctx.lang)), buttons)

    async def on_btn_sug(self, ctx, arg):
        if arg == "yes" and ctx.data.get("suggested"):
            return await self.show_doctors(ctx, ctx.data["suggested"])
        await self.ask_department(ctx)

    async def on_btn_dept(self, ctx, key):
        await self.show_doctors(ctx, key)

    async def show_doctors(self, ctx, dept_key):
        dept = await db.departments.find_one({"_id": dept_key})
        doctors = await db.doctors.find({"department": dept_key, "active": True}).sort("name", 1).to_list(None)
        if not dept or not doctors:
            await self.send(ctx.chat_id, ctx.t("no_doctors"))
            return await self.ask_department(ctx)
        ctx.data["dept"] = dept_key
        buttons = [[(ctx.t("doctor_btn", name=d["name"], exp=d.get("experience_years", "-")), f"doc:{d['_id']}")]
                   for d in doctors]
        await self.ask(ctx, "pick_doctor", ctx.t("pick_doctor", dept=dept_name(dept, ctx.lang)), buttons)

    async def on_btn_doc(self, ctx, doctor_id):
        doctor = await db.doctors.find_one({"_id": doctor_id, "active": True})
        if not doctor:
            await self.send(ctx.chat_id, ctx.t("no_doctors"))
            return await self.resend_current(ctx)
        ctx.data["doctor_id"] = doctor_id
        await self.show_dates(ctx, doctor)

    async def fetch_slots(self, doctor):
        """Free slots from Cal.com, grouped by date, only future slots after the minimum lead time."""
        event_type_id = doctor.get("cal_event_type_id")
        if not event_type_id:
            raise calcom.CalError(f"Doctor {doctor['_id']} has no cal_event_type_id")
        today = datetime.now(TZ).date()
        raw = await calcom.get_slots(event_type_id, today, today + timedelta(days=settings.BOOKING_DAYS_AHEAD),
                                     settings.CLINIC_TZ)
        earliest = db.utcnow() + timedelta(minutes=settings.MIN_LEAD_MINUTES)
        result = {}
        for starts in raw.values():
            for iso in starts:
                try:
                    start = datetime.fromisoformat(iso.replace("Z", "+00:00"))
                except ValueError:
                    continue
                if start.tzinfo is None:
                    start = start.replace(tzinfo=TZ)
                if start < earliest:
                    continue
                local = start.astimezone(TZ)
                result.setdefault(local.date().isoformat(), []).append(local.isoformat())
        return {d: sorted(v) for d, v in sorted(result.items())}

    async def show_dates(self, ctx, doctor):
        await self.send(ctx.chat_id, ctx.t("loading_slots"))
        try:
            slots = await self.fetch_slots(doctor)
        except calcom.CalError as exc:
            log.warning("slot fetch failed: %s", exc)
            await self.send(ctx.chat_id, ctx.t("slots_error"))
            return await self.resend_current(ctx)
        if not slots:
            await self.send(ctx.chat_id, ctx.t("no_slots", doctor=doctor["name"], days=settings.BOOKING_DAYS_AHEAD))
            return await self.resend_current(ctx)
        dates = list(slots.keys())
        ctx.data.update({"slots": slots, "dates": dates, "doctor_id": doctor["_id"]})
        buttons = [(fmt_date(d, ctx.lang), f"date:{i}") for i, d in enumerate(dates)]
        await self.ask(ctx, "pick_date", ctx.t("pick_date", doctor=doctor["name"]), _rows(buttons, 3))

    async def on_btn_date(self, ctx, arg):
        try:
            day = ctx.data["dates"][int(arg)]
            times = ctx.data["slots"][day]
        except (KeyError, IndexError, ValueError):
            return await self.resend_current(ctx)
        ctx.data["date"] = day
        doctor = await db.doctors.find_one({"_id": ctx.data.get("doctor_id")}) or {"name": ""}
        parts = {p: [i for i, iso in enumerate(times) if _part_of_day(iso) == p] for p in PARTS}
        parts = {p: idx for p, idx in parts.items() if idx}
        if len(times) > 16 and len(parts) > 1:  # many 10-min slots -> choose morning / afternoon / evening first
            buttons = [(ctx.t(f"part_{p}", n=len(idx)), f"part:{p}") for p, idx in parts.items()]
            return await self.ask(ctx, "pick_part", ctx.t("pick_part", doctor=doctor["name"], date=fmt_date(day, ctx.lang)),
                                  [[b] for b in buttons])
        await self.show_times(ctx, list(range(len(times))))

    async def on_btn_part(self, ctx, part):
        times = ctx.data.get("slots", {}).get(ctx.data.get("date"), [])
        idx = [i for i, iso in enumerate(times) if _part_of_day(iso) == part]
        if not idx:
            return await self.resend_current(ctx)
        await self.show_times(ctx, idx)

    async def show_times(self, ctx, idx):
        times = ctx.data["slots"][ctx.data["date"]]
        doctor = await db.doctors.find_one({"_id": ctx.data.get("doctor_id")}) or {"name": ""}
        buttons = [(fmt_time(datetime.fromisoformat(times[i]), ctx.lang), f"time:{i}") for i in idx]
        await self.ask(ctx, "pick_time", ctx.t("pick_time", doctor=doctor["name"], date=fmt_date(ctx.data["date"], ctx.lang)),
                       _rows(buttons, 4))

    async def on_btn_time(self, ctx, arg):
        try:
            iso = ctx.data["slots"][ctx.data["date"]][int(arg)]
        except (KeyError, IndexError, ValueError):
            return await self.resend_current(ctx)
        ctx.data["start"] = iso
        if ctx.data.get("flow") == "resched":
            return await self.ask_resched_confirm(ctx)
        await self.ask_details(ctx)

    # ---------------------------------------------------------------- patient details (shared by booking + tickets)
    async def ask_details(self, ctx):
        p = ctx.patient
        if p.get("name") and p.get("phone"):
            email_line = Raw(ctx.t("email_line", email=p["email"])) if p.get("email") else ""
            return await self.ask(
                ctx, "saved_details",
                ctx.t("saved_details", name=p["name"], phone=p["phone"], email_line=email_line),
                [[(ctx.t("btn_use_saved"), "det:use")], [(ctx.t("btn_enter_new"), "det:new")]])
        await self.ask(ctx, "ask_name", ctx.t("ask_name"))

    async def on_btn_det(self, ctx, arg):
        if arg == "use":
            return await self.after_details(ctx)
        await self.ask(ctx, "ask_name", ctx.t("ask_name"))

    async def on_text_ask_name(self, ctx, text):
        name = clean_name(text)
        if not name:
            return await self.send(ctx.chat_id, ctx.t("bad_name"))
        ctx.data["name"] = name
        await self.ask(ctx, "ask_phone", ctx.t("ask_phone"))
        if not is_web(ctx.chat_id):
            await self.send(ctx.chat_id, ctx.t("ask_phone_share"), contact_button=ctx.t("btn_share_phone"))

    async def on_text_ask_phone(self, ctx, text):
        phone = clean_phone(text)
        if not phone:
            return await self.send(ctx.chat_id, ctx.t("bad_phone"))
        ctx.data["phone"] = phone
        await self.send(ctx.chat_id, ctx.t("phone_noted"), remove_keyboard=True)
        await self.ask(ctx, "ask_email", ctx.t("ask_email"), [[(ctx.t("btn_skip"), "email:skip")]])

    async def on_text_ask_email(self, ctx, text):
        email = clean_email(text)
        if not email:
            return await self.send(ctx.chat_id, ctx.t("bad_email"))
        ctx.data["email"] = email
        await self.finish_details(ctx)

    async def on_btn_email(self, ctx, arg):
        ctx.data["email"] = None
        await self.finish_details(ctx)

    async def finish_details(self, ctx):
        update = {"name": ctx.data.get("name"), "phone": ctx.data.get("phone")}
        if update["phone"] != ctx.patient.get("phone"):
            update["phone_verified"] = False  # typed numbers are not proof of ownership
        if ctx.data.get("email"):
            update["email"] = ctx.data["email"]
        await db.patients.update_one({"_id": ctx.chat_id}, {"$set": update})
        ctx.patient.update(update)
        if not ctx.patient.get("phone_verified") and await db.appointments.count_documents(
                {"phone": update["phone"], "chat_id": None, "status": "booked", "start": {"$gt": db.utcnow()}}):
            # clinic bookings exist for this number -> only a shared (verified) number may see them
            if is_web(ctx.chat_id):
                await self.send(ctx.chat_id, ctx.t("web_desk_hint"))
            else:
                await self.send(ctx.chat_id, ctx.t("share_to_link"), contact_button=ctx.t("btn_share_phone"))
        await self.after_details(ctx)

    async def link_desk_bookings(self, chat_id, phone):
        """A patient booked at reception joins Telegram later -> attach their upcoming bookings
        (matched by phone) so they get the confirmation, reminders and can manage them here.
        Only called with a number Telegram verified (shared contact), never with a typed one."""
        if not phone:
            return 0
        found = await db.appointments.find({"phone": phone, "chat_id": None, "status": "booked",
                                            "start": {"$gt": db.utcnow()}}).sort("start", 1).to_list(None)
        for appt in found:
            await db.appointments.update_one({"_id": appt["_id"]}, {"$set": {"chat_id": chat_id}})
            local = db.aware(appt["start"]).astimezone(TZ)
            await self._notify_patient(chat_id, "desk_booked", appt_id=appt["_id"], doctor=appt["doctor_name"],
                                       date=lambda lang, d=local: fmt_date(d, lang), time=lambda lang, d=local: fmt_time(d, lang))
        return len(found)

    async def after_details(self, ctx):
        if ctx.data.get("flow") == "ticket":
            kind = ctx.t(f"kind_{ctx.data['ttype']}")
            return await self.ask(ctx, "ticket_desc", ctx.t("ask_desc", kind=kind))
        await self.ask(ctx, "ask_reason", ctx.t("ask_reason"))

    # ---------------------------------------------------------------- booking confirm
    async def on_text_ask_reason(self, ctx, text):
        if len(text) < 3:
            return await self.send(ctx.chat_id, ctx.t("reason_short"))
        ctx.data["reason"] = text[:300]
        doctor = await db.doctors.find_one({"_id": ctx.data["doctor_id"]})
        dept = await db.departments.find_one({"_id": doctor["department"]})
        start = datetime.fromisoformat(ctx.data["start"])
        summary = ctx.t("book_summary", doctor=doctor["name"], dept=dept_name(dept, ctx.lang),
                        date=fmt_date(start, ctx.lang), time=fmt_time(start, ctx.lang),
                        name=ctx.patient["name"], phone=ctx.patient["phone"], reason=ctx.data["reason"])
        await self.ask(ctx, "book_confirm", summary,
                       [[(ctx.t("btn_confirm"), "bk:confirm")], [(ctx.t("btn_edit"), "bk:edit")]])

    async def on_btn_bk(self, ctx, arg):
        if arg == "edit":
            return await self.ask(ctx, "ask_name", ctx.t("ask_name"))
        await self.do_booking(ctx)

    @staticmethod
    def attendee_email(patient, chat_id):
        if patient.get("email"):
            return patient["email"]
        local, _, domain = settings.FALLBACK_EMAIL.partition("@")
        if not domain:
            raise RuntimeError("FALLBACK_EMAIL is not set in .env")
        return f"{local}+tg{chat_id}@{domain}"

    async def slot_still_free(self, doctor, start):
        """Cal.com accepts any time, so we re-check the slot list right before booking."""
        slots = await self.fetch_slots(doctor)
        day = start.astimezone(TZ).date().isoformat()
        return any(datetime.fromisoformat(iso) == start for iso in slots.get(day, []))

    async def do_booking(self, ctx):
        doctor = await db.doctors.find_one({"_id": ctx.data["doctor_id"]})
        dept = await db.departments.find_one({"_id": doctor["department"]})
        start = datetime.fromisoformat(ctx.data["start"])
        p = ctx.patient
        attendee_email = self.attendee_email(p, ctx.chat_id)
        await self.send(ctx.chat_id, ctx.t("booking_wait"))
        async with self._slot_lock(doctor["_id"], start):
            return await self._do_booking_locked(ctx, doctor, dept, start, p, attendee_email)

    async def _do_booking_locked(self, ctx, doctor, dept, start, p, attendee_email):
        try:
            free = await self.slot_free(doctor, start)
        except calcom.CalError as exc:
            log.warning("slot re-check failed: %s", exc)
            await self.send(ctx.chat_id, ctx.t("book_failed", phone=settings.CLINIC_PHONE))
            return await self.show_menu(ctx)
        if not free:
            await self.send(ctx.chat_id, ctx.t("slot_taken"))
            return await self.show_dates(ctx, doctor)
        appt_id = await db.next_id("APT")
        try:
            dept_en = (dept or {}).get("name_en", doctor["department"])
            notes = "\n".join(filter(None, [
                f"Booking ID: {appt_id}",
                f"Patient: {p['name']}",
                f"Phone: {p['phone']}",
                f"Email: {p['email']}" if p.get("email") else None,
                f"Doctor: {doctor['name']} ({dept_en})",
                f"Reason for visit: {ctx.data.get('reason')}",
                f"Symptoms told to the bot: {ctx.data['symptoms']}" if ctx.data.get("symptoms") else None,
                "Booked via: MediAssist website chat" if is_web(ctx.chat_id) else "Booked via: MediAssist Telegram bot",
            ]))
            booking = await calcom.create_booking(
                doctor["cal_event_type_id"], start, p["name"], attendee_email, settings.CLINIC_TZ,
                metadata={"appointment_id": appt_id, "chat_id": ctx.chat_id,
                          "phone": p["phone"], "reason": ctx.data.get("reason")},
                phone=p["phone"], notes=notes,
            )
        except calcom.CalError as exc:
            log.warning("booking failed: %s", exc)
            if exc.is_client_error:  # slot taken / not available -> pick another time
                await self.send(ctx.chat_id, ctx.t("slot_taken"))
                return await self.show_dates(ctx, doctor)
            await self.send(ctx.chat_id, ctx.t("book_failed", phone=settings.CLINIC_PHONE))
            return await self.show_menu(ctx)

        end = booking.get("end")
        appt = {
            "_id": appt_id,
            "cal_uid": booking.get("uid"),
            "cal_booking_id": booking.get("id"),
            "chat_id": ctx.chat_id,
            "patient_name": p["name"],
            "phone": p["phone"],
            "email": p.get("email"),
            "doctor_id": doctor["_id"],
            "doctor_name": doctor["name"],
            "department": doctor["department"],
            "start": start.astimezone(ZoneInfo("UTC")),
            "end": datetime.fromisoformat(end.replace("Z", "+00:00")) if end else None,
            "reason": ctx.data.get("reason"),
            "symptoms": ctx.data.get("symptoms"),
            "status": "booked",
            "attendance_confirmed": False,
            "reminders_sent": [],
            "history": [],
            "source": "website" if is_web(ctx.chat_id) else "telegram",
            "created_at": db.utcnow(),
        }
        await db.appointments.insert_one(appt)
        msg = ctx.t("booked", appt_id=appt_id, doctor=doctor["name"], dept=dept_name(dept, ctx.lang),
                    date=fmt_date(start, ctx.lang), time=fmt_time(start, ctx.lang))
        if p.get("email"):
            msg += "\n\n" + ctx.t("booked_email", email=p["email"])
        msg += "\n\n" + ctx.t("track_hint", tid=appt_id)
        await self.send(ctx.chat_id, msg)
        await self.show_menu(ctx)

    # ================================================================ my appointments
    async def upcoming(self, chat_id):
        return await db.appointments.find(
            {"chat_id": chat_id, "status": "booked", "start": {"$gte": db.utcnow()}}
        ).sort("start", 1).to_list(None)

    async def my_appointments(self, ctx):
        ctx.sess["data"] = {}
        appts = await self.upcoming(ctx.chat_id)
        if not appts:
            if not ctx.patient.get("phone"):  # booked at the clinic? sharing the number finds it
                await self.ask_share_phone(ctx)
            return await self.ask(ctx, "appts_none", ctx.t("no_appts"), [[(ctx.t("m_book"), "m:book")]])
        buttons = []
        for a in appts[:10]:
            local = db.aware(a["start"]).astimezone(TZ)
            label = ctx.t("appt_btn", date=fmt_date(local, ctx.lang), time=fmt_time(local, ctx.lang),
                          doctor=a["doctor_name"])
            buttons.append([(label, f"ap:{a['_id']}")])
        await self.ask(ctx, "appts_list", ctx.t("appts_list"), buttons)

    async def _own_appt(self, ctx, appt_id):
        return await db.appointments.find_one({"_id": appt_id, "chat_id": ctx.chat_id, "status": "booked"})

    async def on_btn_ap(self, ctx, appt_id):
        appt = await self._own_appt(ctx, appt_id)
        if not appt:
            await self.send(ctx.chat_id, ctx.t("appt_not_found"))
            return await self.my_appointments(ctx)
        ctx.data["appt_id"] = appt_id
        dept = await db.departments.find_one({"_id": appt["department"]})
        local = db.aware(appt["start"]).astimezone(TZ)
        await self.ask(ctx, "appt_detail",
                       ctx.t("appt_detail", appt_id=appt_id, doctor=appt["doctor_name"],
                             dept=dept_name(dept, ctx.lang), date=fmt_date(local, ctx.lang),
                             time=fmt_time(local, ctx.lang)),
                       [[(ctx.t("btn_resched"), "aa:resched")], [(ctx.t("btn_cancel_appt"), "aa:cancel")]])

    async def on_btn_aa(self, ctx, arg):
        appt = await self._own_appt(ctx, ctx.data.get("appt_id"))
        if not appt:
            await self.send(ctx.chat_id, ctx.t("appt_not_found"))
            return await self.show_menu(ctx)
        if arg == "cancel":
            return await self.ask_cancel(ctx, appt)
        await self.start_resched(ctx, appt)

    async def ask_cancel(self, ctx, appt):
        ctx.data["appt_id"] = appt["_id"]
        local = db.aware(appt["start"]).astimezone(TZ)
        await self.ask(ctx, "cancel_confirm",
                       ctx.t("cancel_q", appt_id=appt["_id"], date=fmt_date(local, ctx.lang),
                             time=fmt_time(local, ctx.lang)),
                       [[(ctx.t("btn_yes_cancel"), "cx:yes")], [(ctx.t("btn_no_keep"), "cx:no")]])

    async def on_btn_cx(self, ctx, arg):
        if arg != "yes":
            return await self.show_menu(ctx)
        appt = await self._own_appt(ctx, ctx.data.get("appt_id"))
        if not appt:
            await self.send(ctx.chat_id, ctx.t("appt_not_found"))
            return await self.show_menu(ctx)
        try:
            await calcom.cancel_booking(appt["cal_uid"], "Cancelled by patient via Telegram")
        except calcom.CalError as exc:
            log.warning("cancel failed: %s", exc)
            await self.send(ctx.chat_id, ctx.t("cancel_failed", phone=settings.CLINIC_PHONE))
            return await self.show_menu(ctx)
        await db.appointments.update_one(
            {"_id": appt["_id"]},
            {"$set": {"status": "cancelled", "cancelled_by": "patient", "cancelled_at": db.utcnow()}})
        await self.send(ctx.chat_id, ctx.t("cancelled", appt_id=appt["_id"]))
        await self.show_menu(ctx)

    async def start_resched(self, ctx, appt):
        doctor = await db.doctors.find_one({"_id": appt["doctor_id"]})
        if not doctor:
            await self.send(ctx.chat_id, ctx.t("no_doctors"))
            return await self.show_menu(ctx)
        ctx.data.update({"flow": "resched", "appt_id": appt["_id"]})
        await self.show_dates(ctx, doctor)

    async def ask_resched_confirm(self, ctx):
        appt = await self._own_appt(ctx, ctx.data.get("appt_id"))
        if not appt:
            await self.send(ctx.chat_id, ctx.t("appt_not_found"))
            return await self.show_menu(ctx)
        old = db.aware(appt["start"]).astimezone(TZ)
        new = datetime.fromisoformat(ctx.data["start"])
        await self.ask(ctx, "resched_confirm",
                       ctx.t("resched_summary", appt_id=appt["_id"], doctor=appt["doctor_name"],
                             old=f"{fmt_date(old, ctx.lang)} {fmt_time(old, ctx.lang)}",
                             new=f"{fmt_date(new, ctx.lang)} {fmt_time(new, ctx.lang)}"),
                       [[(ctx.t("btn_confirm"), "rs:confirm")]])

    async def on_btn_rs(self, ctx, arg):
        appt = await self._own_appt(ctx, ctx.data.get("appt_id"))
        if not appt:
            await self.send(ctx.chat_id, ctx.t("appt_not_found"))
            return await self.show_menu(ctx)
        new_start = datetime.fromisoformat(ctx.data["start"])
        doctor = await db.doctors.find_one({"_id": appt["doctor_id"]})
        async with self._slot_lock(doctor["_id"], new_start):
            return await self._resched_locked(ctx, appt, doctor, new_start)

    async def _resched_locked(self, ctx, appt, doctor, new_start):
        try:
            free = await self.slot_free(doctor, new_start, ignore_appt=appt["_id"])
        except calcom.CalError as exc:
            log.warning("slot re-check failed: %s", exc)
            await self.send(ctx.chat_id, ctx.t("resched_failed", phone=settings.CLINIC_PHONE))
            return await self.show_menu(ctx)
        if not free:
            await self.send(ctx.chat_id, ctx.t("slot_taken"))
            return await self.show_dates(ctx, doctor)
        try:
            booking = await calcom.reschedule_booking(appt["cal_uid"], new_start, "Rescheduled by patient via Telegram")
        except calcom.CalError as exc:
            log.warning("reschedule failed: %s", exc)
            if exc.is_client_error:
                await self.send(ctx.chat_id, ctx.t("slot_taken"))
                doctor = await db.doctors.find_one({"_id": appt["doctor_id"]})
                return await self.show_dates(ctx, doctor)
            await self.send(ctx.chat_id, ctx.t("resched_failed", phone=settings.CLINIC_PHONE))
            return await self.show_menu(ctx)
        end = booking.get("end")
        await db.appointments.update_one(
            {"_id": appt["_id"]},
            {"$set": {"cal_uid": booking.get("uid") or appt["cal_uid"],
                      "cal_booking_id": booking.get("id") or appt.get("cal_booking_id"),
                      "start": new_start.astimezone(ZoneInfo("UTC")),
                      "end": datetime.fromisoformat(end.replace("Z", "+00:00")) if end else None,
                      "reminders_sent": [], "attendance_confirmed": False},
             "$push": {"history": {"action": "rescheduled", "by": "patient", "from": appt["start"],
                                   "to": new_start.astimezone(ZoneInfo("UTC")), "at": db.utcnow()}}})
        await self.send(ctx.chat_id, ctx.t("rescheduled", appt_id=appt["_id"], date=fmt_date(new_start, ctx.lang),
                                           time=fmt_time(new_start, ctx.lang)))
        await self.show_menu(ctx)

    # ================================================================ issues + complaints
    async def start_ticket(self, ctx, ttype):
        ctx.sess["data"] = {"flow": "ticket", "ttype": ttype}
        labels = CATEGORIES[ttype][ctx.lang if ctx.lang in ("en", "hi") else "en"]
        buttons = [[(label, f"cat:{i}")] for i, label in enumerate(labels)]
        await self.ask(ctx, "ticket_cat", ctx.t(f"cat_{ttype}"), buttons)

    async def on_btn_cat(self, ctx, arg):
        ttype = ctx.data.get("ttype")
        try:
            i = int(arg)
            ctx.data["category"] = CATEGORIES[ttype]["en"][i]
            ctx.data["category_idx"] = i
        except (KeyError, IndexError, ValueError, TypeError):
            return await self.show_menu(ctx)
        await self.ask_details(ctx)

    async def on_text_ticket_desc(self, ctx, text):
        if len(text) < 10:
            return await self.send(ctx.chat_id, ctx.t("desc_short"))
        ctx.data["desc"] = text[:1000]
        ttype = ctx.data["ttype"]
        category = CATEGORIES[ttype][ctx.lang][ctx.data["category_idx"]]
        await self.ask(ctx, "ticket_confirm",
                       ctx.t("ticket_summary", kind=ctx.t(f"kind_{ttype}"), category=category,
                             name=ctx.patient["name"], phone=ctx.patient["phone"], desc=ctx.data["desc"]),
                       [[(ctx.t("btn_confirm"), "tk:confirm")], [(ctx.t("btn_edit"), "tk:edit")]])

    async def on_btn_tk(self, ctx, arg):
        ttype = ctx.data.get("ttype")
        if not ttype:
            return await self.show_menu(ctx)
        if arg == "edit":
            return await self.ask(ctx, "ticket_desc", ctx.t("ask_desc", kind=ctx.t(f"kind_{ttype}")))
        tid = await db.next_id("ISS" if ttype == "issue" else "CMP")
        await db.tickets.insert_one({
            "_id": tid, "type": ttype, "category": ctx.data["category"], "description": ctx.data["desc"],
            "chat_id": ctx.chat_id, "name": ctx.patient["name"], "phone": ctx.patient["phone"],
            "email": ctx.patient.get("email"), "language": ctx.lang, "status": "pending", "notes": [],
            "created_at": db.utcnow(), "updated_at": db.utcnow(),
        })
        await self.send(ctx.chat_id, ctx.t("ticket_saved", kind=ctx.t(f"kind_{ttype}"), tid=tid)
                        + "\n\n" + ctx.t("track_hint", tid=tid))
        await self.show_menu(ctx)
        await self.analyze_ticket(tid)

    async def analyze_ticket(self, tid):
        """AI for staff: one-line English summary, priority and mood (shown on the dashboard)."""
        ticket = await db.tickets.find_one({"_id": tid})
        if not ticket:
            return
        result = await ai.analyze_ticket(ticket["type"], ticket["category"], ticket["description"])
        if result:
            await db.tickets.update_one({"_id": tid}, {"$set": {
                "ai_summary": result["summary"], "priority": result["priority"], "sentiment": result["sentiment"]}})

    # ================================================================ emergency
    async def emergency(self, ctx, text):
        await self.send(ctx.chat_id, ctx.t("emergency", phone=settings.CLINIC_PHONE))
        alert_id = await db.next_id("ALT")
        await db.alerts.insert_one({
            "_id": alert_id, "chat_id": ctx.chat_id, "name": ctx.patient.get("name"),
            "phone": ctx.patient.get("phone"), "text": text[:1000], "status": "new", "created_at": db.utcnow(),
        })
        if settings.STAFF_CHAT_ID:
            try:
                await self.send(int(settings.STAFF_CHAT_ID),
                                t("en", "emergency_staff", alert_id=alert_id, name=ctx.patient.get("name") or "-",
                                  phone=ctx.patient.get("phone") or "-", text=text[:500]))
            except Exception:
                log.exception("could not notify staff chat")
        await self.show_menu(ctx)

    # ================================================================ reminders (called by the scheduler)
    async def on_btn_rem(self, ctx, arg):
        action, _, appt_id = arg.partition(":")
        appt = await self._own_appt(ctx, appt_id)
        if not appt or db.aware(appt["start"]) < db.utcnow():
            await self.send(ctx.chat_id, ctx.t("appt_not_found"))
            return await self.show_menu(ctx)
        if action == "ok":
            await db.appointments.update_one({"_id": appt_id}, {"$set": {"attendance_confirmed": True}})
            return await self.send(ctx.chat_id, ctx.t("attend_ok"))
        ctx.sess.update({"data": {"appt_id": appt_id}, "stack": []})
        if action == "cx":
            return await self.ask_cancel(ctx, appt)
        return await self.start_resched(ctx, appt)

    async def run_reminders(self):
        now = db.utcnow()
        due = await db.appointments.find(
            {"status": "booked", "start": {"$gt": now, "$lte": now + timedelta(hours=24)}}
        ).to_list(None)
        for appt in due:
            if not appt.get("chat_id"):  # walk-in patient without Telegram -> no reminder possible
                continue
            start = db.aware(appt["start"])
            sent = appt.get("reminders_sent") or []
            left = start - now
            created = db.aware(appt.get("created_at")) or now
            just_booked = now - created < timedelta(hours=1)
            kind = None
            if left <= timedelta(hours=2) and "2h" not in sent:
                kind = "2h"
            elif left > timedelta(hours=2) and "24h" not in sent and not just_booked:
                kind = "24h"
            if not kind:
                continue
            patient = await db.patients.find_one({"_id": appt["chat_id"]}) or {}
            lang = patient.get("language") or "en"
            local = start.astimezone(TZ)
            when = t(lang, "day_today" if local.date() == now.astimezone(TZ).date() else "day_tomorrow")
            text = t(lang, "reminder_24" if kind == "24h" else "reminder_2", appt_id=appt["_id"], when=when,
                     doctor=appt["doctor_name"], date=fmt_date(local, lang), time=fmt_time(local, lang))
            buttons = [[(t(lang, "btn_will_come"), f"rem:ok:{appt['_id']}")],
                       [(t(lang, "btn_resched"), f"rem:rs:{appt['_id']}"),
                        (t(lang, "btn_cancel_appt"), f"rem:cx:{appt['_id']}")]]
            try:
                await self.send(appt["chat_id"], text, buttons)
            except Exception as exc:  # e.g. the patient blocked the bot - record it, don't retry forever
                log.warning("reminder %s not delivered for %s: %s", kind, appt["_id"], exc)
            new_sent = sent + [kind] + (["24h"] if kind == "2h" and "24h" not in sent else [])
            await db.appointments.update_one({"_id": appt["_id"]}, {"$set": {"reminders_sent": new_sent}})

    # ================================================================ called by the dashboard / Cal.com webhook
    async def _notify_patient(self, chat_id, key, **kwargs):
        if not chat_id:
            return
        patient = await db.patients.find_one({"_id": chat_id}) or {}
        lang = patient.get("language") or "en"
        try:
            await self.send(chat_id, t(lang, key, **{k: (v(lang) if callable(v) else v) for k, v in kwargs.items()}))
        except Exception:
            log.exception("could not notify patient %s", chat_id)

    async def staff_book(self, doctor_id, start, name, phone, email, reason, staff_user):
        """Reception books an appointment for a walk-in / phone-call patient from the dashboard.
        If the phone number belongs to a Telegram patient, the booking is linked so they get reminders."""
        doctor = await db.doctors.find_one({"_id": doctor_id, "active": True})
        if not doctor:
            raise ValueError("Doctor not found or not active")
        async with self._slot_lock(doctor["_id"], start):
            return await self._staff_book_locked(doctor, start, name, phone, email, reason, staff_user)

    async def _staff_book_locked(self, doctor, start, name, phone, email, reason, staff_user):
        if not await self.slot_free(doctor, start):
            raise LookupError("That time is not free any more")
        dept = await db.departments.find_one({"_id": doctor["department"]})
        # link to Telegram only if that user proved the number is theirs (shared contact)
        tg_patient = await db.patients.find_one({"phone": phone, "phone_verified": True})
        chat_id = tg_patient["_id"] if tg_patient else None
        email = (email or "").strip() or None  # only the email typed at the desk - never an old saved one
        attendee_email = email or self.attendee_email({}, f"walkin{phone[-10:]}")
        appt_id = await db.next_id("APT")
        dept_en = (dept or {}).get("name_en", doctor["department"])
        notes = "\n".join(filter(None, [
            f"Booking ID: {appt_id}", f"Patient: {name}", f"Phone: {phone}", f"Email: {email}" if email else None,
            f"Doctor: {doctor['name']} ({dept_en})", f"Reason for visit: {reason}",
            f"Booked via: Clinic reception (walk-in) by {staff_user}",
        ]))
        booking = await calcom.create_booking(
            doctor["cal_event_type_id"], start, name, attendee_email, settings.CLINIC_TZ,
            metadata={"appointment_id": appt_id, "phone": phone, "reason": reason, "source": "reception"},
            phone=phone, notes=notes)
        end = booking.get("end")
        appt = {
            "_id": appt_id, "cal_uid": booking.get("uid"), "cal_booking_id": booking.get("id"),
            "chat_id": chat_id, "patient_name": name, "phone": phone, "email": email,
            "doctor_id": doctor["_id"], "doctor_name": doctor["name"], "department": doctor["department"],
            "start": start.astimezone(ZoneInfo("UTC")),
            "end": datetime.fromisoformat(end.replace("Z", "+00:00")) if end else None,
            "reason": reason, "status": "booked", "attendance_confirmed": False, "reminders_sent": [],
            "history": [], "source": "reception", "booked_by": staff_user, "created_at": db.utcnow(),
        }
        await db.appointments.insert_one(appt)
        if chat_id:  # tell the Telegram patient about the booking made at the desk
            local = start.astimezone(TZ)
            await self._notify_patient(chat_id, "desk_booked", appt_id=appt_id, doctor=doctor["name"],
                                       date=lambda lang: fmt_date(local, lang), time=lambda lang: fmt_time(local, lang))
        return appt

    async def staff_cancel(self, appt_id, reason, staff_user, notify=True):
        """Clinic staff cancels from the dashboard -> Cal.com -> DB -> Telegram message to the patient."""
        appt = await db.appointments.find_one({"_id": appt_id, "status": "booked"})
        if not appt:
            raise ValueError("Appointment not found or not active")
        await calcom.cancel_booking(appt["cal_uid"], reason or "Cancelled by clinic")
        await db.appointments.update_one(
            {"_id": appt_id},
            {"$set": {"status": "cancelled", "cancelled_by": "clinic", "cancelled_by_user": staff_user,
                      "cancel_reason": reason, "cancelled_at": db.utcnow()}})
        if notify:
            local = db.aware(appt["start"]).astimezone(TZ)
            await self._notify_patient(appt["chat_id"], "clinic_cancelled", appt_id=appt_id,
                                       date=lambda lang: fmt_date(local, lang), time=lambda lang: fmt_time(local, lang))
        return await db.appointments.find_one({"_id": appt_id})

    async def staff_reschedule(self, appt_id, new_start, staff_user, notify=True):
        """Clinic staff moves a booking from the dashboard. Raises LookupError if the slot is not free."""
        appt = await db.appointments.find_one({"_id": appt_id, "status": "booked"})
        if not appt:
            raise ValueError("Appointment not found or not active")
        doctor = await db.doctors.find_one({"_id": appt["doctor_id"]})
        async with self._slot_lock(doctor["_id"], new_start):
            if not await self.slot_free(doctor, new_start, ignore_appt=appt_id):
                raise LookupError("That time is not free any more")
            booking = await calcom.reschedule_booking(appt["cal_uid"], new_start, "Rescheduled by clinic")
        end = booking.get("end")
        new_utc = new_start.astimezone(ZoneInfo("UTC"))
        await db.appointments.update_one(
            {"_id": appt_id},
            {"$set": {"cal_uid": booking.get("uid") or appt["cal_uid"],
                      "cal_booking_id": booking.get("id") or appt.get("cal_booking_id"),
                      "start": new_utc,
                      "end": datetime.fromisoformat(end.replace("Z", "+00:00")) if end else None,
                      "reminders_sent": [], "attendance_confirmed": False},
             "$push": {"history": {"action": "rescheduled", "by": "clinic", "user": staff_user,
                                   "from": appt["start"], "to": new_utc, "at": db.utcnow()}}})
        if notify:
            local = new_start.astimezone(TZ)
            await self._notify_patient(appt["chat_id"], "clinic_rescheduled", appt_id=appt_id,
                                       date=lambda lang: fmt_date(local, lang), time=lambda lang: fmt_time(local, lang))
        return await db.appointments.find_one({"_id": appt_id})

    async def sync_with_calcom(self):
        """Find bookings that were cancelled / moved directly in Cal.com (e.g. via the links in Cal.com's
        emails or the Cal.com app) and update our database + tell the patient. No public URL needed."""
        result = {"checked": 0, "cancelled": 0, "rescheduled": 0, "errors": 0}
        since = db.utcnow() - timedelta(hours=2)
        appts = await db.appointments.find({"status": "booked", "start": {"$gte": since}}).to_list(None)
        for appt in appts:
            if not appt.get("cal_uid"):
                continue
            result["checked"] += 1
            try:
                booking = await calcom.get_booking(appt["cal_uid"])
                if booking.get("status") not in ("cancelled", "rejected"):
                    continue
                # Follow the reschedule chain: old booking -> rescheduledToUid -> new booking (max 5 hops)
                final, hops = booking, 0
                while final.get("status") in ("cancelled", "rejected") and final.get("rescheduledToUid") and hops < 5:
                    final = await calcom.get_booking(final["rescheduledToUid"])
                    hops += 1
            except calcom.CalError as exc:
                log.warning("Cal.com sync failed for %s: %s", appt["_id"], exc)
                result["errors"] += 1
                continue
            if hops and final.get("status") not in ("cancelled", "rejected") and final.get("start"):
                start = datetime.fromisoformat(final["start"].replace("Z", "+00:00"))
                end = final.get("end")
                await db.appointments.update_one(
                    {"_id": appt["_id"]},
                    {"$set": {"cal_uid": final["uid"], "cal_booking_id": final.get("id"), "start": start,
                              "end": datetime.fromisoformat(end.replace("Z", "+00:00")) if end else None,
                              "reminders_sent": [], "attendance_confirmed": False},
                     "$push": {"history": {"action": "rescheduled", "by": "calcom", "from": appt["start"],
                                           "to": start, "at": db.utcnow()}}})
                local = start.astimezone(TZ)
                await self._notify_patient(appt["chat_id"], "calcom_rescheduled", appt_id=appt["_id"],
                                           date=lambda lang: fmt_date(local, lang),
                                           time=lambda lang: fmt_time(local, lang))
                result["rescheduled"] += 1
            else:
                await db.appointments.update_one(
                    {"_id": appt["_id"]},
                    {"$set": {"status": "cancelled", "cancelled_by": "calcom",
                              "cancel_reason": booking.get("cancellationReason") or None,
                              "cancelled_at": db.utcnow()}})
                local = db.aware(appt["start"]).astimezone(TZ)
                await self._notify_patient(appt["chat_id"], "calcom_cancelled", appt_id=appt["_id"],
                                           date=lambda lang: fmt_date(local, lang),
                                           time=lambda lang: fmt_time(local, lang))
                result["cancelled"] += 1
        if result["cancelled"] or result["rescheduled"]:
            log.info("Cal.com sync: %s", result)
        return result

    async def notify_ticket_status(self, ticket, note=None):
        """Tell the patient about a status change. English staff notes are translated by AI for Hindi patients.
        Returns the translated note (or None)."""
        patient = await db.patients.find_one({"_id": ticket["chat_id"]}) or {}
        lang = patient.get("language") or "en"
        translated = None
        if note and lang == "hi" and ai.looks_english(note):
            translated = await ai.translate(note, "hi")
        note_text = Raw(t(lang, "ticket_note", note=translated or note)) if note else ""
        await self.send(ticket["chat_id"], t(lang, "ticket_status", tid=ticket["_id"],
                                             status=t(lang, f"status_{ticket['status']}"), note=note_text))
        return translated

    async def on_clinic_cancelled(self, cal_uid):
        appt = await db.appointments.find_one({"cal_uid": cal_uid, "status": "booked"})
        if not appt:
            return False
        await db.appointments.update_one(
            {"_id": appt["_id"]},
            {"$set": {"status": "cancelled", "cancelled_by": "clinic", "cancelled_at": db.utcnow()}})
        local = db.aware(appt["start"]).astimezone(TZ)
        await self._notify_patient(appt.get("chat_id"), "clinic_cancelled", appt_id=appt["_id"],
                                   date=lambda lang: fmt_date(local, lang), time=lambda lang: fmt_time(local, lang))
        return True

    async def on_clinic_rescheduled(self, old_uid, new_uid, start, end):
        appt = await db.appointments.find_one({"cal_uid": old_uid, "status": "booked"})
        if not appt:
            return False  # already handled (e.g. patient rescheduled from Telegram)
        await db.appointments.update_one(
            {"_id": appt["_id"]},
            {"$set": {"cal_uid": new_uid, "start": start, "end": end, "reminders_sent": [],
                      "attendance_confirmed": False},
             "$push": {"history": {"action": "rescheduled", "by": "clinic", "from": appt["start"], "to": start,
                                   "at": db.utcnow()}}})
        local = start.astimezone(TZ)
        await self._notify_patient(appt.get("chat_id"), "clinic_rescheduled", appt_id=appt["_id"],
                                   date=lambda lang: fmt_date(local, lang), time=lambda lang: fmt_time(local, lang))
        return True
