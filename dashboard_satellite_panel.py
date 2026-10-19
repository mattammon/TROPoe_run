"""Optional right-hand satellite viewer shared by all dashboard pages."""
from pathlib import Path
import streamlit as st
from dashboard_data import case_label
from dashboard_classification import match_satellite_images
from dashboard_setup import read_satellite_inventory
from dashboard_satellite import generate_satellite_image
from dashboard_vertical import plotly_size_kwargs


def render_satellite_panel(cases, source):
    def collapse():
        st.session_state.show_dashboard_satellite = False
    st.button('Hide imagery panel', on_click=collapse, key='hide_satellite_panel')
    st.subheader('Satellite imagery')
    if cases.empty:
        st.info('No cases available.')
        return
    labels = dict(zip(cases.case_id, cases.sounding_time.map(case_label)))
    if st.session_state.get('dashboard_case') not in labels:
        st.session_state.dashboard_case = cases.case_id.iloc[0]
    selected = st.selectbox('Satellite case', list(labels), format_func=labels.get, key='dashboard_case')
    row = cases.set_index('case_id').loc[selected]
    st.caption(labels[selected]+' · '+str(row.get('category', '')))
    root = str(Path(source['image_root']).expanduser().resolve())
    tolerance = st.number_input('Image time tolerance (minutes)', min_value=0., max_value=60., value=15., key='panel_image_tolerance')
    if st.button('Refresh imagery', key='panel_image_refresh'):
        read_satellite_inventory.clear()
    try:
        inventory = read_satellite_inventory(root) if Path(root).exists() else []
        result = match_satellite_images(inventory, row.sounding_time, row.get('retrieval_time'), tolerance)
        if not result['matches']:
            st.info('No matching satellite image is available.')
            if st.button('Generate image for this case', key='panel_image_generate'):
                with st.spinner('Generating satellite imagery…'):
                    generate_satellite_image(row.sounding_time, root)
                read_satellite_inventory.clear()
                st.rerun()
        else:
            matches = result['matches']
            paths = [str(item['path']) for item in matches]
            image = st.selectbox('Image', paths, format_func=lambda p: Path(p).name, key='panel_image_'+str(selected))
            st.image(image, caption=Path(image).name, **plotly_size_kwargs(st.image))
            st.caption('Match: '+result['basis'])
            st.download_button('Download image', Path(image).read_bytes(), Path(image).name, 'image/png', key='panel_image_download')
        st.caption('Image directory: '+root)
        st.caption('This viewer does not change the case cohort used for aggregate statistics. On Vertical profiles, it also selects the profile case when that case passes the active filters.')
    except Exception as exc:
        st.error('Satellite image could not be displayed: '+str(exc))
