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
st.set_page_config(page_title="TerraClimate Regional Explorer", layout="wide", page_icon="🌎")

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

# --- DATA FETCHING HELPERS ---
@st.cache_data(ttl=3600)
def get_countries():
    gaul = ee.FeatureCollection("FAO/GAUL_SIMPLIFIED_500m/2015/level2")
    return sorted(gaul.aggregate_array('ADM0_NAME').distinct().getInfo())

@st.cache_data(ttl=3600)
def get_states(country):
    gaul = ee.FeatureCollection("FAO/GAUL_SIMPLIFIED_500m/2015/level2")
    filtered = gaul.filter(ee.Filter.eq('ADM0_NAME', country))
    return sorted(filtered.aggregate_array('ADM1_NAME').distinct().getInfo())

@st.cache_data(ttl=3600)
def get_districts(country, state):
    gaul = ee.FeatureCollection("FAO/GAUL_SIMPLIFIED_500m/2015/level2")
    filtered = gaul.filter(ee.Filter.And(
        ee.Filter.eq('ADM0_NAME', country),
        ee.Filter.eq('ADM1_NAME', state)
    ))
    return sorted(filtered.aggregate_array('ADM2_NAME').distinct().getInfo())

st.title("🌏 TerraClimate: Global & Regional Dashboard")

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
    # 1. Selection Level & Dynamic Admin Selection
    with st.expander("🗾 Area of Interest Selection", expanded=True):
        level = st.radio("Selection Level", ["Country", "State/Province", "District"], horizontal=True)
        
        try:
            countries = get_countries()
            c1, c2, c3 = st.columns(3)
            
            with c1:
                selected_country = st.selectbox("Select Country", countries, index=countries.index("India") if "India" in countries else 0)
            
            with c2:
                if level in ["State/Province", "District"]:
                    states = get_states(selected_country)
                    selected_state = st.selectbox("Select Province/State", states)
                else:
                    st.info("Level: Entire Country")
                    selected_state = None
                
            with c3:
                if level == "District":
                    districts = get_districts(selected_country, selected_state)
                    selected_district = st.selectbox("Select District", districts)
                else:
                    st.info(f"Level: Entire {level}")
                    selected_district = None
        except Exception:
            st.warning("Fetching area data...")
            st.stop()

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

    # 3. Palette Customization
    with st.expander("🎨 Palette & Visualization Settings"):
        cp1, cp2, cp3, cp4 = st.columns([2, 1, 1, 1])
        default_p = "1a3678, 2955bc, 5699ff, 8dbae9, acd1ff, caebff, e5f9ff, fdffb4, ffe6a2, ffc969, ffa12d, ff7c1f, ca531a, ff0000, ab0000"
        palette_input = cp1.text_input("Hex Colors", value=default_p)
        auto_stretch = cp4.checkbox("Auto-Stretch", value=True)
        
        v_min_def = -300.0 if selected_var in ['tmmx', 'tmmn'] else 0.0
        v_max_def = 300.0 if selected_var in ['tmmx', 'tmmn'] else 500.0
        
        v_min = cp2.number_input("Min Value", value=v_min_def)
        v_max = cp3.number_input("Max Value", value=v_max_def)
        current_palette = [c.strip() for c in palette_input.split(",")]

    st.markdown("---")

    try:
        # Load Boundaries & Filter logic based on Level
        gaul = ee.FeatureCollection("FAO/GAUL_SIMPLIFIED_500m/2015/level2")
        filters = [ee.Filter.eq('ADM0_NAME', selected_country)]
        
        if level in ["State/Province", "District"] and selected_state:
            filters.append(ee.Filter.eq('ADM1_NAME', selected_state))
        if level == "District" and selected_district:
            filters.append(ee.Filter.eq('ADM2_NAME', selected_district))
            
        roi = gaul.filter(ee.Filter.And(*filters))
        
        # Load Climate Data
        dataset = ee.ImageCollection('IDAHO_EPSCOR/TERRACLIMATE') \
            .filterDate(start_date.strftime('%Y-%m-%d'), end_date.strftime('%Y-%m-%d'))
        
        # Processing & Statistics
        mean_img = dataset.select(selected_var).mean().clip(roi)
        
        if auto_stretch:
            with st.spinner("Calculating stats..."):
                stats = mean_img.reduceRegion(ee.Reducer.minMax(), roi.geometry(), 10000, maxPixels=1e9).getInfo()
                v_min = stats.get(f"{selected_var}_min", v_min_def)
                v_max = stats.get(f"{selected_var}_max", v_max_def)
        
        vis_params = {'min': v_min, 'max': v_max, 'palette': current_palette}
        st.info(f"Visualizing Range: [{round(v_min, 1)}, {round(v_max, 1)}]")

        # --- MAP & TABS ---
        tab_map, tab_chart, tab_export = st.tabs(["🗺️ Explorer", "📈 Area Analysis", "📥 Export JPG"])
        
        with tab_map:
            try:
                # Robust Centering Logic
                centroid_info = roi.geometry().centroid(1000).getInfo()
                if centroid_info and 'coordinates' in centroid_info:
                    center = centroid_info['coordinates'][::-1]
                    m = folium.Map(location=center, zoom_start=6 if level == 'Country' else 9)
                else:
                    m = folium.Map(location=[20, 0], zoom_start=2)
            except Exception:
                m = folium.Map(location=[20, 0], zoom_start=2)
                
            m.add_ee_layer(mean_img, vis_params, "Regional Data")
            folium.GeoJson(data=roi.geometry().getInfo(), style_function=lambda x: {'fillColor': 'none', 'color': 'red', 'weight': 2}).add_to(m)
            folium.LayerControl().add_to(m)
            st_folium(m, width="100%", height=600)
            
        with tab_chart:
            st.subheader(f"Temporal Trend for selected {level}")
            if st.button("📊 Extract Time Series"):
                with st.spinner("Calculating regional means..."):
                    def extract_info(image):
                        millis = image.date().millis()
                        value = image.reduceRegion(ee.Reducer.mean(), roi, 10000).get(selected_var)
                        return ee.Feature(None, {'millis': millis, 'value': value})
                    
                    data_features = dataset.select(selected_var).map(extract_info).getInfo()['features']
                    df = pd.DataFrame([f['properties'] for f in data_features])
                    if not df.empty:
                        df['date'] = pd.to_datetime(df['millis'], unit='ms')
                        df = df.set_index('date').sort_index().dropna(subset=['value'])
                        st.line_chart(df['value'])
                        st.dataframe(df[['value']])
                    else:
                        st.warning("No data found for this selection.")

        with tab_export:
            st.subheader("Region Map Download")
            thumb_url = mean_img.getThumbURL({'min': v_min, 'max': v_max, 'palette': current_palette, 'dimensions': 1024, 'region': roi.geometry().bounds().getInfo(), 'format': 'jpg'})
            st.image(thumb_url, use_column_width=True)
            st.markdown(f"📥 [Click here to download JPG]({thumb_url})")

    except Exception as e:
        st.error(f"Error: {e}")

else:
    st.info("👋 Select Auth in sidebar to begin.")
