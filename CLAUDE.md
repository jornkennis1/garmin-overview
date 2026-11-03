# Garmin training overview

Private, local-only training dashboard for an orienteer (Garmin data → SQLite → Streamlit).

- Questions about training: query `data/garmin.db` (read-only) using the schema and example queries in `DATA.md`.
  Prefer the views `v_activities` and `v_weekly`. Rank time, HR, zones and load above pace (orienteering).
- `mcp_server.py` exposes the database read-only to the Claude Desktop app (MCP over stdio, no extra deps). Keep it read-only; keep tool output compact.
- Never read, print or commit `.env`, `~/.garminconnect/` or anything in `data/`. Keep the repo free of personal paths, names and data: friends clone it.
- Run code with the venv: `.venv\Scripts\python -m garmin_sync.sync` etc. Defaults are in `config.py`; personal overrides in `settings.toml` (git-ignored, template `settings.example.toml`, never commit it). New overridable settings go in `_OVERRIDABLE` in `config.py` and in `settings.example.toml`.
- `app/insights.py`: rule-based insight texts shown on the pages (compare with the user's own normal; stay quiet without recent data).
- Tags: built-in in `config.TAGS`, the user's own in table `custom_tags` (`garmin_sync/tagging.py`: `all_tags`, `load_custom_tags`). Don't hard-code the tag list.
- Activity names: sync writes `activities.name`; the user's own name is `custom_name`. Always read names via `v_activities.name`.
- `app/planning.py` + `app/pages/9_Plan.py`: races, weekly plans (tables `races`, `week_plans`), form projection, taper, season comparison.
- `app/o_maps.py` + `app/pages/7_O_Analysis.py`: course maps aligned to GPS tracks (images in `data/maps/`, alignment in `o_maps`).
- Tests: `.venv\Scripts\python -m pytest -q` (`tests/`, dev deps in `requirements-dev.txt`). Made-up data only, never copy from `data/`. `tests/conftest.py` points config at temp paths.
- Schema changes: new tables/views go in `db/schema.sql`; changes to existing tables go in `MIGRATIONS` in `db/database.py` (use `add_column` for tables newer than some databases; `tests/test_migrations.py` checks old databases migrate). Keep `DATA.md` in sync.
