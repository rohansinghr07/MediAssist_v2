# Future scope: phone-call reminder (Exotel)

Not active in MediAssist. Kept here so it can be added later.

**What it does:** about 2 hours before each visit, the backend rings the patient's mobile through Exotel and plays a
short reminder. It reaches every patient with a mobile number, including walk-ins without Telegram.
- one call per booking (a reschedule allows a new one), only 8 am - 9 pm, daily limit (CALL_DAILY_LIMIT)
- dashboard shows "Call reminder <time>" / "Call reminder failed"
- after deployment the call can say the patient's name, doctor, time and booking ID
  (Exotel Greeting -> text from URL `/api/public/exotel/greeting`)

**Files**
- `exotel.py` - goes to `backend/exotel.py`
- `changes.patch` - all other code changes (config, engine, public API, setup check, tests, dashboard, README, .env.example)

**To add it later** (from the `mediassist` folder, on a new branch):
```
git switch -c feature/call-reminder
copy future_scope\exotel-call-reminder\exotel.py backend\exotel.py
git apply future_scope\exotel-call-reminder\changes.patch
```
Then rebuild the dashboard (`npm run build` in `dashboard`), fill the `EXOTEL_*` values in `.env`
and run `python check_setup.py`.

**Exotel trial limits:** calls only to verified numbers (max 10), about 7 days, limited credits, one ExoPhone.
