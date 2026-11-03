"""Load the clinic's departments and doctors from seed_data.json into MongoDB.

Run from the backend folder:  python scripts/seed.py      (after python scripts/setup_calcom_doctors.py)
Safe to run again. Doctors / departments that are no longer in the file are removed,
and old appointments of a replaced doctor ("replaces") are moved to the new doctor ID.
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # backend/ (config, db, calcom ...)

import db  # noqa: E402


async def main():
    await db.init()
    data = json.loads((Path(__file__).resolve().parent.parent / "data" / "seed_data.json").read_text(encoding="utf-8"))

    dept_ids = [d["_id"] for d in data["departments"]]
    for dept in data["departments"]:
        await db.departments.update_one({"_id": dept["_id"]}, {"$set": dept}, upsert=True)
    removed = await db.departments.delete_many({"_id": {"$nin": dept_ids}})
    print(f"Departments saved: {len(dept_ids)} (old removed: {removed.deleted_count})")

    doctor_ids = []
    for doc in data["doctors"]:
        doc = dict(doc)
        replaces = doc.pop("replaces", None)
        doctor_ids.append(doc["_id"])
        if not doc.get("cal_event_type_id"):
            doc["active"] = False
            print(f"  ! {doc['name']}: no cal_event_type_id -> INACTIVE (run python scripts/setup_calcom_doctors.py)")
        await db.doctors.update_one({"_id": doc["_id"]}, {"$set": doc}, upsert=True)
        if replaces:
            moved = await db.appointments.update_many(
                {"doctor_id": replaces},
                {"$set": {"doctor_id": doc["_id"], "doctor_name": doc["name"], "department": doc["department"]}})
            if moved.modified_count:
                print(f"  moved {moved.modified_count} old appointment(s) from {replaces} to {doc['_id']}")
    # doctors no longer in the file are removed (old appointments keep the doctor's name)
    gone = await db.doctors.delete_many({"_id": {"$nin": doctor_ids}})
    active = await db.doctors.count_documents({"active": True})
    print(f"Doctors saved: {len(doctor_ids)} (active: {active}, old removed: {gone.deleted_count})")
    await db.client.close()


if __name__ == "__main__":
    asyncio.run(main())
