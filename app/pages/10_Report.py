"""Report: a weekly or monthly summary to download as one HTML file (print it to PDF from the browser)."""

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

import common as c
import notes as nt
import planning as pl
import report

c.setup_page("Report", "📄")
c.sidebar()  # the report always uses all activities
acts = c.load_activities()
c.require_data(acts)
today = pd.Timestamp.today().normalize()

f = st.columns([1, 2, 3], vertical_alignment="bottom")
kind = f[0].segmented_control("Period", list(report.KINDS), default="week", format_func=report.KINDS.get,
                              key="report_kind") or "week"
starts = report.period_starts(kind, acts["day"].min(), today)
start = f[1].selectbox(report.KINDS[kind], starts, key=f"report_start_{kind}",
                       format_func=lambda s: report.title(kind, *report.period_bounds(kind, s))
                       + (" (so far)" if report.period_bounds(kind, s)[1] >= today else ""))

labels, colors, _ = c.tag_maps("light")  # the file is always light, for printing
doc = report.build(kind, start, acts, c.load_daily(), nt.load_notes(), pl.load_races(), pl.load_plans(),
                   labels, colors)
f[2].download_button("Download report (.html)", doc, file_name=f"training-{kind}-{start:%Y-%m-%d}.html",
                     mime="text/html", icon=":material/download:", type="primary")
st.caption("The file has everything in it (no internet needed). To make a PDF, open it in your browser and print "
           "to PDF. It always uses all activities, whatever tags you hide on the Settings page.")
components.html(doc, height=900, scrolling=True)  # an iframe, so the report's styles don't touch the app
