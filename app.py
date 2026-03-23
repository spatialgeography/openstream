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
st.set_page_config(page_title="TerraClimate District Explorer", layout="wide", page_icon="🌎")

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

st.title("🌏 TerraClimate: Smart District Monitoring")

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
    # 1. Dynamic Admin Selection
    with st.expander("🗾 Smart Area Selection", expanded=True):
        try:
            countries = get_countries()
            c1, c2, c3 = st.columns(3)
            
            with c1:
                selected_country = st.selectbox("Select Country", countries, index=countries.index("India") if "India" in countries else 0)
            
            with c2:
                states = get_states(selected_country)
                selected_state = st.selectbox("Select Province/State", states)
                
            with c3:
                districts = get_districts(selected_country, selected_state)
                selected_district = st.selectbox("Select District", districts)
        except Exception as e:
            st.warning("Fetching admin boundaries... Please wait or check your GEE connection.")
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
        
        # Determine initial defaults if not auto-stretching
        v_min_def = -300.0 if selected_var in ['tmmx', 'tmmn'] else 0.0
        v_max_def = 300.0 if selected_var in ['tmmx', 'tmmn'] else 500.0
        
        v_min = cp2.number_input("Min Value", value=v_min_def)
        v_max = cp3.number_input("Max Value", value=v_max_def)
        
        current_palette = [c.strip() for c in palette_input.split(",")]

    st.markdown("---")

    try:
        # Load Boundaries
        gaul = ee.FeatureCollection("FAO/GAUL_SIMPLIFIED_500m/2015/level2")
        roi = gaul.filter(ee.Filter.And(
            ee.Filter.eq('ADM0_NAME', selected_country),
            ee.Filter.eq('ADM1_NAME', selected_state),
            ee.Filter.eq('ADM2_NAME', selected_district)
        ))
        
        # Load Climate Data
        dataset = ee.ImageCollection('IDAHO_EPSCOR/TERRACLIMATE') \
            .filterDate(start_date.strftime('%Y-%m-%d'), end_date.strftime('%Y-%m-%d'))
        
        # Processing
        mean_img = dataset.select(selected_var).mean().clip(roi)
        
        # --- AUTO STRETCH LOGIC ---
        if auto_stretch:
            with st.spinner("Calculating regional stats..."):
                stats = mean_img.reduceRegion(
                    reducer=ee.Reducer.minMax(),
                    geometry=roi.geometry(),
                    scale=5000,
                    maxPixels=1e9
                ).getInfo()
                
                # Update Min/Max from GEE result
                v_min = stats.get(f"{selected_var}_min", v_min_def)
                v_max = stats.get(f"{selected_var}_max", v_max_def)
        
        # Apply Custom Palette
        vis_params = {'min': v_min, 'max': v_max, 'palette': current_palette}
        st.info(f"Visualizing `{variables[selected_var]}` with range [{round(v_min, 1)}, {round(v_max, 1)}]")

        # --- MAP & TABS ---
        tab_map, tab_chart, tab_export = st.tabs(["🗺️ Map Viewer", "📈 Trend Analysis", "💾 Export Map"])
        
        with tab_map:
            # Safer Map Centering
            try:
                roi_count = roi.size().getInfo()
                if roi_count > 0:
                    center = roi.geometry().centroid().getInfo()['coordinates'][::-1]
                    m = folium.Map(location=center, zoom_start=8)
                else:
                    st.warning(f"No boundary found for `{selected_district}`. Showing global view.")
                    m = folium.Map(location=[20, 0], zoom_start=2)
            except Exception:
                m = folium.Map(location=[20, 0], zoom_start=2)
            m.add_ee_layer(mean_img, vis_params, f"{selected_district} - {variables[selected_var]}")
            
            folium.GeoJson(
                data=roi.geometry().getInfo(),
                name=selected_district,
                style_function=lambda x: {'fillColor': 'none', 'color': 'red', 'weight': 2}
            ).add_to(m)
            
            folium.LayerControl().add_to(m)
            st_folium(m, width="100%", height=600)
            
        with tab_chart:
            st.subheader(f"Temporal Trend in {selected_district}")
            if st.button("📊 Extract Time Series"):
                with st.spinner("Processing regional data..."):
                    def extract_info(image):
                        date = image.date().format('YYYY-MM-DD')
                        value = image.reduceRegion(ee.Reducer.mean(), roi, 5000).get(selected_var)
                        return ee.Feature(None, {'date': date, 'value': value})
                    
                    data_features = dataset.select(selected_var).map(extract_info).getInfo()['features']
                    df = pd.DataFrame([f['properties'] for f in data_features])
                    if not df.empty:
                        df['date'] = pd.to_datetime(df['date'], format='mixed')
                        df = df.set_index('date').sort_index()
                        st.line_chart(df['value'])
                        st.dataframe(df)
                    else:
                        st.warning("No data found for this period.")

        with tab_export:
            st.subheader("🖼️ Region Export")
            thumb_url = mean_img.getThumbURL({
                'min': vis_params['min'], 'max': vis_params['max'], 'palette': vis_params['palette'],
                'dimensions': 1024, 'region': roi.geometry().bounds().getInfo(), 'format': 'jpg'
            })
            st.image(thumb_url, caption=f"{selected_district} {variables[selected_var]}", use_column_width=True)
            st.markdown(f"📥 [Click here to download JPG]({thumb_url})")

    except Exception as e:
        st.error(f"Error: {e}")

else:
    st.info("👋 Hello! Authenticate in the sidebar to unlock the Smart Area Selection tool.")
