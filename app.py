import streamlit as st
import ee
import folium
from streamlit_folium import folium_static
from google.oauth2 import service_account
import json

# Set up page config
st.set_page_config(page_title="Earth Engine Viewer", layout="wide")

# Helper to add GEE layer to Folium
def add_ee_layer(self, ee_object, vis_params, name):
    map_id_dict = ee.Image(ee_object).getMapId(vis_params)
    folium.raster_layers.TileLayer(
        tiles=map_id_dict['tile_fetcher'].url_format,
        attr='Map Data &copy; Google Earth Engine',
        name=name,
        overlay=True,
        control=True
    ).add_to(self)
folium.Map.add_ee_layer = add_ee_layer

st.title("🌍 Google Earth Engine Viewer")

# Sidebar Authentication
with st.sidebar:
    st.header("🔑 Authentication Setup")
    
    # 1. Project ID
    project_id = st.text_input("Enter Google Cloud Project ID", 
                              value=st.session_state.get("project_id", ""),
                              placeholder="my-gee-project-id")
    
    st.markdown("---")
    
    # 2. File Uploader (Replaces the text box entirely)
    st.subheader("Authentication Credentials")
    uploaded_file = st.file_uploader("Upload Service Account JSON file", type=["json"])
    
    # 3. Instruction Link
    st.markdown("🔗 [Get your credential from Google Cloud](https://console.cloud.google.com/iam-admin/serviceaccounts)")

    # 4. Authenticate Button
    if st.button("🚀 Authenticate & Initialize"):
        if not project_id:
            st.error("Please enter a Project ID.")
        elif uploaded_file is None:
            st.error("Please upload a JSON key file.")
        else:
            try:
                # Read and parse JSON
                content = uploaded_file.read().decode("utf-8")
                sa_info = json.loads(content)
                
                # Sanitize private key
                if "private_key" in sa_info:
                    sa_info["private_key"] = sa_info["private_key"].replace("\\n", "\n")
                
                # Initialize EE with specific scope
                SCOPES = ['https://www.googleapis.com/auth/earthengine']
                creds = service_account.Credentials.from_service_account_info(
                    sa_info, scopes=SCOPES
                )
                ee.Initialize(creds, project=project_id)
                
                # Save state
                st.session_state["project_id"] = project_id
                st.session_state["ee_initialized"] = True
                st.success("Successfully Authenticated!")
                st.rerun()
            except Exception as e:
                st.error(f"Initialization Failed: {e}")

# Application Logic
if st.session_state.get("ee_initialized"):
    st.sidebar.markdown("---")
    year = st.sidebar.slider("Select Year", 2013, 2023, 2023)
    
    try:
        # Simple NDVI or RGB median logic
        dataset = ee.ImageCollection("LANDSAT/LC08/C02/T1_TOA") \
            .filterDate(f"{year}-01-01", f"{year}-12-31") \
            .median()
        
        vis = {'bands': ['B4', 'B3', 'B2'], 'min': 0, 'max': 0.3, 'gamma': 1.4}
        
        m = folium.Map(location=[28.6, 77.2], zoom_start=10)
        m.add_ee_layer(dataset, vis, f'Landsat 8 ({year})')
        folium.LayerControl().add_to(m)
        folium_static(m, width=1200)
    except Exception as e:
        st.error(f"Map Error: {e}")
else:
    st.info("👋 Setup complete! Please use the sidebar to connect your Google Earth Engine project.")
