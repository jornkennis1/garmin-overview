# Garmin training overview (private)

A personal, local-only training dashboard for orienteering, built on my Garmin data.
It's a free replacement for Shape. Everything runs on this laptop; nothing is hosted anywhere.

- **Sync**: `garmin_sync/` fetches activities, laps and daily metrics from Garmin Connect into `data/garmin.db` (SQLite).
- **Dashboard**: `app/` is a Streamlit app at http://localhost:8501 (only reachable from this laptop).
- **Data reference**: `DATA.md` describes the tables and views. Claude Code can use it to answer questions about my training.

> **Privacy**: `.env` (credentials), `data/` (database, raw data, exports, backups) and FIT/zip files are git-ignored.
> Login tokens are stored in `~/.garminconnect` in your home folder, outside this repo.
> The dashboard has no "Deploy" button and listens on 127.0.0.1 only.

---

## Daily use

The quickest way to sync and open the dashboard in one step:

```powershell
powershell -ExecutionPolicy Bypass -File .\sync_and_open.ps1          # sync, then open the dashboard
powershell -ExecutionPolicy Bypass -File .\sync_and_open.ps1 -NoSync  # only open the dashboard
```

Or step by step:

```powershell
.\.venv\Scripts\Activate.ps1
python -m garmin_sync.sync
streamlit run app/Dashboard.py
```

Your browser opens http://localhost:8501 on the **Today** page. Stop the dashboard with **Ctrl+C** in the terminal.
While the dashboard is open, the **Sync now** button in the sidebar fetches new data too.

**Dark mode**: by default the dashboard follows your Windows light/dark setting. To switch manually, use the **⋮ menu** at the top right: **System / Light / Dark**.

| Page | What it shows |
|---|---|
| **Today** | Training readiness, fitness/fatigue, last night's sleep, this week per day, sport split, and a health grid (resting HR, HRV, stress, body battery, steps, active calories, VO2 max, weight, respiration). **Click any box** for a one-sentence explanation and a 30-day chart. |
| **Overview** | This week vs the previous 4 weeks (hours, sessions, load, easy share), weekly hours by tag, weekly load, fitness/fatigue curves, recent sessions |
| **Calendar** | Month grid coloured by tag or by load, with weekly totals. Click an activity for details. |
| **Intensity** | Time in HR zones per week (3- or 5-zone), easy vs hard trend, zone split per tag |
| **Recovery** | Resting HR, HRV (with Garmin's balanced range), sleep, body battery and stress with 7-day averages, plus load for context |
| **Activity** | One session: time/HR/load first, HR with zone bands and lap lines, pace (speed for cycling), elevation, **laps** (chart + table), time in zones, tag editor, optional map |
| **Tags** | Filterable table to tag many activities at once, sortable by "orienteering-likeness" |
| **Settings** | How to switch light/dark, data status (what's synced, from when), where the other settings live |

The tag filter in the sidebar applies to every page.

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

4. **First sync**. Try a small window first, then fetch your full history:
   ```powershell
   python -m garmin_sync.sync --since 2026-09-01
   python -m garmin_sync.sync
   ```
   The full history can take a few hours because of Garmin's rate limits. You can stop it at any time with **Ctrl+C**. Everything fetched so far is kept, and the next run continues where it left off.

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

## Sync details

| Option | What it does |
|---|---|
| `--since YYYY-MM-DD` | Only fetch data on or after this date |
| `--no-details` | Skip per-activity HR zones, HR/pace stream and laps (much faster) |
| `--activities-only` / `--daily-only` | Sync only one part |

What gets synced:
- **Activities**: type, date, duration, distance, elevation, average/max HR, training effect and Garmin training load. Per activity also time in HR zones, the HR/pace/elevation stream (~2000 points) and **laps**. Laps aren't fetched for gym, mobility and similar sessions.
- **Daily metrics**: resting HR, HRV, sleep (duration, stages, score), body battery, stress, steps, active calories, respiration and weight (weigh-ins from a Garmin scale or entered in Garmin Connect).
- **Training status**: status, acute/chronic load, VO2max and training readiness. Only for the last 365 days, because Garmin offers it per day only.

After each sync, TRIMP, the tagging features and the automatic tags are updated.

---

## Tags

Every activity gets one tag: **orienteering race, orienteering training, interval, long run, easy run, strength, cycling, hiking/walking** or **other**.
Tags you set yourself (Tags page or Activity page) are never overwritten. Everything else gets an automatic suggestion after each sync:

| Tag | Automatic rule |
|---|---|
| Orienteering race | A run with Garmin event type "race", or a race keyword in the name (WOC, EOC, World Cup, O-Ringen, ...) |
| Orienteering training | An orienteering keyword in the name, **or** the orienteering model's score is at least 60% (see below) |
| Interval | Track run; interval words in the name; laps marked as interval/recovery by Garmin (structured workouts); **or** a run of 12 km or more with at least 6 laps of uneven length that alternate fast/slow. Regular 1 km auto-laps don't count. |
| Long run | A run of 15 km or more |
| Easy run | Any other run |
| Strength / Cycling / Hiking-walking | By Garmin activity type |
| Other | Everything else |

All thresholds and keyword lists are in `config.py`. After editing them, re-apply with `python -m garmin_sync.tagging`.

### Teaching it to recognise orienteering

Garmin names your runs "<City> Hardlopen", so orienteering has to be recognised from the GPS track.
The signals are sharp direction changes per km, time spent stopped (map reading), how uneven the speed is, and climb per km.

1. Open the **Tags** page, choose sort **"Most orienteering-like first"**, and widen the date range.
2. Tag at least **8 orienteering sessions** (training or race) **and 8 normal runs** (easy, long or interval) by hand, then **Save changes**. More examples give better results; 20+ of each is ideal.
3. Open **"Orienteering detection"** at the top of the page and click **Retrain & re-apply auto tags**.
   It shows how well the model does (cross-validated accuracy) and then auto-tags runs that score 60% or more as orienteering training.
4. Check the suggestions (filter "Current tag" = Orienteering training, "Only auto"), correct any mistakes, and retrain. Corrections become new training examples.

The model also retrains automatically after every sync. From the terminal: `python -m garmin_sync.features`.

### Laps

The **Activity** page shows laps as bars: bar width = lap duration, height = average HR (or pace/speed), colour = HR zone. A table below lists every lap.
Lap boundaries are also drawn as dotted lines on the HR/pace chart.
If you press lap at controls during orienteering, this works as a split analysis.

---

## Heart rate settings

TRIMP, a heart-rate-based load, is computed for every activity as a second load measure and as the fallback for FIT imports.
It uses HRmax (the highest max HR seen, excluding gym sessions) and your median resting HR.
To override them, set `HR_MAX` / `HR_REST` in `config.py`, then run `python -m garmin_sync.metrics`.
Zones come from Garmin (your custom zones as set in Garmin Connect).

---

## Asking Claude about your training (Claude Desktop app)

`mcp_server.py` is a small local **MCP server** that gives the Claude Desktop app read-only access to your training database.
After that, a normal Claude conversation can analyse your data. It's a free replacement for Shape's Claude link.

**Setup (one time).** Already done on this laptop. To redo it, add this to Claude Desktop's config file
(Claude Desktop → Settings → Developer → *Edit Config*):

```json
{
  "mcpServers": {
    "garmin-training": {
      "command": "C:\\Users\\jornk\\dev\\persoonlijk\\garmin_overview\\.venv\\Scripts\\python.exe",
      "args": ["C:\\Users\\jornk\\dev\\persoonlijk\\garmin_overview\\mcp_server.py"]
    }
  }
}
```

Then **fully quit** Claude Desktop (system tray icon → Quit, not just close the window) and start it again.
In a new chat, the tools menu (the sliders/plug icon below the message box) should list **garmin-training**.

**Use it.** Just ask, for example:
- "Give me an overview of my last 30 days and tell me what I can do better."
- "How recovered am I? Look at my resting HR, HRV and sleep for the last 2 weeks."
- "Analyse the laps of my last interval session."
- "Compare my orienteering volume this autumn with last autumn."

Or pick a ready-made prompt from the **+** menu → garmin-training: **training_review** (coach-style review with advice) or **weekly_checkin**.

Tools Claude can use: `training_summary`, `recovery_summary`, `list_activities`, `get_activity` (incl. laps), `daily_metrics`, `query_database` (read-only SQL) and `data_reference`.

Good to know:
- The dashboard doesn't need to run, but Claude Desktop does, on this laptop. Claude sees data up to your **last sync**, so sync first for fresh numbers.
- The server can't change anything: read-only database connection, SELECT-only queries, and no access to `.env` or your Garmin login.
- The numbers Claude retrieves become part of that conversation, like anything you type.
- Test without Claude: `.venv\Scripts\python mcp_server.py --selftest`. Problems? Claude Desktop → Settings → Developer shows the server status and its log.

### With Claude Code

Open Claude Code in this folder and ask questions in plain language, for example:
- "How many hours of orienteering did I do per month this year, compared with last year?"
- "What was my easy/hard split in the 6 weeks before my last race?"
- "Is my resting HR higher the day after sessions with a load above 150?"
- "Which weeks had the biggest jump in volume, and how did my HRV respond?"

Claude reads the database directly, guided by `DATA.md` and `CLAUDE.md`, and only reads. It never needs your credentials.

---

## Fallback: import FIT files / a Garmin data export

Use this if the Garmin API stops working, or to add older activities.

1. Request your data at https://www.garmin.com/account/datamanagement/exportdata. Garmin emails you a zip, usually within a few hours to days.
2. Save the zip in `data/exports/` (git-ignored) and run:
   ```powershell
   python -m garmin_sync.fit_import data\exports\<your-export>.zip
   ```
   This also works with a folder of `.fit` files or a single `.fit` file (e.g. copied from the watch's `GARMIN/Activity` folder over USB).

Activities that already exist (same start within 60 s) are skipped, so it's safe to run more than once. Existing activities without an HR stream or laps get them filled in from the FIT file.
FIT imports have no Garmin training load; the dashboard then uses TRIMP.
Daily summaries and sleep from the export's JSON files are imported on a best-effort basis, and only fill days the API hasn't already provided.

---

## Troubleshooting

- **"Garmin rejected the login"**: check your password in `.env`. If it's correct, Garmin may have changed its login system (this happens a few times a year). Try `pip install --upgrade garminconnect`. If that doesn't help, use the FIT importer.
- **"Garmin asks for an MFA code"** (from the Sync now button): the button can't ask for a code. Run `python -m garmin_sync.sync` once in a terminal.
- **"rate-limiting" / HTTP 429**: Garmin is throttling you. Wait 15–60 minutes and run the sync again; it resumes.
- **Force a fresh login**: delete the folder `~/.garminconnect` and run `python -m garmin_sync.auth`.
- **A field is always empty**: not every watch provides every metric (e.g. HRV, training readiness). Each sync keeps the last raw response per endpoint in `data/raw/samples/` (git-ignored), which helps with debugging.
- **Dashboard shows old data**: click **Sync now**, or reload the page. Data is cached for 5 minutes.
- **Something went wrong with the database**: `data/garmin.backup-before-phase4.db` is a copy from before the Phase 4 changes. To start over completely, delete `data/garmin.db` and sync again; manual tags are then lost.
- **Upgrading packages**: versions are pinned in `requirements.txt` so nothing changes unexpectedly. To move to a newer `garminconnect` (e.g. after a Garmin login change), change its version number there, run `pip install -r requirements.txt`, and do a test sync with `--since`.
