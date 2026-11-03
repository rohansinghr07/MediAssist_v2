"""AI helpers. The AI ONLY understands text - it never books, cancels or changes data.

Jobs:
  1. suggest_department() - symptoms -> department key (+ emergency flag)
  2. detect_intent()      - free text -> what the user wants
Emergency keywords and simple intents are checked in code first (fast, no AI needed).
If no LLM_API_KEY is set, the bot still works using keywords only.
"""
import json
import logging
import re

from config import settings

log = logging.getLogger("ai")

_client = None


def _get_client():
    global _client
    if _client is None and settings.LLM_API_KEY:
        from openai import AsyncOpenAI
        _client = AsyncOpenAI(api_key=settings.LLM_API_KEY, base_url=settings.LLM_BASE_URL or None)
    return _client


async def _ask_json(system: str, user: str):
    client = _get_client()
    if client is None:
        return None
    try:
        resp = await client.chat.completions.create(
            model=settings.LLM_MODEL,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            timeout=20,
        )
        return json.loads(resp.choices[0].message.content or "{}")
    except Exception as exc:  # AI failure must never break the chat
        log.warning("LLM call failed: %s", exc)
        return None


# ---------------------------------------------------------------- emergency (code, not AI)
_EMERGENCY_PATTERNS = [
    r"chest pain", r"heart attack", r"cardiac arrest", r"stroke", r"paraly",
    r"can'?t breathe", r"cannot breathe", r"not able to breathe", r"difficulty (in )?breathing",
    r"breathing (problem|difficulty|trouble)", r"short(ness)? of breath",
    r"unconscious", r"fainted", r"not responding", r"seizure", r"fits?\b.*(aa|aya|came)",
    r"heavy bleeding", r"bleeding (a lot|heavily|badly|too much)", r"severe bleeding",
    r"poison", r"overdose", r"suicid", r"kill myself", r"end my life",
    r"accident", r"severe burn",
    # Hinglish
    r"seene? (me|mein|mai) dard", r"chhati (me|mein) dard", r"dil ka daura",
    r"saa?ns (nahi|nhi|lene me(in)? (dikkat|taklif|problem))", r"behosh",
    r"khoo?n (bahut|zyada|jyada) (beh|nikal)", r"zeher",
    # Hindi
    r"सीने में दर्द", r"छाती में दर्द", r"दिल का दौरा", r"सांस (नहीं|लेने में)", r"साँस (नहीं|लेने में)",
    r"बेहोश", r"बहुत खून", r"ज़हर", r"जहर",
]
_EMERGENCY_RE = re.compile("|".join(_EMERGENCY_PATTERNS), re.IGNORECASE)


def is_emergency(text: str) -> bool:
    return bool(_EMERGENCY_RE.search(text or ""))


# ---------------------------------------------------------------- intents
INTENTS = ("book", "appointments", "issue", "complaint", "symptoms", "faq")

_KEYWORDS = [
    ("complaint", r"complain|complaint|shikayat|shikaayat|शिकायत"),
    ("appointments", r"cancel|reschedul|postpone|change (my )?(time|date|slot)|my (appointment|booking)s?|"
                     r"radd|time badal|date badal|रद्द|बदल"),
    ("book", r"\bbook|appointment|appoint|booking|consult|doctor se milna|dikhana|बुक|अपॉइंटमेंट|अपोइंटमेंट"),
    ("issue", r"\bissue|samasya|समस्या|report nahi|bill|refund|prescription|parchi|पर्चा"),
    ("faq", r"\btimings?\b|\bopen(ing)?\b|\bclos(e|ing)\b|\bfees?\b|\bcharges?\b|\baddress\b|\blocation\b|\bparking\b|"
            r"kab khul|kab band|kitne baje|kaha(n)? hai|\bfees? kitni|कब खुल|कितने बजे|कहाँ है|फीस"),
]
_GREETING_RE = re.compile(r"^(hi+|hello+|hey+|hii+|namaste|namaskar|नमस्ते|start|/start|good (morning|evening|afternoon))[\s!.]*$",
                          re.IGNORECASE)


def is_greeting(text: str) -> bool:
    return bool(_GREETING_RE.match((text or "").strip()))


def keyword_intent(text: str):
    low = (text or "").lower()
    for intent, pattern in _KEYWORDS:
        if re.search(pattern, low, re.IGNORECASE):
            return intent
    return None


async def detect_intent(text: str):
    """Keyword match first, AI second. Returns one of INTENTS or None."""
    found = keyword_intent(text)
    if found or is_greeting(text):
        return found
    result = await _ask_json(
        "You classify messages sent to a clinic's chat assistant. Messages may be English, Hindi or Hinglish. "
        'Reply ONLY with JSON: {"intent": "<value>"} where value is one of: '
        '"book" (wants an appointment), "appointments" (see/cancel/reschedule existing booking), '
        '"issue" (problem with medicine, report, bill, service), "complaint" (complaint about staff/clinic), '
        '"symptoms" (describes a health problem), "faq" (general question about the clinic: timings, fees, '
        'address, services, facilities, payment, reports), "other".',
        text,
    )
    intent = (result or {}).get("intent")
    return intent if intent in INTENTS else None


# Words a clinic patient is likely to say - helps speech-to-text spell them correctly
STT_HINT = ("Patient talking to a clinic in Hindi, Hinglish or English. मुझे सर में दर्द है। पेट में दर्द, बुखार, खांसी, "
            "जुकाम, दांत में दर्द, कमर दर्द, उल्टी, चक्कर। अपॉइंटमेंट बुक करना है। Doctor, appointment, headache, fever.")

_DEVANAGARI = re.compile(r"[ऀ-ॿ]")
_HINGLISH_WORDS = {"mujhe", "mujhko", "mera", "meri", "mere", "hai", "hain", "kya", "nahi", "nhi", "nahin", "karna",
                   "karni", "karna", "chahiye", "dard", "kal", "aaj", "kab", "kitni", "kitna", "kaise", "raha", "rahi",
                   "rahe", "aur", "bhi", "dikhana", "bukhar", "sar", "pet", "daant", "haan", "tha", "thi", "kar", "ke",
                   "liye", "wala", "wali", "hoga", "hogi", "milega", "milegi", "khulta", "batao", "bataiye", "doctor ko"}


def guess_language(text: str):
    """'hi' for Hindi/Hinglish, 'en' for English, None if too short to tell. No AI needed."""
    text = text or ""
    if _DEVANAGARI.search(text):
        return "hi"
    words = re.findall(r"[a-zA-Z]+", text.lower())
    if sum(w in _HINGLISH_WORDS for w in words) >= 2:
        return "hi"
    if len(words) >= 3:
        return "en"
    return None


async def clean_transcript(raw: str):
    """Fix obvious speech-to-text mistakes using clinic context. Returns (text, language)."""
    result = await _ask_json(
        "This is a speech-to-text transcript of a patient speaking to a clinic's assistant in Hindi, Hinglish or "
        "English. Speech recognition often mishears short phrases. If some words make no sense, replace them with the "
        "most likely words a patient would say to a clinic (symptoms, body parts, appointment, complaint words) that "
        "SOUND SIMILAR. If the transcript already makes sense, return it unchanged. Do not add new information, "
        "do not translate, keep the same script. "
        'Reply ONLY with JSON: {"text": "<corrected transcript>", "language": "hi" or "en"} '
        '(language "hi" for Hindi or Hinglish, "en" for English).',
        raw,
    )
    text = ((result or {}).get("text") or "").strip() or raw
    lang = (result or {}).get("language")
    return text, (lang if lang in ("hi", "en") else guess_language(text))


async def transcribe(audio: bytes, filename: str = "voice.ogg"):
    """Voice note -> text (Groq Whisper / OpenAI Whisper). Returns None if it fails."""
    client = _get_client()
    if client is None:
        return None
    try:
        resp = await client.audio.transcriptions.create(
            model=settings.STT_MODEL, file=(filename, audio), prompt=STT_HINT, timeout=30)
        text = (resp.text or "").strip()
        return text or None
    except Exception as exc:
        log.warning("transcription failed: %s", exc)
        return None


async def answer_faq(question: str, clinic_info: str, lang: str):
    """Answer a general question ONLY from the clinic info sheet. Returns (found, answer)."""
    language = "Hindi (Devanagari script, simple words)" if lang == "hi" else "simple English"
    result = await _ask_json(
        "You are the front-desk assistant of a clinic. Answer the patient's question using ONLY the clinic "
        "information below. Do not guess or add anything that is not written there. Never give medical advice, "
        "diagnosis or medicine names - for health questions, suggest booking an appointment. "
        f"Write the answer in {language}, at most 3 short sentences. "
        'Reply ONLY with JSON: {"found": true|false, "answer": "<answer or empty>"}. '
        "Set found=false if the information is not in the clinic information.\n\n"
        "=== CLINIC INFORMATION ===\n" + clinic_info,
        question,
    )
    if not result:
        return False, None
    answer = (result.get("answer") or "").strip()
    return bool(result.get("found")) and bool(answer), answer


async def analyze_ticket(ticket_type: str, category: str, description: str):
    """For staff: short English summary + priority + mood of an issue/complaint."""
    result = await _ask_json(
        "You help clinic staff sort patient issues and complaints. The text may be English, Hindi or Hinglish. "
        'Reply ONLY with JSON: {"summary": "<one short English sentence, max 15 words>", '
        '"priority": "high"|"medium"|"low", "sentiment": "angry"|"upset"|"neutral"|"positive"}. '
        "high = health/safety risk, medicine unavailable, very angry patient or repeated problem; "
        "medium = service problem that needs action soon; low = minor or general feedback.",
        f"Type: {ticket_type}\nCategory: {category}\nPatient wrote: {description}",
    )
    if not result:
        return None
    priority = result.get("priority") if result.get("priority") in ("high", "medium", "low") else "medium"
    sentiment = result.get("sentiment") if result.get("sentiment") in ("angry", "upset", "neutral", "positive") else "neutral"
    return {"summary": (result.get("summary") or "")[:200], "priority": priority, "sentiment": sentiment}


async def translate(text: str, target_lang: str):
    """Translate a staff note into the patient's language ('hi' or 'en'). Returns None on failure."""
    language = "Hindi (Devanagari script, simple everyday words)" if target_lang == "hi" else "simple English"
    result = await _ask_json(
        f"Translate the clinic staff's message into {language}. Keep names, numbers, dates and IDs unchanged. "
        'Reply ONLY with JSON: {"translation": "<text>"}',
        text,
    )
    value = ((result or {}).get("translation") or "").strip()
    return value or None


def looks_english(text: str) -> bool:
    letters = [ch for ch in text or "" if ch.isalpha()]
    return bool(letters) and sum(ch.isascii() for ch in letters) / len(letters) > 0.8


async def suggest_department(symptoms: str, departments: list[dict]):
    """departments: [{"_id": key, "name_en": ...}]. Returns (key or None, emergency: bool)."""
    if is_emergency(symptoms):
        return None, True
    options = "\n".join(f'- "{d["_id"]}": {d["name_en"]}' for d in departments)
    result = await _ask_json(
        "You help a small clinic route patients. Read the patient's symptoms (English, Hindi or Hinglish) and pick "
        "the single best department from this list ONLY:\n" + options + "\n"
        "If nothing fits well, choose the general physician department. "
        "Set emergency=true only for possible emergencies (chest pain, breathing difficulty, unconsciousness, "
        "heavy bleeding, stroke signs, poisoning, suicidal thoughts). "
        'Reply ONLY with JSON: {"department": "<key>", "emergency": true|false}',
        symptoms,
    )
    if not result:
        return None, False
    key = result.get("department")
    valid = {d["_id"] for d in departments}
    return (key if key in valid else None), bool(result.get("emergency"))
