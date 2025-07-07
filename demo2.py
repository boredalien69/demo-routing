import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
from sklearn.cluster import KMeans
import requests

# === CONFIG ===
ORS_API_KEY = "YOUR_ORS_API_KEY"  # Replace with your real key

st.set_page_config(page_title="RoutingTrial2", layout="wide")
st.title("🚚 RoutingTrial2: Delivery Route Optimizer")

# === INIT SESSION STATE ===
st.session_state.setdefault("stage", "upload")
st.session_state.setdefault("geocode_attempted", False)
st.session_state.setdefault("confirmed", [])
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
            "viewbox": "123.5,11.6,124.2,10.1",
            "bounded": 1
        }
        response = requests.get(url, params=params, headers={"User-Agent": "RoutingApp"})
        return [r["display_name"] for r in response.json()]
    except:
        return []

# === STAGE 1: UPLOAD ===
if st.session_state.stage == "upload":
    st.header("📤 Step 1: Upload Excel File")
    uploaded_file = st.file_uploader("Upload delivery file (.xlsx)", type=["xlsx"])
    if uploaded_file:
        df = pd.read_excel(uploaded_file)
        if "Client" not in df.columns or "Address" not in df.columns:
            st.error("❌ Required columns: 'Client' and 'Address'")
        else:
            df["Latitude"] = None
            df["Longitude"] = None
            df["Resolved Address"] = None
            df["Suggestions"] = None
            st.session_state.df = df
            st.session_state.stage = "geocode"
            st.rerun()

# === STAGE 2: GEOCODING + CONFIRMATION ===
elif st.session_state.stage == "geocode":
    st.header("📍 Step 2: Confirm or Fix All Addresses")
    df = st.session_state.df

    if not st.session_state["geocode_attempted"]:
        confirmed_flags = []
        for i, row in df.iterrows():
            lat, lon, resolved = geocode_address(row["Address"])
            if lat:
                df.at[i, "Latitude"] = lat
                df.at[i, "Longitude"] = lon
                df.at[i, "Resolved Address"] = resolved
            suggestions = get_suggestions(row["Address"])
            df.at[i, "Suggestions"] = suggestions
            confirmed_flags.append(False)
        st.session_state.df = df
        st.session_state["confirmed"] = confirmed_flags
        st.session_state["geocode_attempted"] = True
        st.rerun()

    df = st.session_state.df
    confirmed_flags = st.session_state["confirmed"]
    all_confirmed = True

    for i, row in df.iterrows():
        if pd.isna(row["Latitude"]):
            st.warning(f"❌ `{row['Client']}` - `{row['Address']}` not found")
            suggestions = row["Suggestions"] if isinstance(row["Suggestions"], list) else []
            choice = st.selectbox(f"Suggestions for {row['Client']}", [""] + suggestions, key=f"suggest_{i}")
            manual = st.text_input("Manual address override", key=f"manual_{i}")
            if st.button(f"Confirm Fix for {row['Client']}", key=f"fixbtn_{i}"):
                fixed = choice if choice else manual
                lat, lon, resolved = geocode_address(fixed)
                if lat:
                    df.at[i, "Latitude"] = lat
                    df.at[i, "Longitude"] = lon
                    df.at[i, "Resolved Address"] = resolved
                    confirmed_flags[i] = True
                    st.session_state.df = df
                    st.session_state["confirmed"] = confirmed_flags
                    st.success("✅ Fixed.")
                    st.rerun()
        else:
            st.info(f"📍 `{row['Client']}` resolved as: `{row['Resolved Address']}`")
            confirm = st.checkbox(f"Confirm this address for {row['Client']}", key=f"confirm_{i}")
            confirmed_flags[i] = confirm
            if not confirm:
                all_confirmed = False

    if all(confirmed_flags) and all_confirmed:
        st.success("✅ All addresses confirmed.")
        st.session_state.df = df
        st.session_state.stage = "driver_info"
        st.rerun()

# === STAGE 3: DRIVER INFO ===
elif st.session_state.stage == "driver_info":
    st.header("👤 Step 3: Enter Drivers and Trucks")
    num_trucks = st.number_input("Number of trucks", 1, 10, 3)
    driver_names = []
    for i in range(num_trucks):
        name = st.text_input(f"Driver {i+1} name", key=f"driver_{i}")
        driver_names.append(name if name else f"Driver {i+1}")
    st.session_state.num_trucks = num_trucks
    st.session_state.drivers = driver_names

    if st.button("Proceed to Optimization"):
        st.session_state.stage = "optimize"
        st.rerun()

# === STAGE 4: OPTIMIZE ===
elif st.session_state.stage == "optimize":
    st.header("📦 Step 4: Optimize Routes")
    if st.button("🚀 Start Optimization"):
        df = st.session_state.df
        valid = df[df["Latitude"].notna() & df["Longitude"].notna()].copy()
        if valid.empty:
            st.error("❌ No valid coordinates.")
            st.stop()
        kmeans = KMeans(n_clusters=st.session_state.num_trucks, random_state=1)
        valid["Assigned Truck"] = kmeans.fit_predict(valid[["Latitude", "Longitude"]])
        valid["Driver"] = valid["Assigned Truck"].map(lambda i: st.session_state.drivers[i])
        st.session_state.optimized = valid
        st.session_state.stage = "results"
        st.rerun()

# === STAGE 5: RESULTS ===
elif st.session_state.stage == "results":
    st.header("📍 Step 5: View Map and Download Output")
    df = st.session_state.optimized
    dispatch_lat, dispatch_lon = 10.3284, 123.9366  # Mandaue plant

    m = folium.Map(location=[dispatch_lat, dispatch_lon], zoom_start=11)
    folium.Marker([dispatch_lat, dispatch_lon],
                  icon=folium.Icon(color="black", icon="home"),
                  tooltip="Dispatch Point").add_to(m)

    for _, row in df.iterrows():
        folium.Marker([row["Latitude"], row["Longitude"]],
                      popup=f"{row['Client']}<br>Driver: {row['Driver']}").add_to(m)

    st_data = st_folium(m, width=1000, height=600)
    st.download_button("📥 Download Final Routes", data=df.to_csv(index=False),
                       file_name="RoutingTrial2_Output.csv")
