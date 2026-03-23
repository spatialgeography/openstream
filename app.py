import streamlit as st
import ee
import folium
from streamlit_folium import st_folium
from google.oauth2 import service_account
import json
import pandas as pd
from datetime import datetime, timedelta
import requests

# Set up page config
st.set_page_config(page_title="TerraClimate District Analytics", layout="wide", page_icon="🌎")

# Helper to add GEE layer to Folium
def add_ee_layer(self, ee_object, vis_params, name):
    try:
        if isinstance(ee_object, ee.ImageCollection):
            ee_object = ee_object.mean()
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

st.title("🌏 TerraClimate: District-Level Monitoring")

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

# --- MAIN PANEL: CLIMATE ANALYSIS ---
if st.session_state.get("ee_initialized"):
    # 1. Study Area Selection (GAUL Level 2)
    with st.expander("🗾 Study Area Selection (FAO GAUL)", expanded=True):
        c1, c2, c3 = st.columns(3)
        country_name = c1.text_input("Country (e.g. India, Italy)", value="India")
        state_name = c2.text_input("First Level / State (Optional)", value="")
        district_name = c3.text_input("Second Level / District (Optional)", value="")

    # 2. Climate Filters
    with st.container():
        f1, f2, f3 = st.columns([1, 1, 2])
        start_date = f1.date_input("Start", datetime(2017, 1, 1))
        end_date = f2.date_input("End", datetime(2017, 12, 31))
        
        variables = {
            'tmmx': 'Max Temp', 'tmmn': 'Min Temp', 'pdsi': 'Drought (PDSI)', 
            'pr': 'Precipitation', 'soil': 'Soil Moisture', 'aet': 'Evapotransp',
            'def': 'Water Deficit', 'pet': 'Ref Evapo', 'ro': 'Runoff',
            'srad': 'Radiation', 'swe': 'Snow Eq', 'vap': 'Vapor Pres', 
            'vpd': 'VPD', 'vs': 'Wind Speed'
        }
        selected_var = f3.selectbox("Select Variable", options=list(variables.keys()), format_func=lambda x: variables[x])

    st.markdown("---")

    try:
        # Load Boundaries (FAO GAUL Level 2)
        gaul = ee.FeatureCollection("FAO/GAUL_SIMPLIFIED_500m/2015/level2")
        
        # Apply Filters to Admin Boundary
        filters = [ee.Filter.eq('ADM0_NAME', country_name)]
        if state_name: filters.append(ee.Filter.eq('ADM1_NAME', state_name))
        if district_name: filters.append(ee.Filter.eq('ADM2_NAME', district_name))
        
        roi = gaul.filter(ee.Filter.And(*filters))
        
        # Load Climate Data
        dataset = ee.ImageCollection('IDAHO_EPSCOR/TERRACLIMATE') \
            .filterDate(start_date.strftime('%Y-%m-%d'), end_date.strftime('%Y-%m-%d'))
        
        # User defined palette (Custom Multi-Color)
        user_palette = ['1a3678', '2955bc', '5699ff', '8dbae9', 'acd1ff', 'caebff', 'e5f9ff', 'fdffb4', 'ffe6a2', 'ffc969', 'ffa12d', 'ff7c1f', 'ca531a', 'ff0000', 'ab0000']
        
        # Processing & Clipping
        mean_img = dataset.select(selected_var).mean().clip(roi)
        
        if selected_var in ['tmmx', 'tmmn']:
            vis_params = {'min': -300.0, 'max': 300.0, 'palette': user_palette}
        else:
            vis_params = {'min': 0, 'max': 500, 'palette': ['white', 'blue']}

        # --- TABS ---
        tab_map, tab_chart, tab_export = st.tabs(["🗺️ Map Viewer", "📈 Trend Analysis", "💾 Export Map"])
        
        with tab_map:
            # Map Centering
            try:
                center = roi.geometry().centroid().getInfo()['coordinates'][::-1]
                m = folium.Map(location=center, zoom_start=6)
            except:
                m = folium.Map(location=[20, 0], zoom_start=2)
                
            m.add_ee_layer(mean_img, vis_params, variables[selected_var])
            
            # Add Boundary Highlight
            folium.GeoJson(
                data=roi.geometry().getInfo(),
                name="Study Area",
                style_function=lambda x: {'fillColor': 'none', 'color': 'red', 'weight': 2}
            ).add_to(m)
            
            folium.LayerControl().add_to(m)
            st_folium(m, width="100%", height=600)
            
        with tab_chart:
            st.subheader(f"Temporal Trend: {variables[selected_var]}")
            if st.button("📊 Extract Time Series for Region"):
                with st.spinner("Processing regional data..."):
                    def extract_info(image):
                        date = image.date().format('YYYY-MM-DD')
                        # Mean over the whole ROI
                        value = image.reduceRegion(ee.Reducer.mean(), roi, 5000).get(selected_var)
                        return ee.Feature(None, {'date': date, 'value': value})
                    
                    data_features = dataset.select(selected_var).map(extract_info).getInfo()['features']
                    df = pd.DataFrame([f['properties'] for f in data_features])
                    if not df.empty:
                        df['date'] = pd.to_datetime(df['date'])
                        df = df.set_index('date').sort_index()
                        st.line_chart(df['value'])
                        st.dataframe(df)
                    else:
                        st.warning("No data found for this region/timeframe.")

        with tab_export:
            st.subheader("🖼️ Export Map as JPG")
            st.info("Generating a high-quality visualization for the selected area.")
            
            # Generate Thumbnail URL
            thumb_url = mean_img.getThumbURL({
                'min': vis_params['min'],
                'max': vis_params['max'],
                'palette': vis_params['palette'],
                'dimensions': 1024,
                'region': roi.geometry().bounds().getInfo(),
                'format': 'jpg'
            })
            
            st.image(thumb_url, caption=f"{variables[selected_var]} Map", use_column_width=True)
            st.markdown(f"📥 [Click here to download JPG]({thumb_url})")

    except Exception as e:
        st.error(f"Error: {e}")
        st.info("Check your Country/State/District names (case-sensitive) or ensure the area polygon is valid.")

else:
    st.info("👋 Template Ready! Authenticate in the sidebar to begin district-level climate monitoring.")
