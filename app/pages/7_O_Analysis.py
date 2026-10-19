"""O-analysis: all orienteering races and trainings, with the course map aligned under the GPS track."""

import math

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from streamlit_image_coordinates import streamlit_image_coordinates

import common as c
import insights
import o_maps as om

c.setup_page("O-analysis", "🧭")
c.tag_filter_sidebar()  # the tag filter doesn't apply here: this page always shows the two O tags
acts_all = c.load_activities()
c.require_data(acts_all)

O_TAGS = ["o_race", "o_training"]
o_all = acts_all[acts_all["tag"].isin(O_TAGS)].sort_values("start", ascending=False)
if o_all.empty:
    st.info("No activities tagged as orienteering race or training yet. Tag them on the **Tags** or "
            "**Activity** page; the orienteering model then finds more of them automatically.")
    st.stop()

# ---------------------------------------------------------------- filters
f = st.columns([2, 2, 4], vertical_alignment="bottom")
kind = f[0].segmented_control("Show", ["All", "Races", "Trainings"], default="All", key="o_kind") or "All"
years = sorted(o_all["start"].dt.year.unique(), reverse=True)
year = f[1].selectbox("Season", ["All years"] + [str(y) for y in years], key="o_year")
o = o_all
if kind != "All":
    o = o[o["tag"] == ("o_race" if kind == "Races" else "o_training")]
if year != "All years":
    o = o[o["start"].dt.year == int(year)]
if o.empty:
    st.info("No orienteering sessions match these filters.")
    st.stop()
with_map = om.saved_ids()

# ---------------------------------------------------------------- totals + monthly volume
k = st.columns(4)
k[0].metric("Sessions", len(o), border=True)
k[1].metric("Hours", f"{o['hours'].sum():.1f}", border=True)
k[2].metric("Races", int((o["tag"] == "o_race").sum()), border=True)
k[3].metric("Maps added", int(o["activity_id"].isin(with_map).sum()), border=True)

insights.render(insights.orienteering(o_all, acts_all, pd.Timestamp.today().normalize()))

monthly = (o.assign(month=o["start"].dt.to_period("M").dt.to_timestamp())
           .groupby(["month", "tag"], as_index=False)["hours"].sum())
fig = go.Figure()
for tag in O_TAGS:
    d = monthly[monthly["tag"] == tag]
    fig.add_bar(x=d["month"], y=d["hours"], name=c.TAG_LABELS[tag], marker_color=c.TAG_COLORS[tag],
                hovertemplate="%{y:.1f} h<extra>" + c.TAG_LABELS[tag] + "</extra>")
c.style_fig(fig, height=240, y_title="hours per month").update_layout(barmode="stack")
fig.update_xaxes(tickformat="%b %Y")
c.show(fig)

# ---------------------------------------------------------------- session list
st.subheader("Sessions")
st.caption("Select a row to see the session and add or view its map.")
o = o.reset_index(drop=True)
table = pd.DataFrame({
    "Date": o["start"].dt.strftime("%a %d %b %Y"),
    "Name": o["name"].fillna(""),
    "Type": o["tag"].map({"o_race": "Race", "o_training": "Training"}),
    "Time": o["duration_s"].map(c.fmt_duration),
    "Avg HR": o["avg_hr"].round(0),
    "Load": o["load"].round(0),
    "Climb (m)": o["elev_gain_m"].round(0),
    "Km": (o["distance_m"] / 1000).round(1),
    "Stopped": (o["stop_frac"] * o["duration_s"]).map(c.fmt_duration),
    "Map": o["activity_id"].isin(with_map).map({True: "✓", False: ""}),
})
event = st.dataframe(
    table, hide_index=True, on_select="rerun", selection_mode="single-row", key="o_table",
    height=min(400, 38 + 35 * len(table)),
    column_config={"Stopped": st.column_config.TextColumn(
        "Stopped", help="Time slower than 1 m/s: map reading, control punching, hesitation.")},
)

qp_id = st.query_params.get("id")
rows = event.selection.rows
if rows:
    aid = int(o.loc[rows[0], "activity_id"])
elif qp_id and qp_id.isdigit() and int(qp_id) in o["activity_id"].values:
    aid = int(qp_id)
else:
    aid = int(o.loc[0, "activity_id"])
if str(aid) != qp_id:
    st.query_params["id"] = str(aid)
a = o.set_index("activity_id").loc[aid]

# ---------------------------------------------------------------- selected session
st.divider()
st.subheader(f"{a['start']:%a %d %b %Y} · {a['name'] or 'Orienteering'}")
m = st.columns(5)
m[0].metric("Time", c.fmt_duration(a["duration_s"]), border=True)
m[1].metric("Avg HR", "–" if pd.isna(a["avg_hr"]) else f"{a['avg_hr']:.0f} bpm", border=True)
m[2].metric("Load", "–" if pd.isna(a["load"]) else f"{a['load']:.0f}", border=True)
m[3].metric("Climb", "–" if pd.isna(a["elev_gain_m"]) else f"{a['elev_gain_m']:.0f} m", border=True)
m[4].metric("Stopped", c.fmt_duration(a["stop_frac"] * a["duration_s"]) if pd.notna(a["stop_frac"]) else "–",
            border=True, help="Time slower than 1 m/s: map reading, control punching, hesitation.")
with st.expander("Rename this session", icon=":material/edit:"):
    c.name_editor(a.rename(aid), "o")
st.markdown(f"[Open HR, laps and zones on the Activity page](/Activity?id={aid})")

samples = c.load_samples(aid)
laps = c.load_laps(aid)
if samples.empty or samples["lat"].isna().all():
    st.info("This session has no GPS track, so a map can't be aligned to it.")
    st.stop()

state_key, edit_key = f"om_{aid}", f"om_edit_{aid}"
saved = om.load_saved(aid)


def new_state(img=None, name=None, dpi=None, map_pts=None, track_pts=None) -> dict:
    return {"img": img, "name": name, "dpi": dpi, "file_id": None, "zoom_at": list(map_pts or [None] * 3),
            "map_pts": map_pts or [None] * 3, "track_pts": track_pts or [None] * 3, "track_names": [None] * 3}


# ---------------------------------------------------------------- overlay (shared by preview and saved view)
def overlay(img, map_pts, track_pts, key: str, dpi: float | None) -> pd.DataFrame:
    mtx = om.solve_transform(track_pts, map_pts)
    pts = samples.dropna(subset=["lat", "lon"]).copy()
    pts["px"], pts["py"] = om.project(mtx, track_pts, pts["lat"], pts["lon"])
    ts = pts.set_index(pd.to_timedelta(pts["t_offset_s"], unit="s"))
    pts["kmh"] = ts["speed_mps"].rolling("15s", min_periods=1).mean().to_numpy() * 3.6
    pts["clock"] = [f"{int(t // 60)}:{int(t % 60):02d}" for t in pts["t_offset_s"]]

    o1, o2 = st.columns([3, 2], vertical_alignment="bottom")
    color_by = o1.segmented_control("Route colour", ["Red", "HR zone", "Speed"], default="Red",
                                    key=f"{key}_color") or "Red"
    show_laps = o2.toggle("Show lap points", value=len(laps) > 1, key=f"{key}_laps",
                          help="Where you pressed lap. If you lap at every control, these are your controls.")

    disp = img.copy()
    disp.thumbnail((2000, 2000))
    fig = go.Figure()
    fig.add_layout_image(source=disp, xref="x", yref="y", x=0, y=0, sizex=img.width, sizey=img.height,
                         sizing="stretch", layer="below")
    custom = list(zip(pts["clock"], pts["hr"].round(0), pts["kmh"].round(1)))
    hover = "%{customdata[0]} · %{customdata[1]} bpm · %{customdata[2]} km/h<extra></extra>"
    fig.add_scatter(x=pts["px"], y=pts["py"], mode="lines", line=dict(color="#e0182d", width=3),
                    opacity=0.85 if color_by == "Red" else 0.35, customdata=custom, hovertemplate=hover,
                    name="Route", showlegend=False)
    if color_by == "HR zone":
        z = c.load_zones(aid)
        lows = z["zone_low_bpm"].tolist() if len(z) == 5 and z["zone_low_bpm"].notna().all() else None
        if lows:
            zone = pts["hr"].apply(lambda h: None if pd.isna(h) else max(0, sum(h >= lo for lo in lows) - 1))
            for i in range(5):
                d = pts[zone == i]
                fig.add_scatter(x=d["px"], y=d["py"], mode="markers", name=f"Z{i + 1}",
                                marker=dict(size=7, color=c.ZONE_COLORS[i], line=dict(width=1, color="white")),
                                customdata=list(zip(d["clock"], d["hr"].round(0), d["kmh"].round(1))),
                                hovertemplate=hover)
        else:
            st.caption("No HR zones stored for this session.")
    elif color_by == "Speed":
        cap = pts["kmh"].quantile(0.95)
        fig.add_scatter(x=pts["px"], y=pts["py"], mode="markers", name="Speed", customdata=custom,
                        hovertemplate=hover, showlegend=False,
                        marker=dict(size=7, color=pts["kmh"].clip(upper=cap), line=dict(width=1, color="white"),
                                    colorscale=[[i / 4, col] for i, col in enumerate(reversed(c.LOAD_RAMP))],
                                    colorbar=dict(title="km/h", thickness=12)))
        st.caption("Darker = slower: look for dark clusters where you stopped or hesitated.")
    if show_laps and len(laps) > 1 and laps["start_offset_s"].notna().all():
        ends = laps.iloc[:-1]
        t = pts["t_offset_s"].to_numpy()
        idx = [abs(t - (r["start_offset_s"] + (r["duration_s"] or 0))).argmin() for _, r in ends.iterrows()]
        lp = pts.iloc[idx]
        fig.add_scatter(x=lp["px"], y=lp["py"], mode="markers+text", name="Lap",
                        text=ends["lap_index"].astype(int).astype(str), textposition="top right",
                        textfont=dict(color="#1f1e1c", size=13),
                        marker=dict(size=13, color="rgba(0,0,0,0)", line=dict(width=2.5, color="#1f1e1c")),
                        hoverinfo="skip", showlegend=False)
    start, end = pts.iloc[0], pts.iloc[-1]
    fig.add_scatter(x=[start["px"]], y=[start["py"]], mode="markers", hoverinfo="skip", showlegend=False,
                    marker=dict(symbol="triangle-up", size=16, color="rgba(0,0,0,0)", line=dict(width=2.5, color="#1f1e1c")))
    fig.add_scatter(x=[end["px"]], y=[end["py"]], mode="markers", hoverinfo="skip", showlegend=False,
                    marker=dict(symbol="circle-open-dot", size=16, color="#1f1e1c", line=dict(width=2.5)))

    pad = 0.08 * max(pts["px"].max() - pts["px"].min(), pts["py"].max() - pts["py"].min())
    xr = [max(0, pts["px"].min() - pad), min(img.width, pts["px"].max() + pad)]
    yr = [min(img.height, pts["py"].max() + pad), max(0, pts["py"].min() - pad)]
    fig.update_xaxes(visible=False, range=xr)
    fig.update_yaxes(visible=False, range=yr, scaleanchor="x")
    height = int(min(800, max(380, 1100 * (yr[0] - yr[1]) / max(1, xr[1] - xr[0]))))  # follow the route's shape
    fig.update_layout(height=height, margin=dict(l=0, r=0, t=30, b=0), dragmode="pan", hovermode="closest",
                      plot_bgcolor=c.SURFACE, paper_bgcolor=c.SURFACE, font=dict(color=c.TEXT),
                      legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="left", x=0))
    st.plotly_chart(fig, width="stretch", key=f"{key}_fig",
                    config={"displaylogo": False, "scrollZoom": True,
                            "modeBarButtonsToRemove": ["lasso2d", "select2d"]})
    st.caption("Scroll to zoom, drag to pan, double-click to reset. Hover the route for time, HR and speed.")

    info = om.alignment_info(mtx, dpi, track_pts, map_pts)
    errs = info["errors_m"]
    bits = [f"error per point {' / '.join(f'{e:.0f}' for e in errs)} m"]
    if info["scale"]:
        bits.append(f"map scale ≈ 1:{round(info['scale'], -2):,.0f}")
    bits.append(f"north rotated {info['rotation_deg']:+.0f}°")
    if max(errs) > 25:
        worst = errs.index(max(errs)) + 1
        st.warning(f"Point {worst} doesn't fit well with the other two ({max(errs):.0f} m off). "
                   "Check that it's the same spot on the map and on the track, or pick an easier one.")
    st.caption("Alignment check: " + " · ".join(bits) + ". GPS is typically 5–15 m off in the forest; "
               "if the route doesn't follow paths and controls, redo the alignment.")
    return pts


# ---------------------------------------------------------------- saved map view
editing = st.session_state.get(edit_key, False)
if saved and not editing:
    st.subheader("Map")
    st.caption(f"{saved['source_name'] or 'Map'} · saved {saved['updated_at']}")
    pts = overlay(saved["img"], saved["map_pts"], saved["track_pts"], key=f"saved_{aid}", dpi=saved["dpi"])
    b = st.columns([1, 1, 1, 1, 2])
    if b[0].button("Prepare PNG download", key=f"prep_{aid}"):
        with st.spinner("Drawing the route on the full-resolution map ..."):
            st.session_state[f"png_{aid}"] = om.png_bytes(om.route_image(saved["img"], pts["px"], pts["py"]))
    if f"png_{aid}" in st.session_state:
        b[1].download_button("Download PNG", st.session_state[f"png_{aid}"], file_name=f"o-map-{a['start']:%Y-%m-%d}.png",
                             mime="image/png", icon=":material/download:", key=f"dl_{aid}")
    if b[2].button("Redo alignment", key=f"redo_{aid}"):
        st.session_state[state_key] = new_state(saved["img"], saved["source_name"], saved["dpi"],
                                                saved["map_pts"], saved["track_pts"])
        st.session_state[edit_key] = True
        st.rerun()
    if b[3].button("Replace map", key=f"replace_{aid}"):
        st.session_state[state_key] = new_state()
        st.session_state[edit_key] = True
        st.rerun()
    if b[4].button("Delete map", key=f"del_{aid}", type="tertiary", icon=":material/delete:"):
        om.delete_map(aid)
        st.session_state.pop(f"png_{aid}", None)
        st.toast("Map deleted")
        st.rerun()
    st.stop()

# ---------------------------------------------------------------- add / align a map
st.subheader("Add the course map" if not saved else "Align the map")
state = st.session_state.setdefault(state_key, new_state())

up = st.file_uploader("Map file (PDF, JPG or PNG)", type=["pdf", "jpg", "jpeg", "png"], key=f"up_{aid}",
                      help="A scan, photo or PDF export of the course. It is stored only on this computer, in data/maps/.")
if up is not None:
    page = 0
    if up.name.lower().endswith(".pdf"):
        n_pages = om.pdf_page_count(up.getvalue())
        if n_pages > 1:
            page = st.number_input("PDF page", 1, n_pages, 1, key=f"pg_{aid}") - 1
    if state["file_id"] != (up.file_id, page):
        with st.spinner("Loading map ..."):
            img, dpi = om.load_map(up.getvalue(), up.name, page)
        state.update(new_state(img, up.name, dpi))
        state["file_id"] = (up.file_id, page)

if state["img"] is None:
    st.caption("After uploading you mark the same 3 spots on the map and on your track, e.g. the start, "
               "a control far away and the finish. The map is then placed under your route.")
    if saved and st.button("Cancel", key=f"cancel_{aid}"):
        st.session_state[edit_key] = False
        st.rerun()
    st.stop()

img = state["img"]
active_key = f"om_active_{aid}"
st.session_state.setdefault(active_key, 0)


def next_missing() -> None:
    for i in range(3):
        if state["map_pts"][i] is None or state["track_pts"][i] is None:
            st.session_state[active_key] = i
            return


def on_map_click(key: str, box: tuple | None) -> None:
    v = st.session_state.get(key)
    if not v:
        return
    i = st.session_state[active_key]
    if box:  # click in the zoomed crop: fine-tune
        x0, y0, size = box
        state["map_pts"][i] = [x0 + v["x"] * size / v["width"], y0 + v["y"] * size / v["height"]]
    else:
        state["map_pts"][i] = [v["x"] * img.width / v["width"], v["y"] * img.height / v["height"]]
        state["zoom_at"][i] = state["map_pts"][i]  # the zoom stays put while fine-tuning


def on_track_click(key: str, geo: dict, shown_w: int) -> None:
    v = st.session_state.get(key)
    if not v:
        return
    i = st.session_state[active_key]
    f_ = shown_w / v["width"]
    lat, lon, name = om.snap_to_track(geo, v["x"] * f_, v["y"] * f_, snap_px=14 * f_)
    state["track_pts"][i], state["track_names"][i] = [lat, lon], name
    if state["map_pts"][i] is not None:
        next_missing()


st.markdown("**For each point:** ① click the spot on the map · ② fine-tune it in the zoom · "
            "③ click the same spot on your track. Start, finish and lap points snap into place.")
done = [state["map_pts"][i] is not None and state["track_pts"][i] is not None for i in range(3)]
st.segmented_control("Point", [0, 1, 2], key=active_key, required=True,
                     format_func=lambda i: f"Point {i + 1}" + (" ✓" if done[i] else ""))
i = st.session_state[active_key]

left, right = st.columns([3, 2])
with left:
    st.caption(f"① Map: click point {i + 1}")
    shown = img.copy()
    shown.thumbnail((1600, 1600))
    f_ = shown.width / img.width
    marked = om.draw_points(shown, [None if p is None else [p[0] * f_, p[1] * f_] for p in state["map_pts"]], i)
    streamlit_image_coordinates(marked, width="stretch", key=f"mapclick_{aid}", image_format="JPEG",
                                jpeg_quality=85, cursor="crosshair",
                                on_click=lambda k=f"mapclick_{aid}": on_map_click(k, None))

    track_img, geo = om.track_canvas(samples, laps)
    trk_marks = []
    for q in state["track_pts"]:
        if q is None:
            trk_marks.append(None)
        else:
            j = int(((geo["lat"] - q[0]) ** 2 + (geo["lon"] - q[1]) ** 2).argmin())
            trk_marks.append([geo["px"][j], geo["py"][j]])
    st.caption(f"③ Track: click point {i + 1} (S = start, F = finish, numbers = lap points)")
    streamlit_image_coordinates(om.draw_points(track_img, trk_marks, i), width="stretch",
                                key=f"trackclick_{aid}", cursor="crosshair",
                                on_click=lambda k=f"trackclick_{aid}", g=geo, w=track_img.width: on_track_click(k, g, w))
    names = [n or ("set" if q else "–") for n, q in zip(state["track_names"], state["track_pts"])]
    st.caption("Track points: " + " · ".join(f"{k + 1}: {n}" for k, n in enumerate(names)))
with right:
    z = state["zoom_at"][i]
    if z is None:
        st.caption("② Zoom: appears after you click the map")
    else:
        st.caption(f"② Zoom: click to place point {i + 1} exactly")
        size = max(160, round(max(img.size) / 10))
        x0 = int(min(max(0, z[0] - size / 2), img.width - size))
        y0 = int(min(max(0, z[1] - size / 2), img.height - size))
        zw = 380
        crop = img.crop((x0, y0, x0 + size, y0 + size)).resize((zw, zw), om.Image.LANCZOS)
        crop = om.draw_points(crop, [None if q is None else [(q[0] - x0) * zw / size, (q[1] - y0) * zw / size]
                                     for q in state["map_pts"]], i, radius=12)
        streamlit_image_coordinates(crop, width=zw, key=f"zoomclick_{aid}", cursor="crosshair",
                                    on_click=lambda k=f"zoomclick_{aid}", b=(x0, y0, size): on_map_click(k, b))

b = st.columns([1, 1, 4])
if b[0].button("Clear points", key=f"clear_{aid}"):
    state.update(map_pts=[None] * 3, track_pts=[None] * 3, track_names=[None] * 3, zoom_at=[None] * 3)
    st.session_state.pop(f"mapclick_{aid}", None)
    st.rerun()
if b[1].button("Cancel", key=f"cancel2_{aid}"):
    st.session_state.pop(state_key, None)
    st.session_state[edit_key] = False
    st.rerun()

if not all(done):
    st.stop()
mp = state["map_pts"]
if min(math.dist(mp[0], mp[1]), math.dist(mp[1], mp[2]), math.dist(mp[0], mp[2])) < 0.05 * max(img.size):
    st.warning("Some points are very close together. Spread them out over the course for a good fit.")
    st.stop()

st.subheader("Preview")
overlay(img, state["map_pts"], state["track_pts"], key="preview", dpi=state["dpi"])
if st.button("Save map", type="primary", icon=":material/save:", key=f"save_{aid}"):
    om.save_map(aid, img, state["name"], state["dpi"], state["map_pts"], state["track_pts"])
    st.session_state.pop(state_key, None)
    st.session_state.pop(f"png_{aid}", None)
    st.session_state[edit_key] = False
    st.toast("Map saved")
    st.rerun()
