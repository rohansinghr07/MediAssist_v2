"""Exotel voice calls - used for the phone-call reminder 2 hours before an appointment.

The call goes to the patient and plays the "reminder" call flow you made in Exotel (App Bazaar).
Docs: https://developer.exotel.com/docs/voice-v1/api-reference/connect-to-flow
"""
import logging

import httpx

from config import settings

log = logging.getLogger("exotel")


class ExotelError(Exception):
    pass


def _local(phone):
    """+919876543210 -> 09876543210 (the format Exotel shows in its own examples for Indian numbers)."""
    digits = "".join(ch for ch in phone or "" if ch.isdigit())
    return "0" + digits[-10:] if len(digits) >= 10 else phone


async def call_reminder(phone, appt_id):
    """Ring the patient and connect them to the reminder flow. Returns {"sid", "status"}."""
    s = settings
    url = f"https://{s.EXOTEL_SUBDOMAIN}/v1/Accounts/{s.EXOTEL_SID}/Calls/connect.json"
    data = {
        "From": _local(phone),
        "CallerId": s.EXOTEL_CALLER_ID,
        "Url": f"http://my.exotel.com/{s.EXOTEL_SID}/exoml/start_voice/{s.EXOTEL_FLOW_ID}",
        "CallType": "trans",        # transactional (appointment reminder), not marketing
        "TimeOut": "30",           # ring for 30 seconds
        "TimeLimit": "90",         # the reminder never runs longer than 90 seconds
        "CustomField": appt_id,    # lets the flow read the booking details (dynamic greeting)
    }
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.post(url, data=data, auth=(s.EXOTEL_API_KEY, s.EXOTEL_API_TOKEN))
    except httpx.HTTPError as exc:
        raise ExotelError(f"Exotel not reachable: {exc}") from exc
    if r.status_code >= 400:
        try:
            msg = r.json().get("RestException", {}).get("Message") or r.text
        except ValueError:
            msg = r.text
        raise ExotelError(f"Exotel {r.status_code}: {msg[:200]}")
    call = (r.json() or {}).get("Call", {})
    return {"sid": call.get("Sid"), "status": call.get("Status")}


async def account_info():
    """Used by check_setup.py - confirms the keys work."""
    s = settings
    url = f"https://{s.EXOTEL_SUBDOMAIN}/v1/Accounts/{s.EXOTEL_SID}.json"
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.get(url, auth=(s.EXOTEL_API_KEY, s.EXOTEL_API_TOKEN))
    if r.status_code >= 400:
        raise ExotelError(f"Exotel {r.status_code}: {r.text[:200]}")
    return r.json()
