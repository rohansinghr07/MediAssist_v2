"""Input checks done in code (never by the AI)."""
import re

_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
_BAD_NAME_CHARS = re.compile(r"[\d@#$%^&*()_+=<>/\\|{}\[\]~`!?;:\"]")


def clean_phone(text: str):
    """Accepts 9876543210 / +91 98765 43210 / 09876543210. Returns +919876543210 or None."""
    # works with Hindi digits too (voice notes may give ९१४०...)
    digits = "".join(str(int(ch)) for ch in (text or "") if ch.isdecimal())
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    if len(digits) == 10 and digits[0] in "6789":
        return "+91" + digits
    return None


def clean_email(text: str):
    value = (text or "").strip()
    return value.lower() if _EMAIL_RE.match(value) else None


def clean_name(text: str):
    value = " ".join((text or "").split())
    if not 2 <= len(value) <= 60:
        return None
    if _BAD_NAME_CHARS.search(value):
        return None
    if not any(ch.isalpha() for ch in value):
        return None
    return value.title() if value.isascii() else value
