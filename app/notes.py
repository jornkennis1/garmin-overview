"""Injury, illness, holiday and other notes on the calendar (table day_notes, edited on the Calendar page)."""

import pandas as pd

from db.database import connect

KINDS = {"injury": "Injury", "illness": "Illness", "holiday": "Holiday", "other": "Other"}
ICONS = {"injury": "✚", "illness": "☂", "holiday": "✈", "other": "✎"}
# Kinds during which missing or light training is expected, so the insights about that stay quiet.
BREAK_KINDS = ("injury", "illness", "holiday")


def load_notes() -> pd.DataFrame:
    """All notes; `end_date` is the last day (= `date` for one day), `days` the number of days."""
    conn = connect()
    try:
        df = pd.read_sql_query("SELECT note_id, date, end_date, kind, text FROM day_notes ORDER BY date", conn)
    finally:
        conn.close()
    return _dates(df)


def _dates(df: pd.DataFrame) -> pd.DataFrame:
    df["date"] = pd.to_datetime(df["date"])
    df["end_date"] = pd.to_datetime(df["end_date"]).where(lambda s: s > df["date"], df["date"])
    df["days"] = (df["end_date"] - df["date"]).dt.days + 1
    return df


def save_notes(edited: pd.DataFrame, original: pd.DataFrame) -> int:
    """Write the note editor back: insert new rows, update changed ones, delete removed ones."""
    conn = connect()
    n = 0
    try:
        keep = set(edited["note_id"].dropna().astype(int))
        for nid in set(original["note_id"].astype(int)) - keep:
            conn.execute("DELETE FROM day_notes WHERE note_id = ?", (nid,))
            n += 1
        for _, r in edited.iterrows():
            if pd.isna(r["date"]):
                continue
            start = pd.Timestamp(r["date"])
            end = pd.Timestamp(r["end_date"]) if pd.notna(r.get("end_date")) else None
            end = end.strftime("%Y-%m-%d") if end is not None and end > start else None  # one day: no end date
            text = r["text"].strip() if isinstance(r["text"], str) and r["text"].strip() else None
            row = (start.strftime("%Y-%m-%d"), end, r["kind"] if r["kind"] in KINDS else "other", text)
            if pd.isna(r["note_id"]):
                conn.execute("INSERT INTO day_notes (date, end_date, kind, text) VALUES (?,?,?,?)", row)
            else:
                conn.execute("UPDATE day_notes SET date=?, end_date=?, kind=?, text=?, updated_at=datetime('now') "
                             "WHERE note_id=?", (*row, int(r["note_id"])))
            n += 1
        conn.commit()
    finally:
        conn.close()
    return n


def in_range(notes: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    """Notes that overlap the days start..end."""
    return notes[(notes["date"] <= end) & (notes["end_date"] >= start)]


def note_days(notes: pd.DataFrame) -> pd.DataFrame:
    """One row per day a note covers: note columns plus `day`."""
    rows = [{**r.to_dict(), "day": d} for _, r in notes.iterrows()
            for d in pd.date_range(r["date"], r["end_date"], freq="D")]
    return pd.DataFrame(rows, columns=[*notes.columns, "day"])


def current_break(notes: pd.DataFrame, today: pd.Timestamp, grace_days: int = 3) -> pd.Series | None:
    """The injury/illness/holiday note covering today, or one that ended at most `grace_days` ago."""
    b = notes[notes["kind"].isin(BREAK_KINDS) & (notes["date"] <= today)
              & (notes["end_date"] >= today - pd.Timedelta(days=grace_days))]
    return b.iloc[-1] if len(b) else None


def describe(r) -> str:
    """'Illness: flu (Mon 02 – Thu 05 Nov)'."""
    a, b = r["date"], r["end_date"]
    when = f"{a:%a %d %b}" if b <= a else (f"{a:%a %d} – {b:%a %d %b}" if a.month == b.month
                                           else f"{a:%a %d %b} – {b:%a %d %b}")
    text = f": {r['text']}" if isinstance(r["text"], str) and r["text"] else ""
    return f"{KINDS.get(r['kind'], r['kind'])}{text} ({when})"
