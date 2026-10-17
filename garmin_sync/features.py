"""Per-activity features for automatic tagging, and the orienteering model trained on manual tags.

    python -m garmin_sync.features            # update features + retrain the orienteering model
    python -m garmin_sync.features --recompute  # recompute features for all runs

Interval signals come from laps. The orienteering signature comes from the GPS track:
frequent sharp direction changes, short stops (map reading) and very uneven speed.
"""

import argparse
import json
import math
import sqlite3

import numpy as np
import pandas as pd

import config
from db.database import set_state, upsert

O_TAGS = ("o_training", "o_race")
RUN_TAGS = ("o_training", "o_race", "interval", "long_run", "easy_run")
MODEL_FEATURES = ["turns_per_km", "stop_frac", "speed_cv", "climb_per_km"]


# ---------------------------------------------------------------- lap features

def lap_features(laps: pd.DataFrame) -> dict:
    laps = laps[(laps["distance_m"] > 0) & (laps["duration_s"] > 0)]
    out = {"n_laps": len(laps), "lap_dist_cv": None, "lap_alternation": None, "lap_fast_slow_gap": None,
           "has_interval_laps": int(laps["intensity"].isin(["INTERVAL", "RECOVERY"]).any())}
    if len(laps) < 3:
        return out
    # A short final lap (auto-lap remainder) would inflate the variation; ignore it.
    if laps["distance_m"].iloc[-1] < 0.5 * laps["distance_m"].median():
        laps = laps.iloc[:-1]
    dist = laps["distance_m"].to_numpy()
    speed = (laps["distance_m"] / laps["duration_s"]).to_numpy()
    out["lap_dist_cv"] = float(dist.std() / dist.mean())
    fast = speed > np.median(speed)
    out["lap_alternation"] = float(np.mean(fast[1:] != fast[:-1]))
    if fast.any() and (~fast).any():
        out["lap_fast_slow_gap"] = float(speed[fast].mean() / speed[~fast].mean() - 1)
    return out


# ---------------------------------------------------------------- track features

def track_features(s: pd.DataFrame) -> dict:
    out = {"turns_per_km": None, "stop_frac": None, "speed_cv": None}
    if len(s) < 50:
        return out
    t = s["t_offset_s"].to_numpy()
    dt = np.clip(np.diff(t, prepend=t[0]), 0, 30)
    speed = s["speed_mps"].to_numpy(dtype=float)
    valid = ~np.isnan(speed)
    if valid.sum() > 20 and dt[valid].sum() > 0:
        out["stop_frac"] = float(dt[valid & (speed < 1.0)].sum() / dt[valid].sum())
        smooth = pd.Series(speed).rolling(5, min_periods=1, center=True).mean().to_numpy()
        moving = valid & (smooth >= 1.0)
        if moving.sum() > 20:
            out["speed_cv"] = float(smooth[moving].std() / smooth[moving].mean())

    gps = s.dropna(subset=["lat", "lon"])
    if len(gps) >= 50:
        lat0 = math.radians(gps["lat"].mean())
        x = 6371000 * np.radians(gps["lon"].to_numpy()) * math.cos(lat0)
        y = 6371000 * np.radians(gps["lat"].to_numpy())
        cum = np.concatenate([[0], np.cumsum(np.hypot(np.diff(x), np.diff(y)))])
        if cum[-1] >= 500:
            # Resample every 15 m along the path so speed/sampling rate don't matter, then count
            # direction changes sharper than 60 degrees.
            grid = np.arange(0, cum[-1], 15.0)
            xi, yi = np.interp(grid, cum, x), np.interp(grid, cum, y)
            bearing = np.arctan2(np.diff(yi), np.diff(xi))
            dtheta = np.abs((np.diff(bearing) + np.pi) % (2 * np.pi) - np.pi)
            out["turns_per_km"] = float((dtheta > math.radians(60)).sum() / (cum[-1] / 1000))
    return out


# ---------------------------------------------------------------- updating

def update_features(conn: sqlite3.Connection, recompute: bool = False) -> dict:
    """Compute features for runs that don't have them yet, then (re)train the orienteering model."""
    run_types = ",".join(f"'{t}'" for t in config.RUN_TYPES)
    sql = f"""SELECT a.activity_id FROM activities a
              LEFT JOIN activity_features f USING (activity_id)
              WHERE a.sport_type IN ({run_types})"""
    if not recompute:
        sql += " AND f.activity_id IS NULL"
    todo = conn.execute(sql).fetchall()
    for r in todo:
        aid = r["activity_id"]
        laps = pd.read_sql_query(
            "SELECT distance_m, duration_s, intensity FROM activity_laps WHERE activity_id = ? ORDER BY lap_index",
            conn, params=(aid,))
        samples = pd.read_sql_query(
            "SELECT t_offset_s, speed_mps, lat, lon FROM activity_samples WHERE activity_id = ? ORDER BY t_offset_s",
            conn, params=(aid,))
        row = {"activity_id": aid, **lap_features(laps), **track_features(samples)}
        upsert(conn, "activity_features", row, "activity_id")
    conn.commit()
    summary = train_o_model(conn)
    summary["features_updated"] = len(todo)
    return summary


def _training_frame(conn: sqlite3.Connection) -> pd.DataFrame:
    df = pd.read_sql_query(
        """SELECT f.activity_id, f.turns_per_km, f.stop_frac, f.speed_cv,
                  a.elev_gain_m * 1000.0 / NULLIF(a.distance_m, 0) AS climb_per_km,
                  t.tag, t.source
           FROM activity_features f JOIN activities a USING (activity_id)
           LEFT JOIN activity_tags t USING (activity_id)""",
        conn,
    )
    return df


def _fit_logistic(X: np.ndarray, y: np.ndarray, l2: float = 0.1, iters: int = 3000, lr: float = 0.1) -> np.ndarray:
    Xb = np.hstack([np.ones((len(X), 1)), X])
    w = np.zeros(Xb.shape[1])
    pos_weight = (len(y) - y.sum()) / max(y.sum(), 1)  # balance classes
    sw = np.where(y == 1, pos_weight, 1.0)
    for _ in range(iters):
        p = 1 / (1 + np.exp(-Xb @ w))
        grad = Xb.T @ (sw * (p - y)) / sw.sum() + l2 * np.r_[0, w[1:]]
        w -= lr * grad
    return w


def _predict(w: np.ndarray, X: np.ndarray) -> np.ndarray:
    return 1 / (1 + np.exp(-(np.hstack([np.ones((len(X), 1)), X]) @ w)))


def train_o_model(conn: sqlite3.Connection) -> dict:
    """Train orienteering-vs-other-run on manually tagged runs; write o_prob for all runs."""
    df = _training_frame(conn)
    labelled = df[(df["source"] == "manual") & df["tag"].isin(RUN_TAGS) & df["turns_per_km"].notna()]
    y = labelled["tag"].isin(O_TAGS).to_numpy(dtype=float)
    n_pos, n_neg = int(y.sum()), int(len(y) - y.sum())
    if n_pos < config.O_MODEL_MIN_EXAMPLES or n_neg < config.O_MODEL_MIN_EXAMPLES:
        conn.execute("UPDATE activity_features SET o_prob = NULL")
        conn.commit()
        return {"model": None, "n_pos": n_pos, "n_neg": n_neg,
                "needed": config.O_MODEL_MIN_EXAMPLES}

    mean = labelled[MODEL_FEATURES].mean()
    std = labelled[MODEL_FEATURES].std().replace(0, 1).fillna(1)

    def prep(frame):
        return ((frame[MODEL_FEATURES].fillna(mean) - mean) / std).to_numpy()

    X = prep(labelled)
    # 5-fold cross-validated accuracy, so the reported quality is honest.
    rng = np.random.default_rng(0)
    folds = rng.integers(0, 5, len(y))
    correct = 0
    for k in range(5):
        tr, te = folds != k, folds == k
        if te.any() and len(set(y[tr])) == 2:
            correct += int(((_predict(_fit_logistic(X[tr], y[tr]), X[te]) >= 0.5) == y[te]).sum())
    w = _fit_logistic(X, y)

    scored = df[df["turns_per_km"].notna()]
    probs = _predict(w, prep(scored))
    conn.execute("UPDATE activity_features SET o_prob = NULL")
    conn.executemany("UPDATE activity_features SET o_prob = ? WHERE activity_id = ?",
                     [(round(float(p), 3), int(a)) for p, a in zip(probs, scored["activity_id"])])
    model = {"features": MODEL_FEATURES, "weights": [round(float(v), 4) for v in w],
             "mean": mean.round(4).tolist(), "std": std.round(4).tolist(),
             "n_pos": n_pos, "n_neg": n_neg, "cv_accuracy": round(correct / len(y), 3)}
    set_state(conn, "o_model", json.dumps(model))
    conn.commit()
    return {"model": model, "n_pos": n_pos, "n_neg": n_neg,
            "suggested_o": int((probs >= config.O_PROB_THRESHOLD).sum())}


if __name__ == "__main__":
    from db.database import connect
    from garmin_sync.tagging import apply_auto_tags

    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--recompute", action="store_true", help="recompute features for all runs")
    args = p.parse_args()
    c = connect()
    res = update_features(c, recompute=args.recompute)
    print(f"Features updated for {res['features_updated']} runs.")
    if res["model"] is None:
        print(f"Orienteering model not trained yet: you have manually tagged {res['n_pos']} orienteering runs "
              f"and {res['n_neg']} other runs; at least {res['needed']} of each are needed.")
    else:
        m = res["model"]
        print(f"Orienteering model trained on {m['n_pos']} O runs and {m['n_neg']} other runs "
              f"(cross-validated accuracy {m['cv_accuracy']:.0%}); {res['suggested_o']} runs look like orienteering.")
    print(f"{apply_auto_tags(c)} auto tags updated.")
