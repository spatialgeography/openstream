import streamlit as st
import ee
import folium
from streamlit_folium import st_folium
from google.oauth2 import service_account
import json
from datetime import datetime, timedelta

# Set up page config
st.set_page_config(page_title="GEE Landsat Analysis", layout="wide", page_icon="🛰️")

# Helper to add GEE layer to Folium
def add_ee_layer(self, ee_object, vis_params, name):
    try:
        if isinstance(ee_object, ee.ImageCollection):
            ee_object = ee_object.median()
        map_id_dict = ee.Image(ee_object).getMapId(vis_params)
        folium.raster_layers.TileLayer(
            tiles=map_id_dict['tile_fetcher'].url_format,
            attr='Map Data &copy; Google Earth Engine',
            name=name,
            overlay=True,
            control=True
        ).add_to(self)
    except Exception as e:
        st.error(f"Error adding EE layer '{name}': {e}")

folium.Map.add_ee_layer = add_ee_layer

st.title("🛰️ Landsat 8 Interactive Explorer")

# --- SIDEBAR: ONLY AUTHENTICATION ---
with st.sidebar:
    st.header("🔑 Connection & Auth")
    project_id = st.text_input("Project ID", value=st.session_state.get("project_id", ""), placeholder="GEE Project ID")
    uploaded_file = st.file_uploader("Service Account JSON", type=["json"])
    
    st.markdown("🔗 [Get Key](https://console.cloud.google.com/iam-admin/serviceaccounts)")
    st.markdown("📺 [Watch the Tutorial](https://www.youtube.com/@SpatialGeography)")

    if st.button("🚀 Connect to GEE"):
        if not project_id or uploaded_file is None:
            st.error("Missing Project ID or JSON file.")
        else:
            try:
                content = uploaded_file.read().decode("utf-8")
                sa_info = json.loads(content)
                if "private_key" in sa_info:
                    sa_info["private_key"] = sa_info["private_key"].replace("\\n", "\n")
                
                SCOPES = ['https://www.googleapis.com/auth/earthengine']
                creds = service_account.Credentials.from_service_account_info(sa_info, scopes=SCOPES)
                ee.Initialize(creds, project=project_id)
                
                st.session_state["project_id"] = project_id
                st.session_state["ee_initialized"] = True
                st.success("Connected!")
                st.rerun()
            except Exception as e:
                st.error(f"Failed: {e}")

# --- MAIN PANEL: ANALYSIS ---
if st.session_state.get("ee_initialized"):
    with st.container():
        col1, col2 = st.columns([1, 1])
        
        with col1:
            st.subheader("📅 Timeframe")
            start_date = st.date_input("Start Date", datetime.now() - timedelta(days=365))
            end_date = st.date_input("End Date", datetime.now())
        
        with col2:
            st.subheader("📍 Location")
            lat = st.number_input("Lat", value=28.6, format="%.4f")
            lon = st.number_input("Lon", value=77.2, format="%.4f")
            zoom = st.slider("Zoom", 1, 18, 10)

    st.markdown("---")

    try:
        # Define AOI
        aoi = ee.Geometry.Point([lon, lat]).buffer(15000)
        
        # Load Landsat 8 (TOA)
        col = ee.ImageCollection("LANDSAT/LC08/C02/T1_TOA") \
            .filterBounds(aoi) \
            .filterDate(start_date.strftime('%Y-%m-%d'), end_date.strftime('%Y-%m-%d'))
        
        # Visualization Selection
        vis_mode = st.radio("Visualization Style", ["Natural Color", "False Color", "NDVI"], horizontal=True)
        
        if vis_mode == "Natural Color":
            vis_params = {'bands': ['B4', 'B3', 'B2'], 'min': 0, 'max': 0.3, 'gamma': 1.4}
            img = col.median()
        elif vis_mode == "False Color":
            vis_params = {'bands': ['B5', 'B4', 'B3'], 'min': 0, 'max': 0.5, 'gamma': 1.4}
            img = col.median()
        else: # NDVI
            def getNDVI(image):
                return image.normalizedDifference(['B5', 'B4']).rename('NDVI')
            img = col.map(getNDVI).median()
            vis_params = {'min': -1, 'max': 1, 'palette': ['red', 'yellow', 'green']}

        # Map Display
        m = folium.Map(location=[lat, lon], zoom_start=zoom)
        m.add_ee_layer(img, vis_params, f"Landsat 8 - {vis_mode}")
        folium.LayerControl().add_to(m)
        
        st.write(f"Showing **Landsat 8** composite in **{vis_mode}**.")
        st_folium(m, width="100%", height=600)
        
    except Exception as e:
        st.error(f"Error: {e}")

else:
    st.info("👋 Setup complete! Use the sidebar to authorize. This page will unlock all Landsat 8 analysis tools once connected.")
