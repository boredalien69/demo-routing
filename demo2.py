import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
from sklearn.cluster import KMeans
import requests

# === CONFIG ===
ORS_API_KEY = "5b3ce3597851110001cf6248d0ef335bf9ea4cf3a10b8ed39273e514"  # <-- Replace this with your actual ORS API Key

st.set_page_config(page_title="RoutingTrial1", layout="wide")
st.title("🚚 RoutingTrial1: Step-by-Step Delivery Optimizer")

# === INIT SESSION STATE ===
st.session_state.setdefault("stage", "upload")
st.session_state.setdefault("geocode_attempted", False)
st.session_state.setdefault("optimization_started", False)

# === HELPERS ===
def geocode_address(address):
    url = f"https://api.openrouteservice.org/geocode/search"
    params = {"api_key": ORS_API_KEY, "text": address}
    headers = {"Accept": "application/json"}
    try:
        response = requests.get(url, params=params, headers=headers, timeout=10)
        if response.status_code == 200:
            data = response.json()
            if data["features"]:
                coords = data["features"][0]["geometry"]["coordinates"]
                resolved = data["features"][0]["properties"]["label"]
                return coords[1], coords[0], resolved
    except:
        pass
    return None, None, None

def get_suggestions(address):
    try:
        url = f"https://nominatim.openstreetmap.org/search"
        params = {
            "q": address,
            "format": "json",
            "countrycodes": "ph",
            "limit": 5,
            "viewbox": "123.5,11.6,124.2,10.1",  # Rough bounding box for Cebu Province
            "bounded": 1  # Only results within the viewbox
        }
        response = requests.get(url, params=params, headers={"User-Agent": "RoutingApp"})
        return [r["display_name"] for r in response.json()]
    except:
        return []


# === STAGE 1: UPLOAD FILE ===
if st.session_state.stage == "upload":
    st.header("📤 Step 1: Upload Delivery File")
    uploaded_file = st.file_uploader("Upload Excel file", type=["xlsx"])
    if uploaded_file:
        df = pd.read_excel(uploaded_file)
        if "Address" not in df.columns or "Client" not in df.columns:
            st.error("❌ Excel file must contain at least 'Client' and 'Address' columns.")
        else:
            df["Latitude"] = None
            df["Longitude"] = None
            df["Resolved Address"] = None
            df["Suggestions"] = None
            st.session_state.df = df
            st.session_state.stage = "geocode"
            st.rerun()

# === STAGE 2: GEOCODE ===
elif st.session_state.stage == "geocode":
    st.header("📍 Step 2: Geocoding Addresses")
    df = st.session_state.df.copy()

    if not st.session_state["geocode_attempted"]:
        for i, row in df.iterrows():
            lat, lon, resolved = geocode_address(row["Address"])
            if lat:
                df.at[i, "Latitude"] = lat
                df.at[i, "Longitude"] = lon
                df.at[i, "Resolved Address"] = resolved
            else:
                df.at[i, "Suggestions"] = get_suggestions(row["Address"])
        st.session_state.df = df
        st.session_state["geocode_attempted"] = True
        st.rerun()

    df = st.session_state.df
    unresolved = df[df["Latitude"].isna()]

    if not unresolved.empty:
        st.warning(f"{len(unresolved)} address(es) could not be located.")

        for i, row in unresolved.iterrows():
            st.markdown(f"**{row['Client']}** - `{row['Address']}`")
            suggestions = row["Suggestions"] if isinstance(row["Suggestions"], list) else []
            choice = st.selectbox("Pick suggestion or manually fix:",
                                  options=[""] + suggestions,
                                  key=f"suggest_{i}")
            manual = st.text_input("Manual input (optional)", key=f"manual_{i}")
            if st.button(f"Confirm Fix for {row['Client']}", key=f"fixbtn_{i}"):
                fixed = choice if choice else manual
                if fixed:
                    lat, lon, resolved = geocode_address(fixed)
                    if lat:
                        df.at[i, "Latitude"] = lat
                        df.at[i, "Longitude"] = lon
                        df.at[i, "Resolved Address"] = resolved
                        df.at[i, "Suggestions"] = None
                        st.success(f"✅ Address for {row['Client']} fixed.")
                        st.session_state.df = df
                        st.rerun()
                    else:
                        st.error("❌ Unable to locate the fixed address.")
    else:
        st.success("✅ All addresses geocoded.")
        st.session_state.df = df
        st.session_state.stage = "driver_info"
        st.rerun()

# === STAGE 3: DRIVER INFO ===
elif st.session_state.stage == "driver_info":
    st.header("👥 Step 3: Enter Truck and Driver Info")
    num_trucks = st.number_input("Number of Trucks", min_value=1, max_value=10, value=3)
    st.session_state.num_trucks = num_trucks
    driver_names = []
    for i in range(num_trucks):
        name = st.text_input(f"Name of Driver {i+1}", key=f"driver_{i}")
        driver_names.append(name if name else f"Driver {i+1}")
    st.session_state.drivers = driver_names

    if st.button("Proceed to Optimization"):
        st.session_state.stage = "optimize"
        st.rerun()

# === STAGE 4: OPTIMIZATION ===
elif st.session_state.stage == "optimize":
    st.header("🧠 Step 4: Route Optimization")
    if st.button("🚀 Start Optimization"):
        df = st.session_state.df
        valid = df[df["Latitude"].notna() & df["Longitude"].notna()].copy()
        if valid.empty:
            st.error("No valid delivery addresses found.")
            st.stop()

        kmeans = KMeans(n_clusters=st.session_state.num_trucks, random_state=1)
        valid["Assigned Truck"] = kmeans.fit_predict(valid[["Latitude", "Longitude"]])
        valid["Driver"] = valid["Assigned Truck"].map(lambda i: st.session_state.drivers[i])
        st.session_state.optimized = valid
        st.session_state.stage = "results"
        st.rerun()

# === STAGE 5: SHOW RESULTS ===
elif st.session_state.stage == "results":
    st.header("📍 Step 5: Map & Final Output")
    df = st.session_state.optimized
    dispatch_lat, dispatch_lon = 10.3284, 123.9366

    m = folium.Map(location=[dispatch_lat, dispatch_lon], zoom_start=11)
    folium.Marker([dispatch_lat, dispatch_lon],
                  icon=folium.Icon(color="black", icon="home"),
                  tooltip="Dispatch Point").add_to(m)

    for _, row in df.iterrows():
        folium.Marker([row["Latitude"], row["Longitude"]],
                      popup=f"{row['Client']}<br>Driver: {row['Driver']}").add_to(m)

    st_data = st_folium(m, width=1000, height=600)
    st.download_button("📥 Download Final Routes", data=df.to_csv(index=False),
                       file_name="OptimizedRoutes.csv")
