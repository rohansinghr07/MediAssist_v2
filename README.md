# MediAssist – City Clinic, Kota

An AI clinic assistant. Patients book, reschedule and cancel appointments, raise issues or complaints and track
them – on Telegram (English or Hindi, text or voice) or on the clinic website. Reception staff manage everything
from a web dashboard, including walk-in bookings.

| Part | Address (local) | Built with |
|---|---|---|
| Clinic website | http://127.0.0.1:8000/ | HTML, CSS, JavaScript |
| Staff dashboard | http://127.0.0.1:8000/staff/ | React + Bootstrap |
| Telegram bot | @MediAssist_Rohan_Singh_bot | python-telegram-bot |
| API | http://127.0.0.1:8000/docs | Python, FastAPI |
| Bookings and doctor calendars | Cal.com | Cal.com API v2 |
| Database | MongoDB Atlas | pymongo |
| AI | Groq (gpt-oss-120b, Whisper) | OpenAI-compatible API |

One process (`backend/main.py`) runs the website, dashboard, API, Telegram bot, reminders and the Cal.com sync.

**Rule:** Python code makes every decision. The AI only understands text (symptoms, voice notes, questions).
Doctors, slots and bookings always come from Cal.com and the database, never from the AI.

---

## 1. Folder structure

```
mediassist/
├── backend/                  Python server
│   ├── main.py               starts everything
│   ├── engine.py             all chat logic (booking, reschedule, cancel, tickets, emergency, reminders)
│   ├── telegram_bot.py       Telegram <-> engine
│   ├── api.py                staff dashboard API (login required) + Cal.com webhook
│   ├── public_api.py         website API (clinic info, doctors, tracking)
│   ├── web_chat.py           website "Chat with Bot" API (same engine as Telegram)
│   ├── calcom.py             Cal.com client
│   ├── ai.py                 AI calls + emergency keywords
│   ├── db.py                 MongoDB connection
│   ├── texts.py              every bot message in English and Hindi
│   ├── validators.py         name / phone / email checks
│   ├── config.py             settings from .env
│   ├── data/
│   │   ├── seed_data.json    clinic, departments, doctors and weekly timings
│   │   └── clinic_info.md    what the bot's FAQ knows (edit any time)
│   ├── scripts/
│   │   ├── setup_calcom_doctors.py   creates/updates doctors' calendars in Cal.com
│   │   ├── seed.py                   loads departments + doctors into MongoDB
│   │   └── check_setup.py            tests every key and connection
│   └── tests/
│       ├── simulate_chat.py  offline test of every flow (no keys needed)
│       └── demo_server.py    dashboard + website with sample data (port 8010)
├── dashboard/                staff dashboard (React)
│   ├── src/                  source code
│   └── dist/                 built version served at /staff/ (rebuild after changes)
├── website/                  public clinic website (index.html, styles.css, app.js, chat.js)
├── docs/                     PROGRESS.md (project log), BRANCHING.md (Git guide)
├── requirements.txt          Python packages for the server
├── requirements-dev.txt      + test packages
├── render.yaml, Procfile, .python-version   deployment settings
├── .env.example              list of settings (copy to .env)
└── .env                      your keys – never in Git
```

## 2. Setup on a new PC (Windows, Anaconda Prompt)

```bat
conda create -n mediassist python=3.11 -y
conda activate mediassist
cd /d "D:\Ascentium\Automation Project\mediassist"
pip install -r requirements-dev.txt
copy .env.example .env
```
Fill in `.env` (section 3), then:
```bat
cd backend
python tests\simulate_chat.py        :: offline test - must end with ALL 22 TESTS PASSED
python scripts\check_setup.py        :: checks MongoDB, Telegram, Cal.com and AI
python main.py                       :: starts everything
```

## 3. Settings (`.env`)

| Setting | What it is |
|---|---|
| `TELEGRAM_BOT_TOKEN` | from @BotFather |
| `MONGODB_URI`, `MONGODB_DB` | MongoDB Atlas connection (Atlas → Connect → Drivers) |
| `CAL_API_KEY` | Cal.com → Settings → Developer → API Keys |
| `FALLBACK_EMAIL` | clinic Gmail; used when a patient gives no email (Cal.com needs one) |
| `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL` | Groq key, `https://api.groq.com/openai/v1`, `openai/gpt-oss-120b` |
| `ADMIN_USERNAME`, `ADMIN_PASSWORD` | dashboard login (password: 10+ characters on a server) |
| `JWT_SECRET` | 32+ random characters |
| `CLINIC_NAME`, `CLINIC_PHONE`, `CLINIC_TZ` | shown to patients |
| `STAFF_CHAT_ID` | optional – Telegram chat that also receives emergency alerts |
| `CAL_WEBHOOK_SECRET` | optional – enables the Cal.com webhook (the 5-minute sync works without it) |
| `HOST`, `PORT`, `TRUST_PROXY` | server only: `0.0.0.0`, set by the host, `on` |

## 4. Doctors, timings and Cal.com

Doctors and weekly timings live in `backend/data/seed_data.json` (8 doctors, 4 departments, Mon–Sat,
10-minute appointments). After editing it, run from the `backend` folder:
```bat
python scripts\setup_calcom_doctors.py   :: updates each doctor's timings + booking type in Cal.com
python scripts\seed.py                   :: updates the database (doctors removed from the file are removed)
python scripts\check_setup.py            :: shows free slots for every doctor
```
The website, dashboard and bot pick up the change automatically.

## 5. Features

**Patients (Telegram):** book (pick a department or describe symptoms – AI suggests the department), voice notes
with "Did I hear you right?", Morning/Afternoon/Evening then 10-minute times, my appointments, reschedule, cancel,
issues and complaints with ticket numbers (APT-/ISS-/CMP-), tracking, FAQ answered only from `clinic_info.md`,
emergency words → 108 message + dashboard alert, reminders 24 h and 2 h before, replies in the patient's language. Every booking confirmation says the
₹500 consultation fee is paid at the reception at the time of the visit.
**Share my number** links bookings made at reception (only a number verified by Telegram is linked).

**Website:** "Chat with Bot" – the same assistant inside the website (book, reschedule, cancel, issues,
complaints, tracking, FAQ, voice; no Telegram needed), clinic details, departments, doctors with live timings, Book buttons that open the bot (also straight
to a doctor), tracking by booking ID or mobile number (names masked, rate-limited), FAQ, map.

**Staff dashboard:** overview with charts and activity, appointments (filters, search, reschedule, cancel,
completed / no-show), walk-in booking with phone lookup, doctors and free slots, issues and complaints with AI
summary and priority (notes auto-translated to Hindi for Hindi patients), emergency alerts, Cal.com sync.

**Safety:** one booking per doctor + time even when two people book at once, dashboard login lockout after
5 wrong passwords, signed Cal.com webhook only, the server refuses weak passwords when online.

## 6. Development

- Dashboard: `cd dashboard`, `npm install` once, `npm run dev` (live preview on :5173), `npm run build` before committing.
- Sample-data preview without keys: `python tests\demo_server.py` → http://127.0.0.1:8010
- Git: work on a branch, merge into `main` when tested – see `docs/BRANCHING.md`.

## 7. Deployment

`render.yaml` describes the server for Render (Procfile + `.python-version` for Railway). The start command is
`cd backend && python main.py` with `HOST=0.0.0.0` and `TRUST_PROXY=on`. Secrets are typed into the host's
dashboard, never committed. Run only **one** copy of the bot – stop `python main.py` on the PC once the server runs.

## 8. Common problems

| Problem | Fix |
|---|---|
| "Sorry, I couldn't check the slots" | Run `python scripts\check_setup.py` – Cal.com key or doctor IDs |
| Bot doesn't answer | Is `python main.py` running? Only one copy may run (PC **or** server) |
| Old page after an update | Ctrl+F5 |
| Dashboard login "Too many wrong attempts" | Wait 15 minutes |
| Emoji/Hindi errors in the Windows terminal | Already handled in `config.py`; use a UTF-8 terminal |
