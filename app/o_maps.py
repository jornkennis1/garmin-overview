"""Orienteering maps: load a map file, align it to the GPS track with 3 point pairs, store it.

The alignment is a similarity transform (rotation, uniform scale, offset) from local metres around
the track to map pixels, fitted by least squares to 3 point pairs. Orienteering maps don't shear, so
this is robust to small click errors, and the leftover error per point tells how good the fit is.
Map images are stored in data/maps/ (git-ignored); the point pairs in the o_maps table.
"""

import io
import json
import math

import numpy as np
import pandas as pd
from PIL import Image, ImageDraw

import config
from db.database import connect

Image.MAX_IMAGE_PIXELS = 200_000_000  # large scans are fine; this is a local, trusted file
MAX_SIDE = 5000      # stored map images are downscaled to at most this many pixels per side
PDF_DPI = 200        # render resolution for PDF maps
TRACK_CANVAS = 800   # size of the clickable track image
M_PER_DEG_LAT = 110_540
M_PER_DEG_LON = 111_320


# ---------------------------------------------------------------- loading map files

def pdf_page_count(data: bytes) -> int:
    import pypdfium2 as pdfium
    return len(pdfium.PdfDocument(data))


def load_map(data: bytes, filename: str, page: int = 0) -> tuple[Image.Image, float | None]:
    """Return the map as an RGB image plus its resolution in dpi (None when unknown)."""
    if filename.lower().endswith(".pdf"):
        import pypdfium2 as pdfium
        img = pdfium.PdfDocument(data)[page].render(scale=PDF_DPI / 72).to_pil()
        dpi = float(PDF_DPI)
    else:
        img = Image.open(io.BytesIO(data))
        dpi = img.info.get("dpi", (None,))[0] or None
    img = img.convert("RGB")
    if max(img.size) > MAX_SIDE:
        f = MAX_SIDE / max(img.size)
        img = img.resize((round(img.width * f), round(img.height * f)), Image.LANCZOS)
        dpi = dpi * f if dpi else None
    return img, dpi


# ---------------------------------------------------------------- geometry

def to_metres(lat, lon, origin: tuple[float, float]) -> tuple[np.ndarray, np.ndarray]:
    """Local equirectangular projection in metres around origin; exact enough for one course."""
    lat0, lon0 = origin
    x = (np.asarray(lon, float) - lon0) * M_PER_DEG_LON * math.cos(math.radians(lat0))
    y = (np.asarray(lat, float) - lat0) * M_PER_DEG_LAT
    return x, y


def solve_transform(track_pts: list, map_pts: list) -> np.ndarray:
    """2x3 matrix M with [px, py] = M @ [x, y, 1], fitted to (lat, lon) <-> (px, py) pairs.

    Least-squares similarity fit in complex numbers: q = a*p + b, with the image y axis flipped so
    that a is a plain rotation + scale (no mirroring).
    """
    x, y = to_metres([p[0] for p in track_pts], [p[1] for p in track_pts], tuple(track_pts[0]))
    pm = x + 1j * y
    q = np.array([px - 1j * py for px, py in map_pts])
    pc, qc = pm - pm.mean(), q - q.mean()
    a = (qc * pc.conj()).sum() / (np.abs(pc) ** 2).sum()
    b = q.mean() - a * pm.mean()
    return np.array([[a.real, -a.imag, b.real], [-a.imag, -a.real, -b.imag]])


def project(m: np.ndarray, track_pts: list, lat, lon) -> tuple[np.ndarray, np.ndarray]:
    x, y = to_metres(lat, lon, tuple(track_pts[0]))
    return m[0, 0] * x + m[0, 1] * y + m[0, 2], m[1, 0] * x + m[1, 1] * y + m[1, 2]


def alignment_info(m: np.ndarray, dpi: float | None, track_pts: list, map_pts: list) -> dict:
    """Human checks: metres per pixel, map scale (if dpi known), rotation and the error per point."""
    m_per_px = 1 / math.hypot(m[0, 0], m[1, 0])
    px, py = project(m, track_pts, [p[0] for p in track_pts], [p[1] for p in track_pts])
    errors = [math.dist((px[i], py[i]), map_pts[i]) * m_per_px for i in range(len(map_pts))]
    return {
        "m_per_px": m_per_px,
        "scale": m_per_px / (0.0254 / dpi) if dpi else None,
        "rotation_deg": math.degrees(math.atan2(m[0, 1], -m[1, 1])),  # north on the map, clockwise from up
        "errors_m": errors,
    }


# ---------------------------------------------------------------- track picker

def track_canvas(samples: pd.DataFrame, laps: pd.DataFrame) -> tuple[Image.Image, dict]:
    """Draw the GPS track on a plain canvas for clicking. Returns the image and what's needed to
    turn a click back into a track point (pixel positions of every sample and of the landmarks)."""
    pts = samples.dropna(subset=["lat", "lon"]).reset_index(drop=True)
    origin = (pts["lat"].iloc[0], pts["lon"].iloc[0])
    x, y = to_metres(pts["lat"], pts["lon"], origin)
    pad = 30
    span = max(x.max() - x.min(), y.max() - y.min(), 1)
    f = (TRACK_CANVAS - 2 * pad) / span
    w = round((x.max() - x.min()) * f) + 2 * pad
    h = round((y.max() - y.min()) * f) + 2 * pad
    px = (x - x.min()) * f + pad
    py = (y.max() - y) * f + pad

    marks = {"Start": 0, "Finish": len(pts) - 1}
    if len(laps) > 1 and laps["start_offset_s"].notna().all():
        t = pts["t_offset_s"].to_numpy()
        for _, lap in laps.iloc[:-1].iterrows():  # end of each lap = a control if you pressed lap there
            end = lap["start_offset_s"] + (lap["duration_s"] or 0)
            marks[f"Lap {int(lap['lap_index'])}"] = int(np.abs(t - end).argmin())

    img = Image.new("RGB", (w, h), "white")
    d = ImageDraw.Draw(img)
    d.line(list(zip(px, py)), fill="#e34948", width=3, joint="curve")
    for name, i in marks.items():
        r = 7 if name in ("Start", "Finish") else 5
        d.ellipse([px[i] - r, py[i] - r, px[i] + r, py[i] + r], outline="#1f1e1c", width=2)
        if name.startswith("Lap"):
            d.text((px[i] + 7, py[i] - 7), name[4:], fill="#1f1e1c")
    d.text((px[0] + 9, py[0] - 16), "S", fill="#1f1e1c")
    d.text((px[-1] + 9, py[-1] + 4), "F", fill="#1f1e1c")
    return img, {"px": px, "py": py, "lat": pts["lat"].to_numpy(), "lon": pts["lon"].to_numpy(), "marks": marks}


def snap_to_track(geo: dict, cx: float, cy: float, snap_px: float = 14) -> tuple[float, float, str | None]:
    """Nearest landmark (start, finish, lap end) within snap_px, otherwise the nearest sample."""
    best = min(geo["marks"].items(), key=lambda kv: math.hypot(geo["px"][kv[1]] - cx, geo["py"][kv[1]] - cy))
    name, i = best
    if math.hypot(geo["px"][i] - cx, geo["py"][i] - cy) > snap_px:
        i, name = int(np.hypot(geo["px"] - cx, geo["py"] - cy).argmin()), None
    return float(geo["lat"][i]), float(geo["lon"][i]), name


def draw_points(img: Image.Image, pts: list, active: int | None = None, radius: int | None = None) -> Image.Image:
    """Numbered markers for the chosen points (None = not chosen yet)."""
    out = img.copy()
    d = ImageDraw.Draw(out)
    r = radius or max(8, round(max(img.size) / 180))
    for n, p in enumerate(pts):
        if p is None:
            continue
        x, y = p
        color = "#eb6834" if n == active else "#2a78d6"
        d.ellipse([x - r, y - r, x + r, y + r], outline=color, width=max(2, r // 4))
        d.line([x - r / 2, y, x + r / 2, y], fill=color, width=2)
        d.line([x, y - r / 2, x, y + r / 2], fill=color, width=2)
        d.text((x + r + 3, y - r - 3), str(n + 1), fill=color, font_size=max(14, r * 2))
    return out


# ---------------------------------------------------------------- output image

def route_image(img: Image.Image, xs, ys, color: str = "#e0182d", width: int | None = None) -> Image.Image:
    """The map with the route drawn on it, at full resolution (for download)."""
    out = img.copy().convert("RGBA")
    layer = Image.new("RGBA", out.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    w = width or max(3, round(max(img.size) / 600))
    pts = [(float(x), float(y)) for x, y in zip(xs, ys) if not (math.isnan(x) or math.isnan(y))]
    d.line(pts, fill=color + "c8", width=w, joint="curve")
    return Image.alpha_composite(out, layer).convert("RGB")


def png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


# ---------------------------------------------------------------- storage

def maps_dir():
    d = config.DATA_DIR / "maps"
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_map(activity_id: int, img: Image.Image, source_name: str, dpi: float | None,
             map_pts: list, track_pts: list) -> None:
    file = f"{activity_id}.png"
    img.save(maps_dir() / file, format="PNG", optimize=True)
    conn = connect()
    try:
        conn.execute(
            """INSERT INTO o_maps (activity_id, image_file, source_name, dpi, map_points, track_points)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT (activity_id) DO UPDATE SET image_file = excluded.image_file,
                 source_name = excluded.source_name, dpi = excluded.dpi, map_points = excluded.map_points,
                 track_points = excluded.track_points, updated_at = datetime('now')""",
            (activity_id, file, source_name, dpi, json.dumps(map_pts), json.dumps(track_pts)),
        )
        conn.commit()
    finally:
        conn.close()


def load_saved(activity_id: int) -> dict | None:
    conn = connect()
    try:
        row = conn.execute("SELECT * FROM o_maps WHERE activity_id = ?", (activity_id,)).fetchone()
    finally:
        conn.close()
    if not row or not (maps_dir() / row["image_file"]).exists():
        return None
    return {
        "img": Image.open(maps_dir() / row["image_file"]).convert("RGB"),
        "source_name": row["source_name"],
        "dpi": row["dpi"],
        "map_pts": json.loads(row["map_points"]),
        "track_pts": json.loads(row["track_points"]),
        "updated_at": row["updated_at"],
    }


def delete_map(activity_id: int) -> None:
    conn = connect()
    try:
        row = conn.execute("SELECT image_file FROM o_maps WHERE activity_id = ?", (activity_id,)).fetchone()
        conn.execute("DELETE FROM o_maps WHERE activity_id = ?", (activity_id,))
        conn.commit()
    finally:
        conn.close()
    if row:
        (maps_dir() / row["image_file"]).unlink(missing_ok=True)


def saved_ids() -> set[int]:
    conn = connect()
    try:
        return {r[0] for r in conn.execute("SELECT activity_id FROM o_maps")}
    finally:
        conn.close()
