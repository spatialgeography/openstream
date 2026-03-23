import streamlit as st
import ee
import folium
from streamlit_folium import folium_static
from google.oauth2 import service_account
import json

# Set up page config
st.set_page_config(page_title="Earth Engine Viewer (Native)", layout="wide")

# Helper to add EE layer to folium
def add_ee_layer(self, ee_object, vis_params, name):
    """Function to add GEE data as a folium layer."""
    map_id_dict = ee.Image(ee_object).getMapId(vis_params)
    folium.raster_layers.TileLayer(
        tiles=map_id_dict['tile_fetcher'].url_format,
        attr='Map Data &copy; <a href="https://earthengine.google.com/">Google Earth Engine</a>',
        name=name,
        overlay=True,
        control=True
    ).add_to(self)

# Register the helper to Folium
folium.Map.add_ee_layer = add_ee_layer

# App Main UI
st.title("🌍 Google Earth Engine (Direct API)")
st.markdown("### Simple Viewer (No `geemap`)")

# Input for Project ID and Service Account if not in secrets
with st.sidebar:
    st.header("🔑 Authentication Setup")
    
    # Try to get defaults from secrets
    default_project = st.secrets.get("gee", {}).get("project_id", "")
    
    # 1. Project ID Input
    project_id = st.text_input("Enter Google Cloud Project ID", 
                              value=st.session_state.get("project_id", default_project),
                              placeholder="e.g. my-gee-project")
    
    st.markdown("---")
    
    # 2. Credentials Input (Fixing the previous error: st.text_area)
    st.subheader("Authentication Credentials")
    st.caption("Paste your Service Account JSON or Client ID details here.")
    
    creds_input = st.text_area("JSON Credentials", 
                                value=st.session_state.get("creds_input", ""), 
                                height=250,
                                placeholder='{"type": "service_account", ...}')

    # 3. Authenticate Button
    if st.button("🚀 Authenticate & Initialize"):
        if not project_id:
            st.error("Please enter a Project ID first.")
        else:
            st.session_state["project_id"] = project_id
            st.session_state["creds_input"] = creds_input
            
            # Reset initialization state to force retry
            if "ee_initialized" in st.session_state:
                del st.session_state["ee_initialized"]
            st.rerun()

# Use provided credentials or secrets
def initialize_ee_v3():
    """Initializes Earth Engine using provided inputs or secrets."""
    current_project = st.session_state.get("project_id") or st.secrets.get("gee", {}).get("project_id")
    
    if not current_project or current_project == "YOUR_PROJECT_ID_HERE":
        st.info("👋 Welcome! Please enter your **Project ID** and **Credentials** in the sidebar to begin.")
        return False

    if "ee_initialized" not in st.session_state:
        try:
            # 1. Try provided Text Area JSON
            if st.session_state.get("creds_input"):
                try:
                    sa_info = json.loads(st.session_state["creds_input"])
                    creds = service_account.Credentials.from_service_account_info(sa_info)
                    ee.Initialize(creds, project=current_project)
                except json.JSONDecodeError:
                    st.error("Invalid JSON format in Credentials area. Please paste the full JSON file content.")
                    return False
            
            # 2. Fallback to Secrets.toml
            elif "gcp_service_account" in st.secrets:
                sa_info = dict(st.secrets["gcp_service_account"])
                if "\\n" in sa_info["private_key"]:
                    sa_info["private_key"] = sa_info["private_key"].replace("\\n", "\n")
                creds = service_account.Credentials.from_service_account_info(sa_info)
                ee.Initialize(creds, project=current_project)
            
            # 3. Fallback to ADC
            else:
                ee.Initialize(project=current_project)
            
            st.session_state["ee_initialized"] = True
            st.session_state["current_project"] = current_project
            return True
        except Exception as e:
            st.error(f"Earth Engine Initialization Failed: {e}")
            return False
    return True

if initialize_ee_v3():
    st.success(f"Successfully connected to: `{st.session_state.get('current_project')}`")
    
    # Map Controls
    st.sidebar.markdown("---")
    st.sidebar.header("Map Controls")
    year = st.sidebar.slider("Select Year (Landsat 8)", 2013, 2023, 2023)
    
    try:
        l8 = ee.ImageCollection("LANDSAT/LC08/C02/T1_TOA") \
            .filterDate(f"{year}-01-01", f"{year}-12-31") \
            .median()
        
        vis_params = {'bands': ['B4', 'B3', 'B2'], 'min': 0, 'max': 0.3, 'gamma': 1.4}
        m = folium.Map(location=[0, 0], zoom_start=2)
        m.add_ee_layer(l8, vis_params, f'Landsat 8 ({year})')
        folium.LayerControl().add_to(m)
        folium_static(m, width=1200)
    except Exception as e:
        st.error(f"Error loading map: {e}")
