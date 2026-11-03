"""Website chat ("Chat with Bot") - the same chat engine as Telegram, over simple HTTP calls.

The browser keeps a random secret token (localStorage). The patient's chat id is "web:" + a hash of that
token, so the token itself is never stored. Bot replies are saved in `web_messages` and returned to the
browser; later messages (reminders, replies from the clinic) are picked up with /poll while the chat is open.
"""
import hashlib
import re
import secrets
import time
from collections import defaultdict, deque

from bson import ObjectId
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

import db
from api import client_ip

router = APIRouter(prefix="/api/chat")
TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{40,64}$")
MAX_TEXT = 1000
MAX_VOICE_BYTES = 3 * 1024 * 1024           # about 3 minutes of compressed audio
_hits: dict[str, deque] = defaultdict(deque)
LIMITS = {"start": (10, 600), "msg": (40, 60), "voice": (8, 60), "poll": (40, 60)}  # (count, seconds) per visitor


def _limit(request: Request, kind: str):
    count, window = LIMITS[kind]
    key, now = f"{kind}:{client_ip(request)}", time.time()
    q = _hits[key]
    while q and q[0] < now - window:
        q.popleft()
    if len(q) >= count:
        raise HTTPException(429, "Too many messages. Please wait a minute.")
    q.append(now)
    if len(_hits) > 5000:
        for k in [k for k, v in _hits.items() if not v or v[-1] < now - 600]:
            _hits.pop(k, None)


def _chat_id(token: str) -> str:
    if not token or not TOKEN_RE.match(token):
        raise HTTPException(400, "Invalid chat session. Please reload the page.")
    return "web:" + hashlib.sha256(token.encode()).hexdigest()[:32]


def _engine(request: Request):
    engine = request.app.state.engines.get("engine")
    if engine is None:
        raise HTTPException(503, "The assistant is starting. Please try again in a minute.")
    return engine


def _out(doc):
    return {"id": str(doc["_id"]), "from": doc.get("from", "bot"), "text": doc.get("text", ""),
            "buttons": doc.get("buttons") or [], "at": db.aware(doc["created_at"]).isoformat()}


async def _messages_after(chat_id, after=None, limit=60):
    query = {"chat_id": chat_id}
    if after:
        try:
            query["_id"] = {"$gt": ObjectId(after)}
        except Exception:  # noqa: BLE001 - a bad id just means "from the start"
            pass
    docs = await db.web_messages.find(query).sort("_id", -1).limit(limit).to_list(None)
    return [_out(d) for d in reversed(docs)]


async def _save_user(chat_id, text):
    res = await db.web_messages.insert_one({"chat_id": chat_id, "from": "user", "text": text, "buttons": [],
                                            "created_at": db.utcnow()})
    return res.inserted_id


class StartIn(BaseModel):
    token: str | None = None


@router.post("/start")
async def start(body: StartIn, request: Request):
    """Open the chat: continue an existing conversation, or start a new one with the welcome message."""
    engine = _engine(request)
    if body.token and TOKEN_RE.match(body.token):
        chat_id = _chat_id(body.token)
        if await db.patients.find_one({"_id": chat_id}, {"_id": 1}):
            return {"token": body.token, "messages": await _messages_after(chat_id)}
    _limit(request, "start")
    token = secrets.token_urlsafe(32)
    chat_id = _chat_id(token)
    await engine.handle_text(chat_id, "/start")
    return {"token": token, "messages": await _messages_after(chat_id)}


class MessageIn(BaseModel):
    token: str
    text: str | None = None      # typed message
    button: str | None = None    # data of a tapped button, e.g. "doc:DR002"
    label: str | None = None     # the button's text, shown in the chat


@router.post("/message")
async def message(body: MessageIn, request: Request):
    _limit(request, "msg")
    chat_id = _chat_id(body.token)
    engine = _engine(request)
    if body.button:
        if len(body.button) > 64:
            raise HTTPException(400, "Invalid button")
        last = await _save_user(chat_id, (body.label or "✓")[:120])
        await engine.handle_button(chat_id, body.button)
    else:
        text = (body.text or "").strip()
        if not text:
            raise HTTPException(400, "Type a message")
        last = await _save_user(chat_id, text[:MAX_TEXT])
        await engine.handle_text(chat_id, text[:MAX_TEXT])
    return {"messages": await _messages_after(chat_id, str(last))}


@router.post("/voice")
async def voice(request: Request, duration: int = 0):
    """Body = the recorded audio (webm / ogg / mp4); the token comes in the X-Chat-Token header (never in the URL,
    so it doesn't end up in server logs). Same voice flow as Telegram: transcribe -> "Did I hear you?"."""
    _limit(request, "voice")
    chat_id = _chat_id(request.headers.get("x-chat-token", ""))
    engine = _engine(request)
    audio = await request.body()
    if not audio:
        raise HTTPException(400, "No audio received")
    if len(audio) > MAX_VOICE_BYTES:
        raise HTTPException(413, "Voice message is too long")
    ctype = (request.headers.get("content-type") or "").lower()
    name = "voice.ogg" if "ogg" in ctype else "voice.m4a" if ("mp4" in ctype or "aac" in ctype) else "voice.webm"
    last = await _save_user(chat_id, "🎤 Voice message")
    await engine.handle_voice(chat_id, audio, max(0, min(duration, 3600)), name)
    return {"messages": await _messages_after(chat_id, str(last))}


@router.post("/poll")
async def poll(body: StartIn, request: Request, after: str | None = None):
    """New messages since `after` - reminders, clinic replies, or answers that arrived later."""
    _limit(request, "poll")
    chat_id = _chat_id(body.token or "")
    return {"messages": await _messages_after(chat_id, after)}
