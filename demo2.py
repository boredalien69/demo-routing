import streamlit as st
import pandas as pd
import re
import requests
from sklearn.cluster import KMeans
import folium
from streamlit_folium import st_folium
from geopy.geocoders import Nominatim

# ========== CONFIG ==========
ORS_API_KEY = "5b3ce3597851110001cf6248d0ef335bf9ea4cf3a10b8ed39273e514"  # <--- Replace with your actual ORS key
MAX_TRUCKS = 10
st.set_page_config(layout="wide")
st.title("🚛 Cebu Smart Routing – Guided Mode (ORS + Nominatim)")

REQUIRED_COLUMNS = ["Client", "Address", "Start Time", "End Time", "Time Type", "Order and Weight"]
geolocator = Nominatim(user_agent="cebu-routing-fallback")

# ========== GEOCODING FUNCTIONS ==========
def ors_geocode(address):
    url = "https://api.openrouteservice.org/geocode/search"
    headers = {"Authorization": ORS_API_KEY}
    params = {"text": address, "boundary.country": "PHL", "size": 1}
    try:
        response = requests.get(url, headers=headers, params=params, timeout=10)
        data = response.json()
        coords = data["features"][0]["geometry"]["coordinates"]
        return coords[1], coords[0]  # lat, lon
    except:
        return None, None

def fallback_geocode(address):
    try:
        loc = geolocator.geocode(address, timeout=10)
        return (loc.latitude, loc.longitude) if loc else (None, None)
    except:
        return None, None

def geocode_address(full_address):
    lat, lon = ors_geocode(full_address)
    if lat is None:
        lat, lon = fallback_geocode(full_address)
    return lat, lon

def parse_weight(text):
    match = re.search(r"(\d+(\.\d+)?)\s*kg", str(text).lower())
    return float(match.group(1)) if match else 0.0

# ========== SESSION INIT ==========
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

# ========== STAGE: UPLOAD ==========
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

# ========== STAGE: TRUCK SETUP ==========
if st.session_state.stage == "truck":
    df = st.session_state.df
    st.subheader("🚚 Truck & Driver Assignment")
    st.session_state.num_trucks = st.number_input("Number of Trucks", 1, MAX_TRUCKS, 3)
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
            lat, lon = geocode_address(row["Full Address"])
            if lat is not None:
                df.at[idx, "Latitude"] = lat
                df.at[idx, "Longitude"] = lon
            else:
                alt_lat, alt_lon = geocode_address(row["Address"])
                if alt_lat:
                    df.at[idx, "Suggested"] = row["Address"]
                failed.append(idx)

        st.session_state.df = df
        st.session_state.failed_indexes = failed
        if not failed:
            st.success("✅ All addresses found. You may proceed to optimization.")
            st.session_state.stage = "optimize"
        else:
            st.warning("⚠️ Some addresses need manual fixing.")
            st.session_state.stage = "fix"

# ========== STAGE: FIX ==========
if st.session_state.stage == "fix":
    df = st.session_state.df
    failed = st.session_state.failed_indexes
    st.warning("⚠️ Address fix needed for these clients:")
    for idx in failed:
        row = df.loc[idx]
        st.markdown(f"**{row['Client']}** — `{row['Address']}`")
        suggestion = row["Suggested"]
        if suggestion:
            st.selectbox(f"Suggested for {row['Client']}", [row["Address"], suggestion], key=f"dropdown_{idx}")
        else:
            st.text_input(f"Enter fixed address for {row['Client']}", key=f"manual_{idx}")

    if st.button("✅ Confirm Fixed Addresses"):
        still_failed = []
        for idx in failed:
            selected = st.session_state.get(f"dropdown_{idx}") or st.session_state.get(f"manual_{idx}")
            if selected:
                lat, lon = geocode_address(selected)
                if lat:
                    df.at[idx, "Latitude"] = lat
                    df.at[idx, "Longitude"] = lon
                    df.at[idx, "Full Address"] = selected
                else:
                    still_failed.append(idx)
            else:
                still_failed.append(idx)

        st.session_state.df = df
        if not still_failed:
            st.success("✅ All addresses geocoded successfully.")
            st.session_state.stage = "optimize"
        else:
            st.warning("❗ Still unable to locate some addresses:")
            for idx in still_failed:
                st.markdown(f"- ❌ `{df.loc[idx, 'Full Address']}`")
            st.session_state.failed_indexes = still_failed

# ========== STAGE: OPTIMIZATION ==========
if st.session_state.stage == "optimize":
    df = st.session_state.df
    st.subheader("📦 Route Optimization")
    dispatch = st.text_input("Dispatch Starting Point", "S Jayme St, Mandaue, Cebu")
    if st.button("🚀 Start Optimization"):
        lat, lon = geocode_address(dispatch)
        if not lat:
            st.error("❌ Dispatch address not found.")
            st.stop()

        try:
            valid = df.dropna(subset=["Latitude", "Longitude"]).copy()
            kmeans = KMeans(n_clusters=st.session_state.num_trucks, random_state=42)
            valid["Assigned Truck"] = kmeans.fit_predict(valid[["Latitude", "Longitude"]])
            valid["Driver"] = valid["Assigned Truck"].map(st.session_state.drivers)

            st.subheader("🗺️ Route Map")
            m = folium.Map(location=[lat, lon], zoom_start=11)
            folium.Marker([lat, lon], tooltip="Dispatch Point", icon=folium.Icon(color="black")).add_to(m)
            for _, row in valid.iterrows():
                folium.Marker([row["Latitude"], row["Longitude"]],
                              popup=f"{row['Client']}<br>Driver: {row['Driver']}").add_to(m)
            st_folium(m, width=1000, height=600)

            st.download_button("📥 Download Routes", data=valid.to_excel(index=False), file_name="OptimizedRoutes.xlsx")
        except Exception as e:
            st.error(f"❌ Optimization failed: {e}")
