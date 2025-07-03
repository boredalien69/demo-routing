import streamlit as st
import pandas as pd
import re
import requests
from sklearn.cluster import KMeans
import folium
from streamlit_folium import st_folium
from geopy.geocoders import Nominatim

st.set_page_config(layout="wide")
st.title("🚛 Cebu Smart Routing – Guided Mode with ORS & Fixes")

REQUIRED_COLUMNS = ["Client", "Address", "Start Time", "End Time", "Time Type", "Order and Weight"]

geolocator = Nominatim(user_agent="cebu-guided-app")

def parse_weight(text):
    match = re.search(r"(\d+(\.\d+)?)\s*kg", str(text).lower())
    return float(match.group(1)) if match else 0.0

# SESSION DEFAULTS
for key in ["df", "failed_indexes", "fixes", "geocoding_done", "geocode_confirmed"]:
    if key not in st.session_state:
        st.session_state[key] = None

# Upload File
uploaded = st.file_uploader("📤 Upload Excel File", type=["xlsx"])
if uploaded:
    df = pd.read_excel(uploaded)
    if list(df.columns) != REQUIRED_COLUMNS:
        st.error("Invalid column headers. Please follow the standard template.")
        st.stop()

    df["Weight (kg)"] = df["Order and Weight"].apply(parse_weight)
    df["Full Address"] = df["Address"] + ", Cebu, Philippines"
    df["Latitude"] = None
    df["Longitude"] = None
    df["Suggested"] = None

    st.session_state.df = df
    st.session_state.failed_indexes = []
    st.session_state.fixes = {}
    st.session_state.geocoding_done = False
    st.session_state.geocode_confirmed = False

# If file is uploaded
if st.session_state.df is not None:
    df = st.session_state.df
    st.subheader("🔑 ORS API Key (for routing)")
    ors_key = st.text_input("Enter your OpenRouteService API Key", type="password")

    st.subheader("🚚 Truck & Driver Setup")
    num_trucks = st.number_input("Number of Trucks", 1, 10, 3)
    assign_drivers = st.checkbox("Assign driver names?")
    drivers = {}

    if assign_drivers:
        for i in range(num_trucks):
            drivers[i] = st.text_input(f"Driver for Truck {i+1}", key=f"driver_{i}")
    else:
        drivers = {i: f"Truck {i+1}" for i in range(num_trucks)}

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
        st.session_state.geocoding_done = True
        st.session_state.geocode_confirmed = False

# Fix suggestions
if st.session_state.geocoding_done and not st.session_state.geocode_confirmed:
    df = st.session_state.df
    failed = st.session_state.failed_indexes

    if not failed:
        st.success("✅ All addresses geocoded successfully.")
        st.session_state.geocode_confirmed = True
    else:
        st.warning("⚠️ Some addresses could not be located. Fix them below:")
        for idx in failed:
            row = df.loc[idx]
            suggested = row["Suggested"]
            st.markdown(f"**{row['Client']}** — `{row['Address']}`")
            if suggested:
                choice = st.selectbox(
                    f"Suggested for {row['Client']}",
                    [row["Address"], suggested],
                    key=f"dropdown_{idx}"
                )
                st.session_state.fixes[idx] = choice
            else:
                manual = st.text_input(
                    f"Enter corrected address for {row['Client']}",
                    key=f"manual_{idx}"
                )
                if manual:
                    st.session_state.fixes[idx] = manual

        if st.button("✅ Confirm Fixed Addresses"):
            still_failed = []
            for idx, new_addr in st.session_state.fixes.items():
                try:
                    loc = geolocator.geocode(new_addr + ", Cebu, Philippines", timeout=10)
                    if loc:
                        df.at[idx, "Latitude"] = loc.latitude
                        df.at[idx, "Longitude"] = loc.longitude
                        df.at[idx, "Full Address"] = new_addr
                    else:
                        still_failed.append(idx)
                except:
                    still_failed.append(idx)
            st.session_state.df = df
            st.session_state.failed_indexes = still_failed
            if not still_failed:
                st.success("✅ All addresses fixed and geocoded.")
                st.session_state.geocode_confirmed = True
            else:
                st.warning("Some addresses still could not be located.")

# Optimization (only if geocode fully confirmed)
if st.session_state.geocode_confirmed:
    df = st.session_state.df
    st.subheader("📦 Optimize Routes")

    dispatch = st.text_input("Dispatch Starting Point", "S Jayme St, Mandaue, Cebu")
    if st.button("🚀 Start Optimization"):
        try:
            start = geolocator.geocode(dispatch + ", Cebu, Philippines")
            if not start:
                st.error("❌ Dispatch address not found.")
                st.stop()
            start_coords = [start.longitude, start.latitude]
            valid = df.dropna(subset=["Latitude", "Longitude"]).copy()

            kmeans = KMeans(n_clusters=num_trucks, random_state=42)
            valid["Assigned Truck"] = kmeans.fit_predict(valid[["Latitude", "Longitude"]])
            valid["Driver"] = valid["Assigned Truck"].map(drivers)

            # Map rendering
            st.subheader("🗺️ Visual Map")
            m = folium.Map(location=[start.latitude, start.longitude], zoom_start=11)
            folium.Marker([start.latitude, start.longitude], tooltip="Dispatch", icon=folium.Icon(color="black")).add_to(m)

            for _, row in valid.iterrows():
                folium.Marker(
                    [row["Latitude"], row["Longitude"]],
                    popup=f"{row['Client']}<br>Driver: {row['Driver']}"
                ).add_to(m)

            st_folium(m, width=1000, height=600)

            st.download_button("📥 Download Optimized Routes", data=valid.to_excel(index=False), file_name="Optimized_Routes.xlsx")

        except Exception as e:
            st.error(f"❌ Routing failed: {e}")
