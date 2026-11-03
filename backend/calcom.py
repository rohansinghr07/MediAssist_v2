"""Cal.com API v2 client - slots, bookings, cancel, reschedule.

Cal.com is the master for doctor availability and bookings.
Each doctor = one Cal.com event type (its ID is stored in doctors.cal_event_type_id).
"""
import logging
from datetime import date, datetime, timezone

import httpx

from config import settings

log = logging.getLogger("calcom")


class CalError(Exception):
    def __init__(self, message, status=None, body=None):
        super().__init__(message)
        self.status = status
        self.body = body

    @property
    def is_client_error(self):
        return self.status is not None and 400 <= self.status < 500


def _headers(version: str) -> dict:
    return {
        "Authorization": f"Bearer {settings.CAL_API_KEY}",
        "cal-api-version": version,
        "Content-Type": "application/json",
    }


def _error_message(body) -> str:
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict):
            return str(err.get("message") or err.get("code") or err)
        if err:
            return str(err)
        if body.get("message"):
            return str(body["message"])
    return str(body)[:300]


async def _request(method: str, path: str, version: str, **kwargs):
    if not settings.CAL_API_KEY:
        raise CalError("CAL_API_KEY is not set in .env")
    try:
        async with httpx.AsyncClient(base_url=settings.CAL_API_BASE, timeout=20) as client:
            resp = await client.request(method, path, headers=_headers(version), **kwargs)
    except httpx.HTTPError as exc:
        raise CalError(f"Network error talking to Cal.com: {exc}") from exc
    try:
        body = resp.json()
    except ValueError:
        body = {"raw": resp.text}
    if resp.status_code >= 400 or (isinstance(body, dict) and body.get("status") == "error"):
        msg = _error_message(body)
        log.warning("Cal.com %s %s -> %s: %s", method, path, resp.status_code, msg)
        raise CalError(msg, resp.status_code, body)
    return body.get("data") if isinstance(body, dict) else body


def _to_utc_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


async def get_slots(event_type_id: int, start: date, end: date, tz: str) -> dict:
    """Returns {"2026-10-26": ["2026-10-26T09:00:00.000+05:30", ...], ...}"""
    data = await _request(
        "GET",
        "/slots",
        settings.CAL_VERSION_SLOTS,
        params={
            "eventTypeId": int(event_type_id),
            "start": start.isoformat(),
            "end": end.isoformat(),
            "timeZone": tz,
        },
    )
    result = {}
    for day, items in (data or {}).items():
        starts = []
        for item in items or []:
            value = item if isinstance(item, str) else (item or {}).get("start")
            if value:
                starts.append(value)
        if starts:
            result[day] = starts
    return result


def _first(data):
    if isinstance(data, list):
        return data[0] if data else {}
    return data or {}


async def create_booking(event_type_id: int, start: datetime, name: str, email: str, tz: str,
                         metadata: dict | None = None, phone: str | None = None, notes: str | None = None) -> dict:
    """notes = booking details shown to the clinic in Cal.com and in the emails."""
    attendee = {"name": name, "email": email, "timeZone": tz, "language": "en"}
    if phone:
        attendee["phoneNumber"] = phone
    body = {
        "start": _to_utc_z(start),
        "eventTypeId": int(event_type_id),
        "attendee": attendee,
    }
    if notes:
        body["bookingFieldsResponses"] = {"notes": notes[:1000]}
    if metadata:
        body["metadata"] = {str(k)[:40]: str(v)[:500] for k, v in metadata.items() if v is not None}
    data = await _request("POST", "/bookings", settings.CAL_VERSION_BOOKINGS, json=body)
    return _first(data)


async def cancel_booking(uid: str, reason: str = "") -> dict:
    body = {"cancellationReason": reason} if reason else {}
    data = await _request("POST", f"/bookings/{uid}/cancel", settings.CAL_VERSION_BOOKINGS, json=body)
    return _first(data)


async def reschedule_booking(uid: str, new_start: datetime, reason: str = "") -> dict:
    body = {"start": _to_utc_z(new_start)}
    if reason:
        body["reschedulingReason"] = reason
    data = await _request("POST", f"/bookings/{uid}/reschedule", settings.CAL_VERSION_BOOKINGS, json=body)
    return _first(data)


async def get_booking(uid: str) -> dict:
    data = await _request("GET", f"/bookings/{uid}", settings.CAL_VERSION_BOOKINGS)
    return _first(data)


async def list_event_types() -> list:
    data = await _request("GET", "/event-types", settings.CAL_VERSION_EVENT_TYPES)
    if isinstance(data, list):
        return data
    # older response shape: {"eventTypeGroups": [{"eventTypes": [...]}]}
    out = []
    if isinstance(data, dict):
        for group in data.get("eventTypeGroups", []):
            out.extend(group.get("eventTypes", []))
    return out
