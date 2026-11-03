"""Create / update every doctor in Cal.com from seed_data.json - one schedule (weekly timings) and one
event type (consultation, length = clinic "slot_minutes") per doctor. Writes the Cal.com IDs back into seed_data.json.

Run from the backend folder:  python scripts/setup_calcom_doctors.py   (safe to run again - it updates)
Then: python scripts/seed.py
"""
import asyncio
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # backend/ (config, db, calcom ...)

import calcom  # noqa: E402
from config import settings  # noqa: E402

SEED = Path(__file__).resolve().parent.parent / "data" / "seed_data.json"
DAYS = {"mon": "Monday", "tue": "Tuesday", "wed": "Wednesday", "thu": "Thursday", "fri": "Friday",
        "sat": "Saturday", "sun": "Sunday"}
V_SCHEDULES = "2024-06-11"
V_EVENT_TYPES = settings.CAL_VERSION_EVENT_TYPES


def availability(slots: dict) -> list:
    """{"mon": "10:00-13:00,16:00-19:00", ...} -> Cal.com availability blocks (same times grouped by day)."""
    blocks = {}
    for day, text in slots.items():
        for part in filter(None, (p.strip() for p in (text or "").split(","))):
            start, end = part.split("-")
            blocks.setdefault((start, end), []).append(DAYS[day])
    return [{"days": days, "startTime": s, "endTime": e} for (s, e), days in sorted(blocks.items())]


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


async def main():
    data = json.loads(SEED.read_text(encoding="utf-8"))
    clinic = data["clinic"]
    depts = {d["_id"]: d["name_en"] for d in data["departments"]}
    existing_types = {et.get("slug"): et for et in await calcom.list_event_types()}
    existing_schedules = {s["id"]: s for s in (await calcom._request("GET", "/schedules", V_SCHEDULES) or [])}

    for doc in data["doctors"]:
        dept = depts[doc["department"]]
        sched_body = {"name": f"{doc['name']} ({dept})", "timeZone": clinic["timezone"], "isDefault": False,
                      "availability": availability(doc["slots"])}
        if doc.get("cal_schedule_id") in existing_schedules:
            await calcom._request("PATCH", f"/schedules/{doc['cal_schedule_id']}", V_SCHEDULES, json=sched_body)
            action_s = "updated"
        else:
            sched = await calcom._request("POST", "/schedules", V_SCHEDULES, json=sched_body)
            doc["cal_schedule_id"] = sched["id"]
            action_s = "created"

        slug = slugify(doc["name"])
        et_body = {
            "title": f"{doc['name']} – {dept}",
            "description": f"{dept} consultation with {doc['name']} ({doc['experience_years']} yrs experience) "
                           f"at {clinic['name']}, {clinic['address']}. Booked via MediAssist (Telegram).",
            "lengthInMinutes": clinic["slot_minutes"],
            "slotInterval": clinic["slot_minutes"],  # a new slot every 10 minutes (10:00, 10:10, 10:20 ...)
            "scheduleId": doc["cal_schedule_id"],
            "minimumBookingNotice": clinic["min_booking_notice_minutes"],
            "locations": [{"type": "address", "address": f"{clinic['name']}, {clinic['address']}", "public": True}],
            # Title shown in Cal.com + emails, e.g. "Rohan Singh – Dr. Rakesh Verma (General Medicine)"
            "customName": f"{{Scheduler}} – {doc['name']} ({dept})",
            "hideOrganizerEmail": True,
        }
        current = existing_types.get(slug) or next(
            (et for et in existing_types.values() if et.get("id") == doc.get("cal_event_type_id")), None)
        if current:
            await calcom._request("PATCH", f"/event-types/{current['id']}", V_EVENT_TYPES, json=et_body)
            doc["cal_event_type_id"] = current["id"]
            action_e = "updated"
        else:
            et = await calcom._request("POST", "/event-types", V_EVENT_TYPES, json={**et_body, "slug": slug})
            doc["cal_event_type_id"] = et["id"]
            action_e = "created"
        print(f"{doc['_id']} {doc['name']:<22} schedule {action_s} #{doc['cal_schedule_id']:<9} "
              f"event type {action_e} #{doc['cal_event_type_id']}")

    SEED.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("\nSaved Cal.com IDs to seed_data.json. Next: python scripts/seed.py")


if __name__ == "__main__":
    asyncio.run(main())
