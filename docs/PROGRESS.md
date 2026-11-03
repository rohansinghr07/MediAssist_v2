# MediAssist – progress log

_Last updated: Mon 26 Oct 2026_

## Where we are (about 80% done)

| Part | Status |
|---|---|
| Telegram bot (English + Hindi, buttons, new vs returning patient) | ✅ Done, tested live |
| Booking: symptoms → AI department → doctor → date → time → confirm | ✅ Done, tested live |
| My Appointments: reschedule / cancel | ✅ Done |
| Issues + complaints with ticket numbers (ISS-/CMP-) | ✅ Done |
| Track Status by number (APT-/ISS-/CMP-) | ✅ Done |
| Emergency detection (108 message + dashboard alert) | ✅ Done |
| Reminders 24 h + 2 h | ✅ Done, tested live |
| Cal.com: 10 doctors with exact weekly timings, booking details in notes, organizer "City Clinic, Kota" | ✅ Done |
| Cal.com auto-sync every 5 min (changes made via email links / Cal.com app) | ✅ Done, tested live |
| Staff dashboard (React + Bootstrap) at http://127.0.0.1:8000 | ✅ Done |
| AI: symptoms→department, intent, voice notes (confirm "Did I hear right?"), FAQ from clinic_info.md, smart tickets, auto-translate | ✅ Done, tested live |
| Reply language follows how the patient writes or speaks | ✅ Done |
| Project documents (PPT, speaker script, final doc) | ❌ Next |
| Deployment (Render or Railway) + real Cal.com webhook | ❌ Later, after completion |

## Pending from Rohan
- Clinic phone number → `CLINIC_PHONE` in `.env`
- Consultation fees (optional, for FAQ answers) → add to `backend/data/clinic_info.md`
- Run the 6-step test (doctors page, voice "mere bacche ko bukhar hai", book Dr. Arjun, check Cal.com, dashboard, FAQ) and send the flaws list

## Next steps
1. Fix flaws from the test
2. Update the project documents to the new system (Telegram, Python FastAPI, React, Cal.com, MongoDB, Groq AI)
3. Final testing + demo preparation
4. Deploy, then replace the API keys that were shared in chat

## How to start each day
```bat
conda activate mediassist
cd /d "D:\Ascentium\Automation Project\mediassist\backend"
python main.py
```
Bot: @MediAssist_Rohan_Singh_bot · Website: http://127.0.0.1:8000 · Dashboard: http://127.0.0.1:8000/staff/ (admin / password from .env)

## Key decisions so far
- Python (FastAPI) instead of n8n; Telegram instead of WhatsApp; Cal.com instead of Google Calendar
- Code makes every decision; AI only understands and writes text
- Cal.com is the master for slots and bookings; MongoDB holds patients, sessions, tickets and a copy of bookings
- Bot re-checks a slot with Cal.com right before booking (Cal.com accepts any time otherwise)
- When the patient skips email, the booking uses cityclinic.kota+tg<id>@gmail.com
- Departments: General Medicine, Pediatrics, Orthopedics, Dermatology (8 doctors: DR001–DR004, DR007–DR010; Cardiology + DR005/DR006 removed)

## Version 2 (saved 27 Oct 2026, tag v2.0)
- Dashboard redesigned (Doclinic-style theme, charts, activity feed, top search, collapsible sidebar, no emojis)
- Walk-in / reception booking from the dashboard; phone lookup; email only when typed at the desk
- "Share my number" button in the bot links reception bookings to Telegram (confirmation + reminders)
- New Cal.com account (cityclinic.kota@gmail.com); old test records cleared (backup in backups/, not in Git)
- Public clinic website at / (departments, doctors + timings, Telegram booking deep links, tracking by ID or mobile)
- Dashboard moved to /staff/
- Cardiology and its 2 doctors removed; 8 doctors in 4 departments
- New Indian-OPD style timings (morning + evening every department, Mon–Sat); 10-minute appointments
- Bot asks Morning / Afternoon / Evening before showing 10-minute times
- Reminders 24 h ("today"/"tomorrow" fixed) and 2 h before, Telegram only
- 20 offline tests pass (python tests/simulate_chat.py)

## Future scope
- Phone-call reminder 2 h before the visit (Exotel). Built and tested, then parked: code and steps in
  `future_scope/exotel-call-reminder/` (not active in the app).
