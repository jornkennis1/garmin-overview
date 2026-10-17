# Garmin training overview

Private, local-only training dashboard for an orienteer (Garmin data → SQLite → Streamlit).

- Questions about training: query `data/garmin.db` (read-only) using the schema and example queries in `DATA.md`.
  Prefer the views `v_activities` and `v_weekly`. Rank time, HR, zones and load above pace (orienteering).
- `mcp_server.py` exposes the database read-only to the Claude Desktop app (MCP over stdio, no extra deps). Keep it read-only; keep tool output compact.
- Never read, print or commit `.env`, `~/.garminconnect/` or anything in `data/`.
- Run code with the venv: `.venv\Scripts\python -m garmin_sync.sync` etc. Settings are in `config.py`.
- Schema changes: new tables/views go in `db/schema.sql`; changes to existing tables go in `MIGRATIONS` in `db/database.py`. Keep `DATA.md` in sync.
