"""Demo dashboard with SAMPLE data - no MongoDB, Cal.com or Telegram needed.

Run from the backend folder:   python tests/demo_server.py
Open http://127.0.0.1:8010  (login: admin / the ADMIN_PASSWORD in .env, or change-me)
Nothing here touches your real database or Cal.com.
"""
import asyncio
import os
import sys
from datetime import timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import simulate_chat as sim  # noqa: E402  (patches calcom + ai with fakes)
import db  # noqa: E402
from engine import Engine  # noqa: E402


async def seed_demo():
    await db.init(client_override=sim.Client())
    import json
    from pathlib import Path
    seed = json.loads((Path(__file__).resolve().parent.parent / "data" / "seed_data.json").read_text(encoding="utf-8"))
    for d in seed["departments"]:
        await db.departments.insert_one(d)
    for i, doc in enumerate(seed["doctors"], 1):
        await db.doctors.insert_one({**doc, "cal_event_type_id": 1000 + i if i != 4 else 0, "active": i != 4})

    now = db.utcnow()
    people = [("Rohan Singh", "+919140693067", "Pet me dard", "DR001", "general_medicine"),
              ("Priya Gupta", "+919812345678", "Tooth pain since 2 days", "DR003", "pediatrics"),
              ("Amit Kumar", "+919900112233", "Fever and cold", "DR002", "general_medicine"),
              ("Sunita Devi", "+919876501234", "Regular check-up", "DR002", "general_medicine"),
              ("Vikram Rao", "+919765432109", "Cleaning", "DR003", "pediatrics")]
    doctors = {d["_id"]: d for d in seed["doctors"]}
    slots = sim._make_slots()
    first_day = sorted(slots)[0]
    from datetime import datetime
    for i, (name, phone, reason, doc_id, dept) in enumerate(people):
        day = sorted(slots)[i // 3]
        iso = slots[day][(i * 2) % 6]
        sim.REMOVED_SLOTS.add(iso)  # booked -> no longer shown as free
        start = datetime.fromisoformat(iso)
        await db.appointments.insert_one({
            "_id": f"APT-{i + 1:04d}", "cal_uid": f"uid{i + 1}", "chat_id": 1000 + i, "patient_name": name, "phone": phone,
            "doctor_id": doc_id, "doctor_name": doctors[doc_id]["name"], "department": dept,
            "start": start.astimezone(sim.ZoneInfo("UTC")), "end": None, "reason": reason, "status": "booked",
            "attendance_confirmed": i == 0, "reminders_sent": [], "history": [] if i != 2 else [{"action": "rescheduled"}],
            "source": "telegram", "created_at": now - timedelta(minutes=30 * (i + 1))})
        sim.BOOKINGS[f"uid{i + 1}"] = {"uid": f"uid{i + 1}", "status": "accepted"}
        await db.patients.insert_one({"_id": 1000 + i, "name": name, "phone": phone, "language": "hi" if i % 2 else "en"})
    # one appointment today (earlier), one cancelled
    await db.appointments.insert_one({
        "_id": "APT-0006", "cal_uid": "uid6", "chat_id": 1001, "patient_name": "Neha Sharma", "phone": "+919811122233",
        "doctor_id": "DR002", "doctor_name": "Dr. Rakesh Verma", "department": "general_medicine",
        "start": now + timedelta(hours=2), "reason": "Headache", "status": "booked", "reminders_sent": ["24h", "2h"],
        "history": [], "created_at": now - timedelta(days=1)})
    await db.appointments.insert_one({
        "_id": "APT-0007", "cal_uid": "uid7", "chat_id": 1002, "patient_name": "Karan Mehta", "phone": "+919822233344",
        "doctor_id": "DR001", "doctor_name": "Dr. Anjali Mehra", "department": "general_medicine",
        "start": now + timedelta(hours=3), "reason": "Back pain", "status": "cancelled", "cancelled_by": "patient",
        "reminders_sent": [], "history": [], "created_at": now - timedelta(days=2)})
    sim.BOOKINGS["uid6"] = {"uid": "uid6", "status": "accepted"}
    sim.BOOKINGS["uid7"] = {"uid": "uid7", "status": "cancelled"}
    await db.tickets.insert_many([
        {"_id": "ISS-0001", "type": "issue", "category": "Prescription / Medicine", "chat_id": 1001, "name": "Priya Gupta",
         "phone": "+919812345678", "description": "Doctor ne jo dawai likhi hai vo store par nahi mil rahi",
         "language": "hi", "status": "pending", "notes": [], "created_at": now - timedelta(hours=3),
         "ai_summary": "Prescribed medicine not available at the store", "priority": "high", "sentiment": "upset"},
        {"_id": "CMP-0001", "type": "complaint", "category": "Waiting Time", "chat_id": 1002, "name": "Amit Kumar",
         "phone": "+919900112233", "description": "Had to wait 1 hour after my appointment time.",
         "language": "en", "status": "in_progress", "notes": [{"text": "Checking with reception", "by": "admin", "at": now}],
         "created_at": now - timedelta(days=1),
         "ai_summary": "Waited one hour past appointment time", "priority": "medium", "sentiment": "angry"},
        {"_id": "ISS-0002", "type": "issue", "category": "Lab Report", "chat_id": 1003, "name": "Sunita Devi",
         "phone": "+919876501234", "description": "Blood test report not received on email yet.", "language": "en",
         "status": "resolved", "notes": [], "created_at": now - timedelta(days=2)},
    ])
    for prefix, seq in (("APT", 7), ("ISS", 2), ("CMP", 1), ("ALT", 1)):  # keep ID counters in step with sample data
        await db.counters.insert_one({"_id": prefix, "seq": seq})
    await db.alerts.insert_one({"_id": "ALT-0001", "chat_id": 1004, "name": "Vikram Rao", "phone": "+919765432109",
                                "text": "mere papa ko seene me dard ho raha hai", "status": "new",
                                "created_at": now - timedelta(minutes=12)})


async def sender(chat_id, text, buttons=None, **kw):
    print(f"\n📨 Telegram -> {chat_id}: {text}\n")


def main():
    import uvicorn
    from fastapi import FastAPI
    from api import router
    from public_api import router as public_router
    from web_chat import router as chat_router
    from main import mount_frontends

    asyncio.run(seed_demo())
    app = FastAPI()
    app.state.engines = {"engine": Engine(sender)}
    app.include_router(router)
    app.include_router(public_router)
    app.include_router(chat_router)

    app.state.bot_username = "CityClinicKotaBot"  # sample - real one comes from Telegram
    mount_frontends(app)
    print("Demo website: http://127.0.0.1:8010   dashboard: http://127.0.0.1:8010/staff/")
    uvicorn.run(app, host="127.0.0.1", port=8010, log_level="warning")


if __name__ == "__main__":
    main()
