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
    
    # 2. File Uploader for Service Account JSON
    st.subheader("Authentication Credentials")
    st.caption("Upload your Service Account JSON file.")
    
    uploaded_file = st.file_uploader("Choose a Service Account JSON file", type=["json"])
    
    # Added: Link to get the key
    st.markdown("🔗 [Get your Service Account Key](https://console.cloud.google.com/iam-admin/serviceaccounts)")

    # 3. Authenticate Button
    if st.button("🚀 Authenticate & Initialize"):
        if not project_id:
            st.error("Please enter a Project ID first.")
        else:
            st.session_state["project_id"] = project_id
            
            # If a file is uploaded, store its content in session state
            if uploaded_file is not None:
                try:
                    file_content = uploaded_file.read().decode("utf-8")
                    st.session_state["sa_json_content"] = json.loads(file_content)
                    st.success("JSON Key uploaded successfully!")
                except Exception as e:
                    st.error(f"Error reading JSON file: {e}")
            
            # Reset initialization state to force retry
            if "ee_initialized" in st.session_state:
                del st.session_state["ee_initialized"]
            st.rerun()

# Use provided credentials or secrets
def initialize_ee_v4():
    """Initializes Earth Engine using uploaded file or secrets."""
    current_project = st.session_state.get("project_id") or st.secrets.get("gee", {}).get("project_id")
    
    if not current_project or current_project == "YOUR_PROJECT_ID_HERE":
        st.info("👋 Welcome! Please enter your **Project ID** and **Upload your Service Account JSON** in the sidebar to begin.")
        return False

    if "ee_initialized" not in st.session_state:
        try:
            # 1. Try provided Uploaded JSON Content
            if st.session_state.get("sa_json_content"):
                sa_info = st.session_state["sa_json_content"]
                # Handle potential key formatting issues in newly uploaded files
                if "private_key" in sa_info and "\\n" in sa_info["private_key"]:
                    sa_info["private_key"] = sa_info["private_key"].replace("\\n", "\n")
                
                creds = service_account.Credentials.from_service_account_info(sa_info)
                ee.Initialize(creds, project=current_project)
            
            # 2. Fallback to Secrets.toml Service Account
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
            st.info("💡 Ensure the Earth Engine API is enabled and your credentials are correct.")
            return False
    return True

if initialize_ee_v4():
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
        m = folium.Map(location=[28.6139, 77.2090], zoom_start=10)
        m.add_ee_layer(l8, vis_params, f'Landsat 8 ({year})')
        folium.LayerControl().add_to(m)
        folium_static(m, width=1200)
    except Exception as e:
        st.error(f"Error loading map: {e}")
