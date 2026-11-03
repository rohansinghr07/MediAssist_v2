"""All settings come from the .env file in the project root (mediassist/.env)."""
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# Windows terminals default to cp1252 and crash on emojis / Hindi - force UTF-8 output
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

ROOT = Path(__file__).resolve().parent.parent
if not (ROOT / ".env").exists():
    print(f"WARNING: no .env file found at {ROOT / '.env'}")
load_dotenv(ROOT / ".env")


def _get(name, default=None):
    value = os.getenv(name, default)
    return value.strip() if isinstance(value, str) else value


class Settings:
    # Clinic
    CLINIC_NAME = _get("CLINIC_NAME", "City Clinic, Kota")
    CLINIC_PHONE = _get("CLINIC_PHONE", "+91-0000000000")
    TELEGRAM_BOT_USERNAME = _get("TELEGRAM_BOT_USERNAME", "")  # optional: filled automatically when the bot starts
    CLINIC_TZ = _get("CLINIC_TZ", "Asia/Kolkata")

    # Telegram
    TELEGRAM_BOT_TOKEN = _get("TELEGRAM_BOT_TOKEN", "")
    STAFF_CHAT_ID = _get("STAFF_CHAT_ID", "")  # optional: Telegram chat/group that gets emergency alerts

    # MongoDB
    MONGODB_URI = _get("MONGODB_URI", "mongodb://localhost:27017")
    MONGODB_DB = _get("MONGODB_DB", "mediassist")

    # Cal.com
    CAL_API_KEY = _get("CAL_API_KEY", "")
    CAL_API_BASE = _get("CAL_API_BASE", "https://api.cal.com/v2")
    CAL_VERSION_SLOTS = _get("CAL_VERSION_SLOTS", "2024-09-04")
    CAL_VERSION_BOOKINGS = _get("CAL_VERSION_BOOKINGS", "2026-02-25")
    CAL_VERSION_EVENT_TYPES = _get("CAL_VERSION_EVENT_TYPES", "2024-06-14")
    CAL_WEBHOOK_SECRET = _get("CAL_WEBHOOK_SECRET", "")
    # Cal.com requires a real attendee email. When a patient skips email, the booking uses
    # the clinic's email with a tag, e.g. clinic+tg12345@gmail.com (still lands in the clinic inbox).
    FALLBACK_EMAIL = _get("FALLBACK_EMAIL", "")

    # AI (OpenAI or Groq - both use the OpenAI-style API)
    LLM_API_KEY = _get("LLM_API_KEY", "")
    LLM_BASE_URL = _get("LLM_BASE_URL", "")  # blank = OpenAI. Groq: https://api.groq.com/openai/v1
    LLM_MODEL = _get("LLM_MODEL", "gpt-4o-mini")
    # Speech-to-text for voice messages. Groq: whisper-large-v3 | OpenAI: whisper-1
    STT_MODEL = _get("STT_MODEL", "whisper-large-v3")
    MAX_VOICE_SECONDS = int(_get("MAX_VOICE_SECONDS", "90"))

    # Booking rules
    BOOKING_DAYS_AHEAD = int(_get("BOOKING_DAYS_AHEAD", "7"))
    MIN_LEAD_MINUTES = int(_get("MIN_LEAD_MINUTES", "30"))  # no slot sooner than this
    SESSION_TIMEOUT_MINUTES = int(_get("SESSION_TIMEOUT_MINUTES", "30"))
    REMINDER_CHECK_SECONDS = int(_get("REMINDER_CHECK_SECONDS", "300"))
    # How often to check Cal.com for bookings changed outside our system (email links, Cal.com app)
    CAL_SYNC_SECONDS = int(_get("CAL_SYNC_SECONDS", "300"))

    # Dashboard login
    ADMIN_USERNAME = _get("ADMIN_USERNAME", "admin")
    ADMIN_PASSWORD = _get("ADMIN_PASSWORD", "change-me")
    JWT_SECRET = _get("JWT_SECRET", "please-change-this-secret")
    JWT_HOURS = int(_get("JWT_HOURS", "12"))
    CORS_ORIGINS = [o.strip() for o in _get("CORS_ORIGINS", "http://localhost:5173,http://localhost:3000").split(",") if o.strip()]

    # Server
    HOST = _get("HOST", "127.0.0.1")
    # on a hosting service (Render etc.) the visitor's IP arrives in X-Forwarded-For - trust it only there
    TRUST_PROXY = _get("TRUST_PROXY", "off").lower() in ("on", "1", "true", "yes")
    PORT = int(_get("PORT", "8000"))


settings = Settings()
