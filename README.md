# Garmin training overview (private)

A personal, local-only training dashboard for orienteering, built on my Garmin data.
It's a free replacement for Shape. Everything runs on this laptop; nothing is hosted anywhere.

- **Sync**: `garmin_sync/` fetches activities and daily metrics from Garmin Connect into `data/garmin.db` (SQLite).
- **Dashboard**: `app/` is a Streamlit app at http://localhost:8501 *(Phase 3)*.
- **Data reference**: `DATA.md` describes the tables *(Phase 2)*.

> **Privacy**: `.env` (credentials), `data/` (database, raw data, exports) and FIT/zip files are git-ignored.
> Login tokens are stored in `~/.garminconnect` in your home folder, outside this repo.

---

## One-time setup

All commands are for **PowerShell**, run from the project folder (`C:\Users\jornk\dev\persoonlijk\garmin_overview`).

1. **Create and activate the virtual environment, then install dependencies** (needs Python 3.12+):
   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```
   If PowerShell refuses to run `Activate.ps1`, run this once:
   `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.
   When the venv is active, your prompt starts with `(.venv)`.

2. **Add your Garmin credentials**:
   ```powershell
   Copy-Item .env.example .env
   notepad .env
   ```
   Fill in `GARMIN_EMAIL` and `GARMIN_PASSWORD` and save. Only this laptop ever sees them.

3. **Test the login**:
   ```powershell
   python -m garmin_sync.auth
   ```
   If your account has two-step verification (MFA), Garmin emails or texts you a code; type it in when asked.
   Login tokens are then cached in `~/.garminconnect`. Later runs reuse them and refresh them automatically, so you won't have to log in again until they expire (typically months).

4. **First sync**. Try a small window first:
   ```powershell
   python -m garmin_sync.sync --since 2026-09-01
   ```
   Then fetch your full history (this can take an hour or more because of Garmin's rate limits):
   ```powershell
   python -m garmin_sync.sync
   ```
   You can stop it at any time with **Ctrl+C**. Everything fetched so far is kept, and the next run continues where it left off.

5. **Put the code in a private GitHub repo** (optional):
   ```powershell
   git status                                   # .env and data/ must NOT be listed
   git check-ignore -v .env data/garmin.db      # both should print a .gitignore rule
   git add .
   git commit -m "Initial commit"
   gh repo create garmin-overview --private --source . --push
   ```
   No `gh` CLI? Create an empty **private** repo on github.com instead, then run
   `git remote add origin <url>` and `git push -u origin main`.

---

## Daily use

```powershell
.\.venv\Scripts\Activate.ps1
python -m garmin_sync.sync
```

Sync options:

| Option | What it does |
|---|---|
| `--since YYYY-MM-DD` | Only fetch data on or after this date |
| `--no-details` | Skip the per-activity HR zones and HR/pace stream (much faster) |
| `--activities-only` / `--daily-only` | Sync only one part |

### What gets synced

- **Activities**: type, date, duration, distance, elevation, average/max HR, training effect and Garmin training load. Per activity also time in HR zones and the HR/pace/elevation stream.
- **Daily metrics**: resting HR, HRV, sleep (duration, stages, score), body battery, stress and steps.
- **Training status**: status, acute/chronic load, VO2max and training readiness. Only for the last 365 days, because Garmin offers it per day only.

---

## Troubleshooting

- **"Garmin rejected the login"**: check your password in `.env`. If it's correct, Garmin may have changed its login system (this happens a few times a year). Try `pip install --upgrade garminconnect`. If that doesn't help, use the FIT importer *(Phase 2)*.
- **"rate-limiting" / HTTP 429**: Garmin is throttling you. Wait 15–60 minutes and run the sync again; it resumes.
- **Force a fresh login**: delete the folder `~/.garminconnect` and run `python -m garmin_sync.auth`.
- **A field is always empty**: not every watch provides every metric (e.g. HRV, training readiness). Each sync keeps the last raw response per endpoint in `data/raw/samples/` (git-ignored), which helps with debugging.
