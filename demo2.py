import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
from sklearn.cluster import KMeans
import requests
from io import BytesIO

# ========== CONFIG ==========
ORS_API_KEY = "YOUR_ORS_API_KEY"

st.set_page_config(page_title="Cebu Delivery Optimizer", layout="wide")
st.title("🚚 Cebu Delivery Route Optimizer")

# ========== COMPATIBLE RERUN ==========
try:
    rerun = st.rerun
except AttributeError:
    rerun = st.experimental_rerun

# ========== HELPERS ==========
def geocode_address(address):
    headers = {"Authorization": ORS_API_KEY}
    url = f"https://api.openrouteservice.org/geocode/search?api_key={ORS_API_KEY}&text={address}"
    response = requests.get(url, headers=headers)
    if response.status_code == 200 and response.json().get("features"):
        coords = response.json()["features"][0]["geometry"]["coordinates"]
        full_address = response.json()["features"][0]["properties"]["label"]
        return coords[1], coords[0], full_address
    return None, None, None

def get_suggestions(address):
    try:
        url = f"https://nominatim.openstreetmap.org/search?q={address}&format=json"
        response = requests.get(url, headers={"User-Agent": "RoutingApp"})
        return [r["display_name"] for r in response.json()]
    except:
        return []

# ========== STAGE 1: UPLOAD ==========
if "stage" not in st.session_state:
    st.session_state.stage = "upload"

if st.session_state.stage == "upload":
    uploaded_file = st.file_uploader("📤 Upload Excel File", type=["xlsx"])
    if uploaded_file:
        df = pd.read_excel(uploaded_file)
        st.session_state.df = df
        st.session_state.stage = "geocode"
        rerun()

# ========== STAGE 2: GEOCODE ==========
if st.session_state.stage == "geocode":
    st.subheader("📍 Step 1: Geocoding Client Addresses")
    df = st.session_state.df.copy()

    if "geocode_attempted" not in st.session_state:
        df["Latitude"], df["Longitude"], df["Resolved Address"] = None, None, None
        df["Suggestions"], df["Manual Fix"] = None, "", ""
        for i, row in df.iterrows():
            lat, lon, resolved = geocode_address(row["Address"])
            if lat:
                df.at[i, "Latitude"] = lat
                df.at[i, "Longitude"] = lon
                df.at[i, "Resolved Address"] = resolved
            else:
                suggestions = get_suggestions(row["Address"])
                df.at[i, "Suggestions"] = suggestions
        st.session_state.df = df
        st.session_state.geocode_attempted = True
        rerun()

    df = st.session_state.df
    not_found_df = df[df["Latitude"].isna()]

    if not not_found_df.empty:
        st.warning(f"{len(not_found_df)} address(es) could not be located. Please review below:")

        for i, row in not_found_df.iterrows():
            st.markdown(f"**Client:** {row['Client']}")
            if row["Suggestions"]:
                chosen = st.selectbox(f"Choose suggestion for `{row['Client']}`",
                                      options=[""] + row["Suggestions"],
                                      key=f"dropdown_{i}")
                st.session_state[f"suggestion_{i}"] = chosen
            manual = st.text_input(f"Or manually fix `{row['Client']}`",
                                   value=row.get("Manual Fix", ""), key=f"manual_{i}")
            st.session_state[f"manualfix_{i}"] = manual

        if st.button("✅ Confirm Fixed Addresses"):
            for i in not_found_df.index:
                fixed = st.session_state.get(f"suggestion_{i}") or st.session_state.get(f"manualfix_{i}")
                if fixed:
                    lat, lon, resolved = geocode_address(fixed)
                    if lat:
                        df.at[i, "Latitude"] = lat
                        df.at[i, "Longitude"] = lon
                        df.at[i, "Resolved Address"] = resolved
            st.session_state.df = df
            if df["Latitude"].isna().sum() == 0:
                st.success("✅ All addresses successfully located!")
                st.session_state.stage = "driver_info"
                rerun()
            else:
                st.warning("Some addresses are still missing. Please recheck.")
    else:
        st.success("✅ All addresses already geocoded.")
        st.session_state.stage = "driver_info"
        rerun()

# ========== STAGE 3: DRIVER INFO ==========
if st.session_state.stage == "driver_info":
    df = st.session_state.df
    st.subheader("👥 Step 2: Enter Number of Trucks and Drivers")

    num_trucks = st.number_input("Number of Trucks", min_value=1, max_value=10, value=3, step=1)
    st.session_state.num_trucks = num_trucks

    drivers = []
    for i in range(num_trucks):
        name = st.text_input(f"Driver {i+1} Name", key=f"driver_{i}")
        drivers.append(name if name else f"Driver {i+1}")
    st.session_state.drivers = drivers

    if st.button("Proceed to Optimization"):
        st.session_state.stage = "optimize"
        rerun()

# ========== STAGE 4: OPTIMIZATION ==========
if st.session_state.stage == "optimize":
    df = st.session_state.df
    st.subheader("📦 Step 3: Route Optimization")

    dispatch_label = st.text_input("Dispatch Location Name (for display only)",
                                   "Main Plant - S Jayme St, Mandaue")
    dispatch_lat = 10.3284
    dispatch_lon = 123.9366
    st.markdown(f"🧭 Using dispatch point: `{dispatch_lat}, {dispatch_lon}`")

    if "optimization_started" not in st.session_state:
        st.session_state.optimization_started = False

    if st.button("🚀 Start Optimization"):
        st.session_state.optimization_started = True

    if st.session_state.optimization_started:
        valid = df.dropna(subset=["Latitude", "Longitude"]).copy()

        if valid.empty:
            st.error("⚠️ No valid delivery addresses found.")
            st.dataframe(df)
        else:
            kmeans = KMeans(n_clusters=st.session_state.num_trucks, random_state=42)
            valid["Assigned Truck"] = kmeans.fit_predict(valid[["Latitude", "Longitude"]])
            valid["Driver"] = valid["Assigned Truck"].map(st.session_state.drivers)

            st.subheader("🗺️ Optimized Delivery Map")
            m = folium.Map(location=[dispatch_lat, dispatch_lon], zoom_start=11)
            folium.Marker([dispatch_lat, dispatch_lon],
                          tooltip=dispatch_label,
                          icon=folium.Icon(color="black", icon="home")).add_to(m)

            for _, row in valid.iterrows():
                folium.Marker([row["Latitude"], row["Longitude"]],
                              popup=f"{row['Client']}<br>Driver: {row['Driver']}").add_to(m)

            st_folium(m, width=1000, height=600)
            st.download_button("📥 Download Routes",
                               data=valid.to_excel(index=False),
                               file_name="OptimizedRoutes.xlsx")
