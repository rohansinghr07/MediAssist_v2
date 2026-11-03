"""Checks every connection before you start the bot.

Run from the backend folder:  python scripts/check_setup.py

It tests: .env values, MongoDB, Telegram token, Cal.com key (and lists your event type IDs),
free slots for each doctor, and the AI key.
"""
import asyncio
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # backend/ (config, db, calcom ...)

import ai  # noqa: E402
import calcom  # noqa: E402
import db  # noqa: E402
from config import settings  # noqa: E402

OK, BAD, WARN = "  [OK]  ", "  [FAIL]", "  [WARN]"


async def check_mongo():
    print("\n1) MongoDB")
    try:
        await db.init()
        await db.database.command("ping")
        n_doc = await db.doctors.count_documents({})
        print(OK, f"connected to '{settings.MONGODB_DB}', doctors in DB: {n_doc}")
        if n_doc == 0:
            print(WARN, "no doctors yet -> run: python scripts/seed.py")
        return True
    except Exception as exc:
        print(BAD, exc)
        return False


async def check_telegram():
    print("\n2) Telegram")
    if not settings.TELEGRAM_BOT_TOKEN:
        return print(BAD, "TELEGRAM_BOT_TOKEN is empty")
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/getMe")
        data = r.json()
        if data.get("ok"):
            print(OK, f"bot @{data['result']['username']}")
        else:
            print(BAD, data)
    except Exception as exc:
        print(BAD, exc)


async def check_calcom(mongo_ok):
    print("\n3) Cal.com")
    if not settings.CAL_API_KEY:
        return print(BAD, "CAL_API_KEY is empty")
    if "@" not in settings.FALLBACK_EMAIL:
        print(BAD, "FALLBACK_EMAIL is empty - bookings without patient email will fail")
    else:
        print(OK, f"fallback email: {settings.FALLBACK_EMAIL}")
    try:
        types = await calcom.list_event_types()
        print(OK, f"API key works. Your event types ({len(types)}):")
        for et in types:
            length = et.get("lengthInMinutes") or et.get("length")
            print(f"         id={et.get('id'):<10} {length} min   {et.get('title')}  (slug: {et.get('slug')})")
    except calcom.CalError as exc:
        print(BAD, exc)
        return
    if not mongo_ok:
        return
    tz = ZoneInfo(settings.CLINIC_TZ)
    today = datetime.now(tz).date()
    for doc in await db.doctors.find({"active": True}).to_list(None):
        try:
            slots = await calcom.get_slots(doc["cal_event_type_id"], today, today + timedelta(days=settings.BOOKING_DAYS_AHEAD),
                                           settings.CLINIC_TZ)
            total = sum(len(v) for v in slots.values())
            print(OK if total else WARN, f"{doc['name']}: {total} free slots in next {settings.BOOKING_DAYS_AHEAD} days")
        except calcom.CalError as exc:
            print(BAD, f"{doc['name']}: {exc}")


async def check_ai():
    print("\n4) AI")
    if not settings.LLM_API_KEY:
        return print(WARN, "LLM_API_KEY empty -> bot works with keywords only (no symptom suggestion)")
    key, emergency = await ai.suggest_department(
        "mere ghutne me 2 din se dard hai",
        [{"_id": "general_medicine", "name_en": "General Medicine"}, {"_id": "orthopedics", "name_en": "Orthopedics"},
         {"_id": "dermatology", "name_en": "Dermatology"}, {"_id": "pediatrics", "name_en": "Pediatrics"}])
    if key:
        print(OK, f"model {settings.LLM_MODEL}: 'ghutne me dard' (knee pain) -> {key}")
    else:
        print(BAD, "AI call failed - check LLM_API_KEY / LLM_BASE_URL / LLM_MODEL")


async def main():
    print(f"MediAssist setup check - clinic: {settings.CLINIC_NAME}")
    mongo_ok = await check_mongo()
    await check_telegram()
    await check_calcom(mongo_ok)
    await check_ai()
    print("\nDone.")


if __name__ == "__main__":
    asyncio.run(main())
