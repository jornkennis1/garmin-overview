# Garmin training overview

A private, local-only training dashboard built on your own Garmin data, made with orienteering in mind
(time, heart rate, zones and load first; pace second). It's a free replacement for Shape.
Everything runs on your own computer; nothing is hosted anywhere.

- **Sync**: `garmin_sync/` fetches activities, laps and daily metrics from Garmin Connect into `data/garmin.db` (SQLite).
- **Dashboard**: `app/` is a Streamlit app at http://localhost:8501, only reachable from your own computer.
- **Ask Claude**: `mcp_server.py` lets the Claude Desktop app analyse your training (read-only). See [Asking Claude](#asking-claude-about-your-training).

> **Privacy**: your data stays in `data/` and your personal settings in `settings.toml`; both are git-ignored, as are `.env` and FIT/zip files.
> Garmin login tokens are stored in `~/.garminconnect` in your home folder, outside this repo.
> The dashboard has no "Deploy" button and listens on localhost only.

---

## Quick start

You need **Python 3.12 or newer** ([python.org](https://www.python.org/downloads/); on Windows tick *Add python.exe to PATH*) and **git**.

**Windows** (PowerShell):

```powershell
git clone <repo-url> garmin_overview
cd garmin_overview
powershell -ExecutionPolicy Bypass -File .\setup.ps1
```

**macOS / Linux**:

```bash
git clone <repo-url> garmin_overview
cd garmin_overview
./setup.sh
```

The setup script:

1. creates a virtual environment in `.venv` and installs `requirements.txt`;
2. creates your own `settings.toml` from `settings.example.toml` (see [Personal settings](#personal-settings));
3. logs in to Garmin. It asks for your Garmin email and password in the terminal and **doesn't store the password**: only the login tokens are kept in `~/.garminconnect`. With two-step verification (MFA), type in the code Garmin sends you;
4. optionally fetches your last 30 days;
5. optionally connects Claude Desktop ([details](#asking-claude-about-your-training));
6. on Windows, optionally adds a `garmin` terminal command.

It's safe to run again. Then fetch your full history (this can take a few hours because of Garmin's rate limits; stop any time with **Ctrl+C**, the next run resumes):

```powershell
.venv\Scripts\python -m garmin_sync.sync      # Windows
.venv/bin/python -m garmin_sync.sync          # macOS / Linux
```

<details>
<summary>Manual setup (without the script)</summary>

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1        # macOS / Linux: source .venv/bin/activate
pip install -r requirements.txt
Copy-Item settings.example.toml settings.toml    # macOS / Linux: cp
python -m garmin_sync.auth          # log in once
python -m garmin_sync.sync --since 2026-09-01    # small test window
python -m garmin_sync.sync          # full history
```

If PowerShell refuses to run `Activate.ps1`, run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once.
</details>

**Optional `.env`**: Garmin tokens last for months and refresh themselves. When they finally expire, run `python -m garmin_sync.auth` again.
If you'd rather have that happen automatically (e.g. from the dashboard's **Sync now** button), copy `.env.example` to `.env` and fill in `GARMIN_EMAIL` and `GARMIN_PASSWORD`. Your password is then stored in that file on your computer (git-ignored).

---

## Daily use

**Windows**: double-click `start_dashboard.bat`, or in a terminal:

```powershell
garmin          # open the dashboard (if you added the command during setup)
garmin sync     # sync new Garmin data first, then open the dashboard
powershell -ExecutionPolicy Bypass -File .\sync_and_open.ps1          # same as 'garmin sync'
```

**macOS / Linux**:

```bash
.venv/bin/python -m garmin_sync.sync                # sync
.venv/bin/python -m streamlit run app/Dashboard.py  # open the dashboard
```

Your browser opens http://localhost:8501 on the **Today** page. Stop the dashboard with **Ctrl+C** in the terminal.
While the dashboard is open, the **Sync now** button in the sidebar fetches new data too.

**"garmin is not recognized"**: open a new terminal, or run `. $PROFILE` once.

**Dark mode**: the dashboard follows your system's light/dark setting. To switch manually, use the **⋮ menu** at the top right: **System / Light / Dark**.

| Page | What it shows |
|---|---|
| **Today** | Training readiness, fitness/fatigue, last night's sleep, this week per day, sport split, and a health grid (resting HR, HRV, stress, body battery, steps, active calories, VO2 max, weight, respiration). **Click any box** for a one-sentence explanation and a 30-day chart. |
| **Overview** | This week vs the previous 4 weeks (hours, sessions, load, easy share), weekly hours by tag, weekly load, fitness/fatigue curves, recent sessions |
| **Calendar** | Month grid coloured by tag or by load, with weekly totals. Click an activity for details. |
| **Intensity** | Time in HR zones per week (3- or 5-zone), easy vs hard trend, zone split per tag |
| **Recovery** | Resting HR, HRV (with Garmin's balanced range), sleep, body battery and stress with 7-day averages, plus load for context |
| **Activity** | One session: time/HR/load first, HR with zone bands and lap lines, pace (speed for cycling), elevation, **laps** (chart + table), time in zones, tag editor, optional map |
| **O-analysis** | All orienteering races and trainings: monthly volume, a session list (time, HR, load, climb, time stopped), and the **course map under your GPS track** (see below) |
| **Tags** | Filterable table to tag many activities at once, sortable by "orienteering-likeness" |
| **Settings** | How to switch light/dark, data status (what's synced, from when), where the other settings live |

The tag filter in the sidebar applies to every page.

---

## Asking Claude about your training

`mcp_server.py` is a small local **MCP server** that gives the **Claude Desktop** app read-only access to your training database.
A normal Claude conversation can then analyse your data. It needs no extra packages.

### Setup (one time)

1. Install [Claude Desktop](https://claude.ai/download) and sign in.
2. Run (the setup script offers to do this for you):
   ```powershell
   .venv\Scripts\python claude_desktop_setup.py --install    # macOS / Linux: .venv/bin/python
   ```
   This adds a `garmin-training` entry to Claude Desktop's config file with the paths of *your* clone, keeps any other MCP servers you have, and saves a `.bak` copy first.
   Without `--install` it only prints the snippet and the config file location, so you can add it by hand
   (Claude Desktop → Settings → Developer → *Edit Config*). It looks like this, with your own paths:
   ```json
   {
     "mcpServers": {
       "garmin-training": {
         "command": "C:\\path\\to\\garmin_overview\\.venv\\Scripts\\python.exe",
         "args": ["C:\\path\\to\\garmin_overview\\mcp_server.py"]
       }
     }
   }
   ```
   On macOS/Linux, `command` is `/path/to/garmin_overview/.venv/bin/python`.
3. **Fully quit** Claude Desktop (system tray / menu bar icon → Quit, not just close the window) and start it again.
4. In a new chat, the tools menu (the sliders/plug icon below the message box) should list **garmin-training**.

Moved the project folder? Run `claude_desktop_setup.py --install` again.

### Use it

Just ask, for example:
- "Give me an overview of my last 30 days and tell me what I can do better."
- "How recovered am I? Look at my resting HR, HRV and sleep for the last 2 weeks."
- "Analyse the laps of my last interval session."
- "Compare my orienteering volume this autumn with last autumn."

Or pick a ready-made prompt from the **+** menu → garmin-training: **training_review** (coach-style review with advice) or **weekly_checkin**.

Tools Claude can use: `training_summary`, `recovery_summary`, `list_activities`, `get_activity` (incl. laps), `daily_metrics`, `query_database` (read-only SQL) and `data_reference`.

Good to know:
- The dashboard doesn't need to run, but Claude Desktop does, on the same computer. Claude sees data up to your **last sync**, so sync first for fresh numbers.
- The server can't change anything: read-only database connection, SELECT-only queries, and no access to `.env` or your Garmin login.
- The numbers Claude retrieves become part of that conversation, like anything you type.
- Test without Claude: `.venv\Scripts\python mcp_server.py --selftest`. Problems? Claude Desktop → Settings → Developer shows the server status and its log.

### With Claude Code

Open Claude Code in this folder and ask questions in plain language, for example:
- "How many hours of orienteering did I do per month this year, compared with last year?"
- "What was my easy/hard split in the 6 weeks before my last race?"
- "Is my resting HR higher the day after sessions with a load above 150?"

Claude reads the database directly, guided by `DATA.md` and `CLAUDE.md`, and only reads. It never needs your credentials.

---

## Personal settings

Your personal settings live in **`settings.toml`** (git-ignored, created by the setup script from `settings.example.toml`).
Every line is optional; uncomment a line to override the default from `config.py`:

| Setting | What it does |
|---|---|
| `hr_max`, `hr_rest` | Override HRmax and resting HR used for TRIMP. Default: highest max HR seen (excluding gym sessions) and the median resting HR of the last 60 days. |
| `trimp_k` | TRIMP curve: `1.92` (standard "male") or `1.67` ("female") |
| `hr_zone_lower_bounds` | HR zones for FIT imports when Garmin's zones are unknown |
| `o_race_keywords`, `o_keywords`, `interval_keywords` | Words in activity names that trigger a tag. Add the names you give your own sessions, in your own language. |
| `long_run_min_km`, `interval_*`, `o_prob_threshold`, ... | Tagging thresholds |
| `api_delay_s` | Pause between Garmin API calls; raise it if you get rate-limited |
| `[tags]` | Rename tag labels shown in the dashboard |

A typo in a setting name gives a clear error instead of being silently ignored. After changing heart-rate settings run `python -m garmin_sync.metrics`; after changing tagging settings run `python -m garmin_sync.tagging`.

Heart-rate zones come from Garmin (your zones as set in Garmin Connect). TRIMP, a heart-rate-based load, is computed for every activity as a second load measure and as the fallback for FIT imports.

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
- **Training status**: status, acute/chronic load, VO2max and training readiness. Only for the last 365 days by default, because Garmin offers it per day only.

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

All thresholds and keyword lists can be changed in `settings.toml` (see [Personal settings](#personal-settings)).

### Teaching it to recognise orienteering

Garmin gives runs default names like "<City> Running", so orienteering has to be recognised from the GPS track.
The signals are sharp direction changes per km, time spent stopped (map reading), how uneven the speed is, and climb per km.

1. Open the **Tags** page, choose sort **"Most orienteering-like first"**, and widen the date range.
2. Tag at least **8 orienteering sessions** (training or race) **and 8 normal runs** (easy, long or interval) by hand, then **Save changes**. More examples give better results; 20+ of each is ideal.
3. Open **"Orienteering detection"** at the top of the page and click **Retrain & re-apply auto tags**.
   It shows how well the model does (cross-validated accuracy) and then auto-tags runs that score 60% or more as orienteering training.
4. Check the suggestions (filter "Current tag" = Orienteering training, "Only auto"), correct any mistakes, and retrain. Corrections become new training examples.

The model is trained on *your* tags only and also retrains automatically after every sync. From the terminal: `python -m garmin_sync.features`.

### Laps

The **Activity** page shows laps as bars: bar width = lap duration, height = average HR (or pace/speed), colour = HR zone. A table below lists every lap.
Lap boundaries are also drawn as dotted lines on the HR/pace chart.
If you press lap at controls during orienteering, this works as a split analysis.

---

## O-analysis: your route on the course map

The **O-analysis** page lists every activity tagged *orienteering race* or *orienteering training*. Select a session to add its course map:

1. Upload the map as **PDF, JPG or PNG** (a PDF export, a scan or a photo taken straight from above).
2. Mark the **same 3 spots** on the map and on your GPS track, e.g. the start, a control far away and the finish. For each point: click the map, fine-tune it in the zoom, then click the track. Start, finish and lap points snap into place, so if you press lap at controls those are the easiest to use.
3. Check the preview: the route should follow paths and controls. The *alignment check* shows the error per point (GPS is typically 5–15 m off in the forest) and, for PDFs, the map scale it found.
4. **Save map**. It's stored in `data/maps/` (git-ignored) and shown every time you open that session.

On a saved map you can colour the route by **HR zone** or **speed** (dark clusters = where you stopped or hesitated), show your lap points, hover the route for time/HR/speed, and download a PNG of the map with the route drawn on it.
The alignment uses rotation, scale and position only (maps don't stretch), so 3 good points are enough; a photo taken at an angle won't line up everywhere.

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

## Contributing / keeping your data out of git

If you change the code and want to push it back (or to your own fork), check first that nothing personal is staged:

```powershell
git status                                                  # .env, settings.toml and data/ must NOT be listed
git check-ignore -v .env settings.toml data/garmin.db       # each should print a .gitignore rule
```

Personal defaults that everyone could benefit from belong in `config.py`; anything that is just yours belongs in `settings.toml`.

---

## Troubleshooting

- **"Garmin rejected the login"**: check your email and password. If they're correct, Garmin may have changed its login system (this happens a few times a year). Try `pip install --upgrade garminconnect`. If that doesn't help, use the FIT importer.
- **"Garmin asks for an MFA code"** or **"No valid cached login"** (from the Sync now button): the button can't ask for input. Run `python -m garmin_sync.auth` once in a terminal.
- **"rate-limiting" / HTTP 429**: Garmin is throttling you. Wait 15–60 minutes and run the sync again; it resumes.
- **Force a fresh login**: delete the folder `~/.garminconnect` and run `python -m garmin_sync.auth`.
- **"Unknown setting ... in settings.toml"**: a typo in a setting name; the error lists the allowed names.
- **A field is always empty**: not every watch provides every metric (e.g. HRV, training readiness). Each sync keeps the last raw response per endpoint in `data/raw/samples/` (git-ignored), which helps with debugging.
- **Dashboard shows old data**: click **Sync now**, or reload the page. Data is cached for 5 minutes.
- **Start over**: delete `data/garmin.db` and sync again; manual tags are then lost.
- **Upgrading packages**: versions are pinned in `requirements.txt` so nothing changes unexpectedly. To move to a newer `garminconnect` (e.g. after a Garmin login change), change its version number there, run `pip install -r requirements.txt`, and do a test sync with `--since`.
