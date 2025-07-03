import streamlit as st
import pandas as pd
import re
from sklearn.cluster import KMeans
import folium
from streamlit_folium import st_folium
from geopy.geocoders import Nominatim

st.set_page_config(layout="wide")
st.title("🚛 Cebu Smart Routing – Guided Mode (No Loop)")

REQUIRED_COLUMNS = ["Client", "Address", "Start Time", "End Time", "Time Type", "Order and Weight"]
geolocator = Nominatim(user_agent="cebu-routing-guided")

def parse_weight(text):
    match = re.search(r"(\d+(\.\d+)?)\s*kg", str(text).lower())
    return float(match.group(1)) if match else 0.0

# Session State Init
if "stage" not in st.session_state:
    st.session_state.stage = "upload"
if "df" not in st.session_state:
    st.session_state.df = None
if "failed_indexes" not in st.session_state:
    st.session_state.failed_indexes = []
if "num_trucks" not in st.session_state:
    st.session_state.num_trucks = 3
if "drivers" not in st.session_state:
    st.session_state.drivers = {}

# Upload Step
if st.session_state.stage == "upload":
    uploaded = st.file_uploader("📤 Upload Excel File", type=["xlsx"])
    if uploaded:
        df = pd.read_excel(uploaded)
        if list(df.columns) != REQUIRED_COLUMNS:
            st.error("❌ Incorrect columns. Please use the correct Excel template.")
            st.stop()
        df["Weight (kg)"] = df["Order and Weight"].apply(parse_weight)
        df["Full Address"] = df["Address"] + ", Cebu, Philippines"
        df["Latitude"] = None
        df["Longitude"] = None
        df["Suggested"] = None

        st.session_state.df = df
        st.session_state.stage = "truck"

# Truck Setup Step
if st.session_state.stage == "truck":
    df = st.session_state.df
    st.subheader("🚚 Truck & Driver Assignment")
    st.session_state.num_trucks = st.number_input("Number of Trucks", 1, 10, 3)
    assign_names = st.checkbox("Assign driver names?")
    st.session_state.drivers = {}
    for i in range(st.session_state.num_trucks):
        if assign_names:
            name = st.text_input(f"Driver name for Truck {i+1}", key=f"driver_{i}")
            st.session_state.drivers[i] = name if name else f"Truck {i+1}"
        else:
            st.session_state.drivers[i] = f"Truck {i+1}"

    if st.button("🔍 Check All Addresses"):
        failed = []
        for idx, row in df.iterrows():
            try:
                loc = geolocator.geocode(row["Full Address"], timeout=10)
                if loc:
                    df.at[idx, "Latitude"] = loc.latitude
                    df.at[idx, "Longitude"] = loc.longitude
                else:
                    alt = geolocator.geocode(row["Address"], timeout=10)
                    if alt:
                        df.at[idx, "Suggested"] = alt.address
                    failed.append(idx)
            except:
                failed.append(idx)

        st.session_state.df = df
        st.session_state.failed_indexes = failed
        if not failed:
            st.success("✅ All addresses found. You may proceed to optimization.")
            st.session_state.stage = "optimize"
        else:
            st.warning("⚠️ Some addresses need manual fixing.")
            st.session_state.stage = "fix"

# Fix Step
if st.session_state.stage == "fix":
    df = st.session_state.df
    failed = st.session_state.failed_indexes
    st.warning("⚠️ Address fix needed for these clients:")

    for idx in failed:
        row = df.loc[idx]
        suggestion = row["Suggested"]
        st.markdown(f"**{row['Client']}** — `{row['Address']}`")
        if suggestion:
            st.selectbox(
                f"Suggested for {row['Client']}",
                [row["Address"], suggestion],
                key=f"dropdown_{idx}"
            )
        else:
            st.text_input(
                f"Enter fixed address for {row['Client']}",
                key=f"manual_{idx}"
            )

    if st.button("✅ Confirm Fixed Addresses"):
        still_failed = []
        for idx in failed:
            selected = st.session_state.get(f"dropdown_{idx}") or st.session_state.get(f"manual_{idx}")
            if selected:
                try:
                    if "philippines" not in selected.lower():
                        selected += ", Cebu, Philippines"
                    loc = geolocator.geocode(selected, timeout=10)
                    if loc:
                        df.at[idx, "Latitude"] = loc.latitude
                        df.at[idx, "Longitude"] = loc.longitude
                        df.at[idx, "Full Address"] = selected
                    else:
                        still_failed.append(idx)
                except:
                    still_failed.append(idx)
            else:
                still_failed.append(idx)

        st.session_state.df = df
        if not still_failed:
            st.success("✅ All addresses geocoded successfully.")
            st.session_state.stage = "optimize"
        else:
            st.warning("❗ Still unable to locate the following addresses:")
            for idx in still_failed:
                st.markdown(f"- ❌ `{df.loc[idx, 'Full Address']}`")
            st.session_state.failed_indexes = still_failed

# Optimization Step
if st.session_state.stage == "optimize":
    df = st.session_state.df
    st.subheader("📦 Route Optimization")
    dispatch = st.text_input("Dispatch Starting Point", "S Jayme St, Mandaue, Cebu")
    if st.button("🚀 Start Optimization"):
        try:
            start = geolocator.geocode(dispatch + ", Cebu, Philippines")
            if not start:
                st.error("❌ Dispatch address not found.")
                st.stop()
            valid = df.dropna(subset=["Latitude", "Longitude"]).copy()
            kmeans = KMeans(n_clusters=st.session_state.num_trucks, random_state=42)
            valid["Assigned Truck"] = kmeans.fit_predict(valid[["Latitude", "Longitude"]])
            valid["Driver"] = valid["Assigned Truck"].map(st.session_state.drivers)

            st.subheader("🗺️ Route Map")
            m = folium.Map(location=[start.latitude, start.longitude], zoom_start=11)
            folium.Marker(
                [start.latitude, start.longitude],
                tooltip="Dispatch Point",
                icon=folium.Icon(color="black")
            ).add_to(m)

            for _, row in valid.iterrows():
                folium.Marker(
                    [row["Latitude"], row["Longitude"]],
                    popup=f"{row['Client']}<br>Driver: {row['Driver']}"
                ).add_to(m)

            st_folium(m, width=1000, height=600)
            st.download_button("📥 Download Routes", data=valid.to_excel(index=False), file_name="OptimizedRoutes.xlsx")
        except Exception as e:
            st.error(f"❌ Optimization failed: {e}")
