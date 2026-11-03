"""Offline test - runs full chats WITHOUT Telegram, Cal.com, MongoDB or AI keys.

Run from the backend folder:   python tests/simulate_chat.py
It prints every message like a chat transcript and stops with an error if something breaks.
"""
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import mongomock  # noqa: E402

import ai  # noqa: E402
import calcom  # noqa: E402
import db  # noqa: E402
from config import settings  # noqa: E402
from engine import Engine  # noqa: E402
from texts import t  # noqa: E402

TZ = ZoneInfo("Asia/Kolkata")
VERBOSE = "-q" not in sys.argv


# ---------------------------------------------------------------- async wrapper around mongomock
class Cursor:
    def __init__(self, cursor):
        self.c = cursor

    def sort(self, *a, **k):
        self.c = self.c.sort(*a, **k)
        return self

    def limit(self, n):
        self.c = self.c.limit(n)
        return self

    async def to_list(self, length=None):
        return list(self.c)


class Coll:
    def __init__(self, c):
        self.c = c

    def find(self, *a, **k):
        return Cursor(self.c.find(*a, **k))

    def __getattr__(self, name):
        fn = getattr(self.c, name)

        async def run(*a, **k):
            return fn(*a, **k)
        return run


class Database:
    def __init__(self, d):
        self.d = d

    def __getitem__(self, name):
        return Coll(self.d[name])

    async def command(self, *a, **k):
        return {"ok": 1}


class Client:
    def __init__(self):
        self.c = mongomock.MongoClient(tz_aware=True)

    def __getitem__(self, name):
        return Database(self.c[name])


# ---------------------------------------------------------------- fake Cal.com
BOOKINGS = {}
FAIL_NEXT_BOOKING = {"on": False}


def _make_slots():
    base = datetime.now(TZ).replace(hour=10, minute=0, second=0, microsecond=0) + timedelta(days=1)
    out = {}
    for d in range(3):
        day = base + timedelta(days=d)
        out[day.date().isoformat()] = [(day + timedelta(minutes=15 * i)).isoformat() for i in range(6)]
    return out


async def fake_get_slots(event_type_id, start, end, tz):
    return {d: [x for x in v if x not in REMOVED_SLOTS] for d, v in _make_slots().items()}


async def fake_create(event_type_id, start, name, email, tz, metadata=None, phone=None, notes=None):
    if FAIL_NEXT_BOOKING["on"]:
        FAIL_NEXT_BOOKING["on"] = False
        raise calcom.CalError("slot not available", 400)
    uid = f"uid{len(BOOKINGS) + 1}"
    BOOKINGS[uid] = {"uid": uid, "start": start, "email": email, "name": name, "status": "accepted",
                     "phone": phone, "notes": notes}
    REMOVED_SLOTS.add(start.astimezone(TZ).isoformat())  # like real Cal.com: a booked time is no longer offered
    end = start + timedelta(minutes=15)
    return {"uid": uid, "id": len(BOOKINGS), "start": start.isoformat(),
            "end": end.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")}


async def fake_cancel(uid, reason=""):
    BOOKINGS[uid]["status"] = "cancelled"
    if hasattr(BOOKINGS[uid].get("start"), "astimezone"):
        REMOVED_SLOTS.discard(BOOKINGS[uid]["start"].astimezone(TZ).isoformat())
    return BOOKINGS[uid]


async def fake_resched(uid, new_start, reason=""):
    new_uid = uid + "r"
    BOOKINGS[uid].update({"status": "cancelled", "rescheduledToUid": new_uid})  # same as real Cal.com
    BOOKINGS[new_uid] = {"uid": new_uid, "start": new_start, "status": "accepted"}
    if hasattr(BOOKINGS[uid].get("start"), "astimezone"):
        REMOVED_SLOTS.discard(BOOKINGS[uid]["start"].astimezone(TZ).isoformat())
    REMOVED_SLOTS.add(new_start.astimezone(TZ).isoformat())
    return {"uid": new_uid, "id": 99, "start": new_start.isoformat(), "end": None}


settings.FALLBACK_EMAIL = "clinic@gmail.com"
REMOVED_SLOTS = set()
calcom.get_slots = fake_get_slots
calcom.create_booking = fake_create
calcom.cancel_booking = fake_cancel
calcom.reschedule_booking = fake_resched


async def fake_get_booking(uid):
    b = dict(BOOKINGS[uid])
    if hasattr(b.get("start"), "isoformat"):
        b["start"] = b["start"].isoformat()
    return b


calcom.get_booking = fake_get_booking


# ---------------------------------------------------------------- fake AI (keywords only)
async def fake_suggest(symptoms, departments):
    if ai.is_emergency(symptoms):
        return None, True
    low = symptoms.lower()
    if "tooth" in low or "daant" in low:
        return "pediatrics", False
    if "stomach" in low or "pet" in low or "fever" in low or "पेट" in low:
        return "general_medicine", False
    return None, False


async def fake_intent(text):
    found = ai.keyword_intent(text)
    if found:
        return found
    if "ache" in text.lower() or "dard" in text.lower() or "दर्द" in text:
        return "symptoms"
    return None


async def fake_transcribe(audio, filename="voice.ogg"):
    return audio.decode("utf-8") if audio else None  # test "audio" is just the text


async def fake_faq(question, info, lang):
    if "sunday" in question.lower():
        return True, "The clinic is closed on Sunday." if lang == "en" else "रविवार को क्लिनिक बंद रहता है।"
    return False, ""


async def fake_clean(raw):
    return raw, ai.guess_language(raw)


async def fake_analyze(ticket_type, category, description):
    return {"summary": "Medicine not available", "priority": "high", "sentiment": "upset"}


async def fake_translate(text, lang):
    return "अनुवाद: " + text


async def fake_intent2(text):
    if "sunday" in text.lower() or "owner" in text.lower():
        return "faq"
    return await fake_intent(text)


ai.suggest_department = fake_suggest
ai.detect_intent = fake_intent2
ai.transcribe = fake_transcribe
ai.answer_faq = fake_faq
ai.clean_transcript = fake_clean
ai.analyze_ticket = fake_analyze
ai.translate = fake_translate


# ---------------------------------------------------------------- chat driver
class Chat:
    def __init__(self, engine, chat_id, name):
        self.engine, self.chat_id, self.name = engine, chat_id, name
        self.inbox = []

    def last_buttons(self):
        for msg in reversed(self.inbox):
            if msg[1]:
                return msg[1]
        return []

    def last_text(self):
        return self.inbox[-1][0] if self.inbox else ""

    def all_text_since(self, n):
        return "\n".join(m[0] for m in self.inbox[n:])

    async def say(self, text):
        if VERBOSE:
            print(f"\n👤 {self.name}: {text}")
        n = len(self.inbox)
        await self.engine.handle_text(self.chat_id, text, self.name)
        return self.all_text_since(n)

    async def tap(self, label_part):
        for row in self.last_buttons():
            for label, data in row:
                if label_part.lower() in label.lower():
                    if VERBOSE:
                        print(f"\n👤 {self.name}: [taps] {label}")
                    n = len(self.inbox)
                    await self.engine.handle_button(self.chat_id, data, self.name)
                    return self.all_text_since(n)
        raise AssertionError(f"No button containing '{label_part}'. Buttons: {self.last_buttons()}")

    async def tap_data(self, data):
        if VERBOSE:
            print(f"\n👤 {self.name}: [taps old button] {data}")
        n = len(self.inbox)
        await self.engine.handle_button(self.chat_id, data, self.name)
        return self.all_text_since(n)

    async def tap_first(self, prefix):
        for row in self.last_buttons():
            for label, data in row:
                if data.startswith(prefix):
                    if VERBOSE:
                        print(f"\n👤 {self.name}: [taps] {label}")
                    n = len(self.inbox)
                    await self.engine.handle_button(self.chat_id, data, self.name)
                    return self.all_text_since(n)
        raise AssertionError(f"No button with prefix '{prefix}'")


async def main():
    await db.init(client_override=Client())
    import json
    from pathlib import Path
    seed = json.loads((Path(__file__).resolve().parent.parent / "data" / "seed_data.json").read_text(encoding="utf-8"))
    for d in seed["departments"]:
        await db.departments.insert_one(d)
    for i, doc in enumerate(seed["doctors"], 1):
        await db.doctors.insert_one({**doc, "cal_event_type_id": 1000 + i})

    chats = {}

    async def sender(chat_id, text, buttons=None, contact_button=None, remove_keyboard=False):
        chat = chats.get(chat_id)
        if chat is None:
            if VERBOSE:
                print(f"\n📣 [to {chat_id}] {text}")
            return
        if contact_button:  # show the share-number keyboard like a button row
            buttons = [[(contact_button, "CONTACT")]]
        chat.inbox.append((text, buttons or []))
        if VERBOSE:
            print(f"🤖 {text}")
            for row in buttons or []:
                print("     " + "  ".join(f"[{label}]" for label, _ in row))

    engine = Engine(sender)
    rohan = Chat(engine, 111, "Rohan")
    chats[111] = rohan

    print("=" * 70, "\nTEST 1: new user -> language -> book via symptoms (AI suggests dept)")
    out = await rohan.say("hi")
    assert "choose your language" in out
    out = await rohan.tap("English")
    assert "Main Menu" in out
    await rohan.tap("Book Appointment")
    await rohan.tap("No, help me choose")
    out = await rohan.say("I have stomach ache from 3 days")
    assert "General Medicine" in out and "choose a doctor" in out  # suggestion + doctors in one step
    out = await rohan.tap("Rakesh")
    assert "choose a date" in out
    await rohan.tap_first("date:")
    await rohan.tap_first("time:")
    out = await rohan.say("R")
    assert "valid name" in out
    await rohan.say("rohan singh")
    out = await rohan.say("12345")
    assert "valid mobile" in out
    await rohan.say("91406 93067")
    out = await rohan.say("not-an-email")
    assert "doesn't look right" in out
    await rohan.tap("Skip")
    out = await rohan.say("Stomach ache")
    assert "Rohan Singh" in out and "+919140693067" in out
    out = await rohan.tap("Confirm")
    assert "APT-0001" in out
    appt = await db.appointments.find_one({"_id": "APT-0001"})
    assert appt["status"] == "booked" and appt["cal_uid"] == "uid1"
    assert BOOKINGS["uid1"]["email"] == "clinic+tg111@gmail.com"  # clinic email because patient skipped
    notes = BOOKINGS["uid1"]["notes"]  # booking details visible in Cal.com
    assert "Booking ID: APT-0001" in notes and "Patient: Rohan Singh" in notes and "+919140693067" in notes
    assert "Dr. Rakesh Verma (General Medicine)" in notes and "Reason for visit: Stomach ache" in notes
    assert BOOKINGS["uid1"]["phone"] == "+919140693067"

    print("=" * 70, "\nTEST 2: returning user, saved details, known department, slot taken once")
    db_sess = await db.sessions.find_one({"_id": 111})
    await db.sessions.update_one({"_id": 111}, {"$set": {"updated_at": db_sess["updated_at"] - timedelta(hours=2)}})
    out = await rohan.say("hello")
    assert "Welcome back, Rohan Singh" in out and "choose your language" not in out
    await rohan.tap("Book Appointment")
    await rohan.tap("Yes, I know")
    await rohan.tap("Pediatrics")
    await rohan.tap("Arjun")
    await rohan.tap_first("date:")
    await rohan.tap_first("time:")
    out = await rohan.tap("Use these")
    assert "reason" in out
    await rohan.say("Tooth pain")
    FAIL_NEXT_BOOKING["on"] = True
    out = await rohan.tap("Confirm")
    assert "no longer available" in out and "choose a date" in out
    await rohan.tap_first("date:")
    await rohan.tap_first("time:")
    await rohan.tap("Use these")
    await rohan.say("Tooth pain")
    out = await rohan.tap("Confirm")
    assert "APT-0003" in out  # APT-0002 number was used by the failed attempt

    print("=" * 70, "\nTEST 2b: slot taken by someone else while patient was deciding")
    await rohan.tap("Book Appointment")
    await rohan.tap("Yes, I know")
    await rohan.tap("Pediatrics")
    await rohan.tap("Priya")
    await rohan.tap_first("date:")
    await rohan.tap_first("time:")
    await rohan.tap("Use these")
    await rohan.say("Checkup")
    chosen = (await db.sessions.find_one({"_id": 111}))["data"]["start"]
    REMOVED_SLOTS.add(chosen)
    before = len(BOOKINGS)
    out = await rohan.tap("Confirm")
    assert "no longer available" in out and len(BOOKINGS) == before
    REMOVED_SLOTS.clear()
    await rohan.tap("Main Menu")

    print("=" * 70, "\nTEST 3: old button pressed after moving on -> rejected safely")
    out = await rohan.tap_data("doc:DR001")
    assert "no longer active" in out and "Main Menu" in out

    print("=" * 70, "\nTEST 4: free text intent -> My Appointments -> reschedule")
    out = await rohan.say("I want to reschedule my appointment")
    assert "upcoming appointments" in out
    await rohan.tap_first("ap:APT-0001")
    await rohan.tap("Reschedule")
    await rohan.tap_first("date:")
    buttons = rohan.last_buttons()
    last_time = [d for row in buttons for _, d in row if d.startswith("time:")][-1]
    await rohan.tap_data(last_time)
    out = await rohan.tap("Confirm")
    assert "moved to" in out
    appt = await db.appointments.find_one({"_id": "APT-0001"})
    assert appt["cal_uid"] == "uid1r" and len(appt["history"]) == 1

    print("=" * 70, "\nTEST 5: cancel")
    await rohan.tap("My Appointments")
    await rohan.tap_first("ap:APT-0003")
    out = await rohan.tap("Cancel appointment")
    assert "Are you sure" in out
    out = await rohan.tap("Yes, cancel")
    assert "cancelled" in out
    assert (await db.appointments.find_one({"_id": "APT-0003"}))["status"] == "cancelled"

    print("=" * 70, "\nTEST 6: Back button")
    await rohan.tap("Book Appointment")
    await rohan.tap("Yes, I know")
    out = await rohan.tap("Back")
    assert "Do you already know" in out
    out = await rohan.tap("Back")
    assert "Main Menu" in out

    print("=" * 70, "\nTEST 7: issue ticket in Hindi, short description rejected")
    await rohan.tap("Change Language")
    out = await rohan.tap("हिंदी")
    assert "मुख्य मेनू" in out
    await rohan.tap("समस्या दर्ज करें")
    await rohan.tap("पर्चा")
    await rohan.tap("इसी का उपयोग करें")
    out = await rohan.say("Ho")
    assert "कम से कम 10" in out
    await rohan.say("Doctor ne jo dawai likhi hai vo store par nahi mil rahi")
    out = await rohan.tap("पुष्टि करें")
    assert "ISS-0001" in out
    t1 = await db.tickets.find_one({"_id": "ISS-0001"})
    assert t1["category"] == "Prescription / Medicine" and t1["status"] == "pending"

    print("=" * 70, "\nTEST 8: dashboard changes ticket status -> patient notified")
    await db.tickets.update_one({"_id": "ISS-0001"}, {"$set": {"status": "resolved"}})
    n = len(rohan.inbox)
    await engine.notify_ticket_status(await db.tickets.find_one({"_id": "ISS-0001"}), "Medicine is now in stock")
    assert "हल हो गया" in rohan.all_text_since(n)

    print("=" * 70, "\nTEST 9: emergency")
    out = await rohan.say("mere papa ko seene me dard ho raha hai")
    assert "108" in out
    assert await db.alerts.count_documents({}) == 1

    print("=" * 70, "\nTEST 10: mid-flow typing -> Continue / Start over")
    await rohan.tap("शिकायत दर्ज करें")
    out = await rohan.say("hello")
    assert "पिछली बार" in out
    out = await rohan.tap("जारी रखें")
    assert "शिकायत किस बारे में है" in out

    print("=" * 70, "\nTEST 11: reminders (24h + 2h) and 'I'll come'")
    await rohan.tap("मुख्य मेनू")
    await db.appointments.update_one({"_id": "APT-0001"}, {"$set": {
        "start": db.utcnow() + timedelta(hours=20), "created_at": db.utcnow() - timedelta(days=1)}})
    n = len(rohan.inbox)
    await engine.run_reminders()
    assert "कल आपका अपॉइंटमेंट" in rohan.all_text_since(n)
    await engine.run_reminders()  # must not send twice
    assert len(rohan.inbox) == n + 1
    out = await rohan.tap("आऊँगा")
    assert "धन्यवाद" in out
    await db.appointments.update_one({"_id": "APT-0001"}, {"$set": {"start": db.utcnow() + timedelta(hours=1)}})
    n = len(rohan.inbox)
    await engine.run_reminders()
    assert "2 घंटे" in rohan.all_text_since(n)

    print("=" * 70, "\nTEST 12: clinic cancels in Cal.com (webhook)")
    n = len(rohan.inbox)
    assert await engine.on_clinic_cancelled("uid1r")
    assert "रद्द कर दी है" in rohan.all_text_since(n)

    print("=" * 70, "\nTEST 13: new user typing intent directly")
    priya = Chat(engine, 222, "Priya")
    chats[222] = priya
    out = await priya.say("mujhe appointment book karni hai")
    assert "choose your language" in out
    await priya.tap("English")
    out = await priya.say("mujhe appointment book karni hai")
    assert "क्या आप जानते हैं" in out  # Hinglish -> reply switches to Hindi
    out = await priya.say("random words")
    assert "जारी" in out
    out = await priya.say("I want to see the main menu please")  # English -> back to English
    assert "Do you want to continue" in out

    print("=" * 70, "\nTEST 14: tracking by number")
    await db.tickets.update_one({"_id": "ISS-0001"}, {"$push": {"notes": {"text": "Medicine is now in stock", "by": "admin",
                                                                         "at": db.utcnow()}}})
    out = await rohan.say("iss-1")  # loose format works
    assert "ISS-0001" in out and "हल हो गया" in out and "Medicine is now in stock" in out
    out = await rohan.tap("स्थिति देखें")
    assert "APT-0001" in str(rohan.last_buttons()) and "ISS-0001" in str(rohan.last_buttons())
    out = await rohan.tap_first("tr:APT-0001")
    assert "APT-0001" in out and "समय बदला गया" in out  # reschedule history shown
    out = await priya.say("APT-0001")  # someone else's number
    assert "couldn't find" in out
    out = await priya.say("/track")
    assert "type your booking or ticket number" in out
    out = await priya.say("hello there")
    assert "valid number" in out
    # a number inside a description must NOT jump to tracking
    await priya.tap("Main Menu")
    await priya.tap("Register a Complaint")
    await priya.tap("Waiting Time")
    await priya.say("Priya Verma")
    await priya.say("9812345678")
    await priya.tap("Skip")
    out = await priya.say("For APT-0001 I waited for more than one hour")
    assert "Please confirm the complaint details" in out
    out = await priya.tap("Confirm")
    assert "CMP-0001" in out and "Track Status" in out

    print("=" * 70, "\nTEST 15: Telegram shows the tapped choice in the old message")
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from telegram_bot import pressed_label, with_choice
    markup = InlineKeyboardMarkup([[InlineKeyboardButton("📅 Book Appointment", callback_data="m:book")],
                                   [InlineKeyboardButton("🔎 Track Status", callback_data="m:track")]])
    assert pressed_label(markup, "m:track") == "🔎 Track Status"
    assert with_choice("<b>Main Menu</b>", "A & B") == "<b>Main Menu</b>\n\n👉 <b>A &amp; B</b>"

    print("=" * 70, "\nTEST 16: booking changed directly in Cal.com (email link) -> auto-sync")
    for _ in range(2):  # book two appointments for Priya
        await priya.tap("Book Appointment")
        await priya.tap("Yes, I know")
        await priya.tap("Pediatrics")
        await priya.tap("Priya")
        await priya.tap_first("date:")
        await priya.tap_first("time:")
        await priya.tap("Use these")
        await priya.say("Tooth check")
        await priya.tap("Confirm")
    a1, a2 = (await db.appointments.find({"chat_id": 222}).sort("_id", 1).to_list(None))[-2:]
    # 1) patient cancels from the Cal.com email
    BOOKINGS[a1["cal_uid"]]["status"] = "cancelled"
    # 2) patient reschedules from the Cal.com email -> old cancelled + rescheduledToUid, new accepted
    new_start = db.aware(a2["start"]) + timedelta(days=1)
    BOOKINGS[a2["cal_uid"]].update({"status": "cancelled", "rescheduledToUid": "emailnew"})
    BOOKINGS["emailnew"] = {"uid": "emailnew", "status": "accepted", "start": new_start.isoformat(), "end": None}
    n = len(priya.inbox)
    res = await engine.sync_with_calcom()
    assert res["cancelled"] == 1 and res["rescheduled"] == 1, res
    a1n = await db.appointments.find_one({"_id": a1["_id"]})
    a2n = await db.appointments.find_one({"_id": a2["_id"]})
    assert a1n["status"] == "cancelled" and a1n["cancelled_by"] == "calcom"
    assert a2n["status"] == "booked" and a2n["cal_uid"] == "emailnew" and db.aware(a2n["start"]) == new_start
    msgs = priya.all_text_since(n)
    assert "has been cancelled" in msgs and "has been moved" in msgs
    assert (await engine.sync_with_calcom())["cancelled"] == 0  # nothing twice
    out = await priya.say(a1["_id"])
    assert "via Cal.com" in out

    print("=" * 70, "\nTEST 17: AI features - voice, FAQ, smart ticket, translated staff note")
    out_n = len(priya.inbox)
    await engine.handle_voice(222, "What time do you open on Sunday?".encode(), 4)
    out = priya.all_text_since(out_n)
    assert "Did I hear you correctly" in out and "closed on Sunday" not in out  # asks first
    out = await priya.tap("Yes")
    assert "closed on Sunday" in out and "Answered by MediAssist AI" in out
    # Hindi voice about symptoms -> Hindi confirm -> हाँ -> department + doctors directly
    out_n = len(priya.inbox)
    await engine.handle_voice(222, "मुझे तीन दिन से पेट में दर्द है".encode(), 4)
    out = priya.all_text_since(out_n)
    assert "क्या मैंने सही सुना" in out
    out = await priya.tap("हाँ")
    assert "सामान्य चिकित्सा" in out and "डॉक्टर चुनें" in out and "Rakesh" in str(priya.last_buttons())
    # wrong transcript -> No -> asked to repeat, nothing else happens
    await priya.tap("मुख्य मेनू")
    await engine.handle_voice(222, "मुझे शर्म दरते हैं".encode(), 3)
    out = await priya.tap("नहीं")
    assert "फिर से भेजें" in out
    out = await priya.say("I want the main menu please")
    assert "Main Menu" in out
    out_n = len(priya.inbox)
    await engine.handle_voice(222, b"x", 500)  # too long
    assert "under 90 seconds" in priya.all_text_since(out_n)
    out = await priya.say("Who is the owner?")
    assert "don't have that information" in out
    # smart ticket: AI fields saved for staff
    cmp1 = await db.tickets.find_one({"_id": "CMP-0001"})
    assert cmp1["priority"] == "high" and cmp1["ai_summary"] == "Medicine not available"
    # translated note for a Hindi patient (Rohan), original kept
    n = len(rohan.inbox)
    translated = await engine.notify_ticket_status(await db.tickets.find_one({"_id": "ISS-0001"}), "Please collect it today")
    assert translated == "अनुवाद: Please collect it today" and "अनुवाद" in rohan.all_text_since(n)
    n = len(priya.inbox)
    assert await engine.notify_ticket_status(await db.tickets.find_one({"_id": "CMP-0001"}), "Sorry for the wait") is None
    assert "Sorry for the wait" in priya.all_text_since(n)  # English patient gets it unchanged

    print("=" * 70, "\nTEST 18: walk-in booking from the dashboard (reception)")
    slots = await engine.fetch_slots(await db.doctors.find_one({"_id": "DR002"}))
    day = sorted(slots)[-1]
    # a0) the number was only TYPED in the bot (anyone can type any number) -> NOT linked
    a0 = await engine.staff_book("DR002", datetime.fromisoformat(slots[day][5]), "Rohan Singh", "+919140693067",
                                 None, "Typed number check", "admin")
    assert a0["chat_id"] is None
    await engine.staff_cancel(a0["_id"], "test", "admin")
    await db.patients.update_one({"_id": 111}, {"$set": {"phone_verified": True}})  # Rohan shared his contact
    # a) phone of a Telegram patient who SHARED the number -> linked, gets Telegram confirmation + reminders
    n = len(rohan.inbox)
    a1 = await engine.staff_book("DR002", datetime.fromisoformat(slots[day][0]), "Rohan Singh", "+919140693067",
                                 None, "Follow-up", "admin")
    assert a1["chat_id"] == 111 and a1["source"] == "reception"
    assert "रिसेप्शन ने आपका अपॉइंटमेंट" in rohan.all_text_since(n)  # Rohan's language is Hindi here
    assert "Booked via: Clinic reception (walk-in) by admin" in BOOKINGS[a1["cal_uid"]]["notes"]
    # email left blank at the desk -> the patient's old saved email must NOT be used
    assert a1["email"] is None and BOOKINGS[a1["cal_uid"]]["email"].startswith("clinic+")
    # b) new walk-in patient (no Telegram) -> no chat, reminders skipped, cancel works without a message
    a2 = await engine.staff_book("DR002", datetime.fromisoformat(slots[day][1]), "Walk In", "+919000000001",
                                 None, "Fever", "admin")
    assert a2["chat_id"] is None and BOOKINGS[a2["cal_uid"]]["email"].startswith("clinic+")
    await db.appointments.update_one({"_id": a2["_id"]}, {"$set": {"start": db.utcnow() + timedelta(hours=1)}})
    await engine.run_reminders()  # must not crash on a booking without Telegram
    assert (await db.appointments.find_one({"_id": a2["_id"]}))["reminders_sent"] == []
    await engine.staff_cancel(a2["_id"], "test", "admin")
    # c) walk-in without Telegram joins the bot later and shares the same phone -> booking gets linked + message
    a3 = await engine.staff_book("DR002", datetime.fromisoformat(slots[day][2]), "Late Joiner", "+919000000002",
                                 None, "Cough", "admin")
    assert a3["chat_id"] is None
    await db.patients.insert_one({"_id": 999, "name": "Late Joiner", "phone": "+919000000002", "language": "en"})
    assert await engine.link_desk_bookings(999, "+919000000002") == 1
    assert (await db.appointments.find_one({"_id": a3["_id"]}))["chat_id"] == 999
    assert await engine.link_desk_bookings(999, "+919000000002") == 0  # not linked twice
    # d) brand-new Telegram user taps "Share my number" -> reception booking linked + confirmation
    a4 = await engine.staff_book("DR002", datetime.fromisoformat(slots[day][3]), "Dhruv K", "+919057468262",
                                 None, "Check-up", "admin")
    dhruv = Chat(engine, 555, "Dhruv"); chats[555] = dhruv
    await dhruv.say("/start")
    await dhruv.tap("English")
    assert "Share my number" in dhruv.all_text_since(0) or any("Share my number" in l for _, rows in dhruv.inbox for r in rows for l, _ in r)
    n = len(dhruv.inbox)
    await engine.handle_contact(555, "+91 90574 68262", own=False)
    assert "your own" in dhruv.all_text_since(n)
    await engine.handle_contact(555, "919057468262", own=True, tg_name="Dhruv K")
    assert "Number saved" in dhruv.all_text_since(n) and a4["_id"] in dhruv.all_text_since(n)
    assert (await db.appointments.find_one({"_id": a4["_id"]}))["chat_id"] == 555

    print("=" * 70, "\nTEST 19b: website deep links (t.me/bot?start=...)")
    web = Chat(engine, 777, "Web"); chats[777] = web
    await engine.handle_start(777, "doc_DR002", "Web User")   # new user -> language first
    assert "choose your language" in web.all_text_since(0).lower()
    n = len(web.inbox)
    await web.tap("English")                                   # then straight to Dr. Rakesh Verma's dates
    assert "Rakesh" in web.all_text_since(n) and "Main Menu" not in web.all_text_since(n)
    n = len(web.inbox)
    await engine.handle_start(777, "book", "Web User")          # known user -> booking starts at once
    assert web.all_text_since(n) and (await db.sessions.find_one({"_id": 777}))["state"] == "book_know"
    await engine.handle_start(777, "track", "Web User")
    assert (await db.sessions.find_one({"_id": 777}))["state"] == "track_id"
    await engine.handle_start(777, "<script>x", "Web User")    # junk payload -> just the menu
    assert (await db.sessions.find_one({"_id": 777}))["state"] == "menu"
    assert (await db.appointments.find_one({"_id": a2["_id"]}))["status"] == "cancelled"
    # c) same slot twice -> refused
    try:
        await engine.staff_book("DR002", datetime.fromisoformat(slots[day][0]), "X Y", "+919000000002", None, "Test", "admin")
        REMOVED_SLOTS.add(slots[day][0])
        await engine.staff_book("DR002", datetime.fromisoformat(slots[day][0]), "X Y", "+919000000002", None, "Test", "admin")
        raise AssertionError("double booking allowed")
    except LookupError:
        pass
    REMOVED_SLOTS.clear()

    print("=" * 70, "\nTEST 20: 10-minute slots -> Morning / Afternoon / Evening step first")
    async def full_day_slots(event_type_id, start, end, tz):
        base = datetime.now(TZ).replace(hour=9, minute=0, second=0, microsecond=0) + timedelta(days=1)
        return {base.date().isoformat(): [(base + timedelta(minutes=10 * i)).isoformat() for i in range(66)]}  # 9 am - 8 pm
    calcom.get_slots = full_day_slots
    try:
        many = Chat(engine, 888, "Many"); chats[888] = many
        await db.patients.insert_one({"_id": 888, "name": "Many Slots", "phone": "+919000000888", "language": "en"})
        await engine.handle_start(888, "doc_DR002", "Many")
        await many.tap_first("date:")
        assert "When would you like to come?" in many.all_text_since(0)
        n = len(many.inbox)
        await many.tap("Evening")
        labels = [l for row in many.last_buttons() for l, d in row if d.startswith("time:")]
        assert labels and all(("pm" in l.lower()) for l in labels) and len(labels) == 24, labels  # 4 pm - 8 pm
        await many.tap("Back")
        assert "When would you like to come?" in many.all_text_since(n)
    finally:
        calcom.get_slots = fake_get_slots

    print("=" * 70, "\nTEST 21: safety - same slot at the same moment, double tap, typed numbers")
    real_create = calcom.create_booking
    async def slow_create(*a, **kw):  # a slow Cal.com makes the race window wide
        await asyncio.sleep(0.05)
        return await real_create(*a, **kw)
    calcom.create_booking = slow_create
    try:
        free = await engine.fetch_slots(await db.doctors.find_one({"_id": "DR004"}))
        slot = datetime.fromisoformat(sorted(free)[0] and free[sorted(free)[0]][0])
        results = await asyncio.gather(
            engine.staff_book("DR004", slot, "Desk One", "+919811111111", None, "Race", "admin"),
            engine.staff_book("DR004", slot, "Desk Two", "+919822222222", None, "Race", "admin"),
            return_exceptions=True)
        ok = [r for r in results if isinstance(r, dict)]
        assert len(ok) == 1 and isinstance([r for r in results if not isinstance(r, dict)][0], LookupError), results
        assert await db.appointments.count_documents({"doctor_id": "DR004", "start": slot.astimezone(timezone.utc),
                                                      "status": "booked"}) == 1

        # double tap on "Confirm" in the bot -> only one booking
        dbl = Chat(engine, 4040, "Double"); chats[4040] = dbl
        await db.patients.insert_one({"_id": 4040, "name": "Double Tap", "phone": "+919833333333",
                                      "phone_verified": True, "language": "en"})
        await engine.handle_start(4040, "doc_DR003", "Double")
        await dbl.tap_first("date:"); await dbl.tap_first("time:"); await dbl.tap("Use these"); await dbl.say("Fever")
        before = await db.appointments.count_documents({"chat_id": 4040})
        await asyncio.gather(engine.handle_button(4040, "bk:confirm"), engine.handle_button(4040, "bk:confirm"))
        assert await db.appointments.count_documents({"chat_id": 4040}) == before + 1

        # a stranger TYPES someone else's number -> the clinic booking is NOT handed over
        desk = await engine.staff_book("DR003", datetime.fromisoformat(free[sorted(free)[-1]][-1]), "Real Owner",
                                       "+919844444444", None, "Check-up", "admin")
        bad = Chat(engine, 5050, "Stranger"); chats[5050] = bad
        await db.patients.insert_one({"_id": 5050, "language": "en"})
        await bad.say("book appointment"); await bad.tap("Yes, I know"); await bad.tap("Pediatrics")
        await bad.tap("Arjun"); await bad.tap_first("date:"); await bad.tap_first("time:")
        await bad.say("Some One")
        assert "Share my number" in bad.all_text_since(0) or any("Share" in l for _, r in bad.inbox for row in r for l, _ in row)
        n = len(bad.inbox)
        await bad.say("98444 44444")                                 # typed, not shared
        await bad.tap("Skip")
        assert (await db.appointments.find_one({"_id": desk["_id"]}))["chat_id"] is None
        assert "confirms the number is yours" in bad.all_text_since(n)  # asked to share instead
        # the real owner shares the contact while the bot asks for the phone -> linked, flow continues
        own = Chat(engine, 6060, "Owner"); chats[6060] = own
        await db.patients.insert_one({"_id": 6060, "language": "en"})
        await own.say("book appointment"); await own.tap("Yes, I know"); await own.tap("Pediatrics")
        await own.tap("Arjun"); await own.tap_first("date:"); await own.tap_first("time:"); await own.say("Real Owner")
        n = len(own.inbox)
        await engine.handle_contact(6060, "919844444444", own=True, tg_name="Real Owner")
        assert (await db.appointments.find_one({"_id": desk["_id"]}))["chat_id"] == 6060
        assert "email" in own.all_text_since(n).lower()               # booking continues with the email step
    finally:
        calcom.create_booking = real_create

    print("=" * 70, "\nTEST 22: website chat - same engine, messages stored for the browser")
    wid = "web:" + "a" * 32

    async def web_inbox(after=None):
        q = {"chat_id": wid, "from": "bot"}
        docs = await db.web_messages.find(q).sort("_id", 1).to_list(None)
        return docs

    async def web_tap(part):
        last = [d for d in await web_inbox() if d["buttons"]][-1]
        data = next(dt for row in last["buttons"] for lbl, dt in row if part.lower() in lbl.lower())
        await engine.handle_button(wid, data)

    await engine.handle_text(wid, "/start")
    assert "choose your language" in (await web_inbox())[-1]["text"].lower()
    await web_tap("English")
    texts = " ".join(d["text"] for d in await web_inbox())
    assert "Share my number" not in texts                      # no Telegram-only prompt on the website
    await engine.handle_text(wid, "book appointment")
    await web_tap("Yes, I know"); await web_tap("General Medicine"); await web_tap("Rakesh")
    days = [d for d in await web_inbox() if d["buttons"]][-1]["buttons"]
    await engine.handle_button(wid, days[0][0][1])               # first date
    last = [d for d in await web_inbox() if d["buttons"]][-1]
    first_time = next(dt for row in last["buttons"] for lbl, dt in row if dt.startswith(("time:", "part:")))
    await engine.handle_button(wid, first_time)
    last = [d for d in await web_inbox() if d["buttons"]][-1]
    if any(dt.startswith("time:") for row in last["buttons"] for _, dt in row):
        await engine.handle_button(wid, next(dt for row in last["buttons"] for _, dt in row if dt.startswith("time:")))
    await engine.handle_text(wid, "Web Patient")
    assert "Share my number" not in (await web_inbox())[-1]["text"]
    await engine.handle_text(wid, "98765 11111")
    await web_tap("Skip")
    await engine.handle_text(wid, "Fever since yesterday")
    await web_tap("Confirm")
    msgs = " ".join(d["text"] for d in await web_inbox())
    assert "Appointment booked" in msgs and "₹500" in msgs       # fee line in the confirmation
    appt = await db.appointments.find_one({"chat_id": wid})
    assert appt and appt["source"] == "website"
    assert "website chat" in BOOKINGS[appt["cal_uid"]]["notes"]
    # voice works the same way as Telegram
    await engine.handle_voice(wid, "mujhe sar me dard hai".encode(), 3, "voice.webm")
    vmsg = (await web_inbox())[-1]
    assert any(dt == "vc:yes" for row in vmsg["buttons"] for _, dt in row)   # "Did I hear you correctly?" Yes/No
    # Telegram bookings get the fee line too
    assert "₹500" in t("en", "booked", appt_id="APT-1", doctor="D", dept="X", date="d", time="t")
    assert "₹500" in t("hi", "booked", appt_id="APT-1", doctor="D", dept="X", date="d", time="t")

    print("\n" + "=" * 70 + "\nALL 22 TESTS PASSED ✅")


if __name__ == "__main__":
    asyncio.run(main())
