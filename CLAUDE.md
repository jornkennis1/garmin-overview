# Garmin training overview

Private, local-only training dashboard for an orienteer (Garmin data → SQLite → Streamlit).

- Questions about training: query `data/garmin.db` (read-only) using the schema and example queries in `DATA.md`.
  Prefer the views `v_activities` and `v_weekly`. Rank time, HR, zones and load above pace (orienteering).
- `mcp_server.py` exposes the database read-only to the Claude Desktop app (MCP over stdio, no extra deps). Keep it read-only; keep tool output compact.
- Never read, print or commit `.env`, `~/.garminconnect/` or anything in `data/`. Keep the repo free of personal paths, names and data: friends clone it.
- Run code with the venv: `.venv\Scripts\python -m garmin_sync.sync` etc. Defaults are in `config.py`; personal overrides in `settings.toml` (git-ignored, template `settings.example.toml`, never commit it). New overridable settings go in `_OVERRIDABLE` in `config.py` and in `settings.example.toml`.
- `app/o_maps.py` + `app/pages/7_O_Analysis.py`: course maps aligned to GPS tracks (images in `data/maps/`, alignment in `o_maps`).
- Schema changes: new tables/views go in `db/schema.sql`; changes to existing tables go in `MIGRATIONS` in `db/database.py`. Keep `DATA.md` in sync.
