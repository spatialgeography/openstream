import streamlit as st
import ee
import folium
from streamlit_folium import st_folium
from google.oauth2 import service_account
import json
from datetime import datetime, timedelta

# Set up page config
st.set_page_config(page_title="Earth Engine Pro Viewer", layout="wide", page_icon="🌍")

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

st.title("🛰️ Earth Engine Interactive Explorer")

# Sidebar Authentication & Filters
with st.sidebar:
    st.header("🔑 1. Connection")
    project_id = st.text_input("Project ID", value=st.session_state.get("project_id", ""), placeholder="GEE Project ID")
    uploaded_file = st.file_uploader("Service Account JSON", type=["json"])
    st.markdown("🔗 [Get Key](https://console.cloud.google.com/iam-admin/serviceaccounts)")

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

    if st.session_state.get("ee_initialized"):
        st.markdown("---")
        st.header("📅 2. Filters")
        
        # Date range
        today = datetime.now()
        start_date = st.date_input("Start Date", today - timedelta(days=365))
        end_date = st.date_input("End Date", today)
        
        # Dataset choice
        dataset_choice = st.selectbox("Select Dataset", ["Landsat 8 (TOA)", "Sentinel-2 (SR)", "MODIS Vegetation"])
        
        # Visualization choice
        vis_mode = st.selectbox("Visualization", ["Natural Color (RGB)", "False Color (Infrared)", "NDVI (Vegetation Index)"])
        
        st.header("📍 3. Location")
        lat = st.number_input("Latitude", value=28.6, format="%.4f")
        lon = st.number_input("Longitude", value=77.2, format="%.4f")
        zoom = st.slider("Zoom Level", 1, 18, 10)

# Main Dashboard Logic
if st.session_state.get("ee_initialized"):
    try:
        # Define AOI (Point with buffer)
        aoi = ee.Geometry.Point([lon, lat]).buffer(10000) # 10km buffer
        
        # Load correct collection based on choice
        if dataset_choice == "Landsat 8 (TOA)":
            col = ee.ImageCollection("LANDSAT/LC08/C02/T1_TOA") \
                .filterBounds(aoi) \
                .filterDate(start_date.strftime('%Y-%m-%d'), end_date.strftime('%Y-%m-%d'))
            
            if vis_mode == "Natural Color (RGB)":
                vis_params = {'bands': ['B4', 'B3', 'B2'], 'min': 0, 'max': 0.3, 'gamma': 1.4}
                img = col.median()
            elif vis_mode == "False Color (Infrared)":
                vis_params = {'bands': ['B5', 'B4', 'B3'], 'min': 0, 'max': 0.5, 'gamma': 1.4}
                img = col.median()
            else: # NDVI
                def getNDVI(image):
                    return image.normalizedDifference(['B5', 'B4']).rename('NDVI')
                img = col.map(getNDVI).median()
                vis_params = {'min': -1, 'max': 1, 'palette': ['blue', 'white', 'green']}

        elif dataset_choice == "Sentinel-2 (SR)":
            col = ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED") \
                .filterBounds(aoi) \
                .filterDate(start_date.strftime('%Y-%m-%d'), end_date.strftime('%Y-%m-%d'))
            
            if vis_mode == "Natural Color (RGB)":
                vis_params = {'bands': ['B4', 'B3', 'B2'], 'min': 0, 'max': 3000}
                img = col.median()
            elif vis_mode == "False Color (Infrared)":
                vis_params = {'bands': ['B8', 'B4', 'B3'], 'min': 0, 'max': 5000}
                img = col.median()
            else: # NDVI
                def getNDVI(image):
                    return image.normalizedDifference(['B8', 'B4']).rename('NDVI')
                img = col.map(getNDVI).median()
                vis_params = {'min': -1, 'max': 1, 'palette': ['blue', 'white', 'green']}
        
        else: # MODIS
            col = ee.ImageCollection("MODIS/061/MOD13Q1") \
                .filterBounds(aoi) \
                .filterDate(start_date.strftime('%Y-%m-%d'), end_date.strftime('%Y-%m-%d'))
            img = col.select('NDVI').median().multiply(0.0001)
            vis_params = {'min': 0, 'max': 1, 'palette': ['white', 'green']}

        # Create Map
        m = folium.Map(location=[lat, lon], zoom_start=zoom, control_scale=True)
        
        # Add AOI to map for reference
        folium.GeoJson(
            data=aoi.getInfo(),
            name="Analysis AOI",
            style_function=lambda x: {'fillColor': 'none', 'color': 'red', 'weight': 2}
        ).add_to(m)

        # Add EE Layer
        m.add_ee_layer(img, vis_params, f"{dataset_choice} - {vis_mode}")
        
        folium.LayerControl().add_to(m)
        
        # Display
        st.write(f"Showing **{dataset_choice}** filtered by **{vis_mode}** from `{start_date}` to `{end_date}`.")
        st_folium(m, width="100%", height=600)
        
    except Exception as e:
        st.error(f"Visualization Error: {e}")
        st.info("Try a wider date range or check if imagery is available for this area.")
else:
    st.info("👋 Hello! Please connect your Project ID and JSON key in the sidebar to begin exploring satellite imagery.")
