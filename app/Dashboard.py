"""Dashboard entry point: `streamlit run app/Dashboard.py`. Defines the page menu; Today is the start page."""

import streamlit as st

pages = [
    st.Page("pages/0_Today.py", title="Today", icon=":material/today:", default=True),
    st.Page("Overview.py", title="Overview", icon=":material/dashboard:", url_path="Overview"),
    st.Page("pages/1_Calendar.py", title="Calendar", icon=":material/calendar_month:", url_path="Calendar"),
    st.Page("pages/2_Intensity.py", title="Intensity", icon=":material/favorite:", url_path="Intensity"),
    st.Page("pages/3_Recovery.py", title="Recovery", icon=":material/bedtime:", url_path="Recovery"),
    st.Page("pages/4_Activity.py", title="Activity", icon=":material/directions_run:", url_path="Activity"),
    st.Page("pages/5_Tags.py", title="Tags", icon=":material/sell:", url_path="Tags"),
    st.Page("pages/6_Settings.py", title="Settings", icon=":material/settings:", url_path="Settings"),
]
st.navigation(pages).run()
