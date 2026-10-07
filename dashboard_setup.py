"""Classification-first Streamlit workflow and satellite review."""
from dataclasses import asdict
import json
from pathlib import Path

import pandas as pd
import streamlit as st

import dashboard_data as data
import dashboard_plots as plots
from dashboard_classification import (ClassificationRules, ReviewStore, classify, fingerprint,
                                      prepare_master, save_run, satellite_inventory, match_satellite_images)
from dashboard_vertical import plotly_size_kwargs


@st.cache_data(show_spinner=False, ttl=60)
def read_satellite_inventory(root):
    return satellite_inventory(root)


def inspect_case(frame, image_root, store, key, on_review=None):
    """Select on the scatter or use the list for cases with missing radiance."""
    labels = dict(zip(frame.case_id, frame.sounding_time.map(data.case_label)))
    selected_key = key+'_case'
    if st.session_state.get(selected_key) not in labels:
        st.session_state[selected_key] = frame.case_id.iloc[0]
    case = st.selectbox('Inspect case / satellite image', list(labels), format_func=labels.get, key=selected_key)
    row = frame.set_index('case_id').loc[case]
    st.write('**'+labels[case]+'**')
    st.caption(f"Automatic: {row.automatic_category} · Final: {row.category} · Source: {row.classification_source}")
    image_root = str(Path(image_root).expanduser().resolve())
    tolerance = st.number_input('Satellite filename time tolerance (minutes)', min_value=0.,
                                max_value=60., value=15., step=1., key=key+'_sat_tolerance',
                                help='Try the exact sounding and retrieval minutes first, then the closest filename time to retrieval_time within this limit. Zero disables nearby matching.')
    if st.button('Refresh satellite files', key=key+'_refresh_satellite'):
        read_satellite_inventory.clear()
    st.caption('Searching recursively: '+image_root)
    st.caption('Sounding UTC: '+str(row.sounding_time)+' · Retrieval UTC: '+str(row.get('retrieval_time', 'missing')))
    image = ''
    try:
        inventory = read_satellite_inventory(image_root)
        result = match_satellite_images(inventory, row.sounding_time, row.get('retrieval_time'), tolerance)
        matches = result['matches']
        st.caption(f'{len(inventory):,} timestamped PNGs indexed. Matching: {result["basis"]}.')
        if matches:
            paths = [item['path'] for item in matches]
            chosen = st.selectbox('Satellite image', paths, format_func=lambda p: p.name, key=key+'_image_'+case)
            image = str(chosen)
            matched = next(item for item in matches if item['path'] == chosen)
            st.caption(f'Filename time: {matched["time"]:%d %b %Y · %H:%M UTC}; offset {matched["offset_minutes"]:+g} min from {result["reference_time"]:%H:%M UTC}. The actual GOES scan time is in the image title.')
            if result['basis'].startswith('nearest'):
                st.warning('Nearby-time match: verify the image time before recording a manual classification.')
            st.image(image, caption=Path(image).name, **plotly_size_kwargs(st.image))
        elif not inventory:
            st.info('No PNGs beginning YYYYMMDDhhmm were found. Check the directory and its visibility inside the app/container, then refresh satellite files.')
        else:
            st.info(f'No exact sounding/retrieval image or nearby image within {tolerance:g} minutes was found. You can still record a review.')
    except (OSError, ValueError) as exc:
        st.error('Satellite image lookup/display failed: '+str(exc))
    current, _ = store.snapshot()
    if case in current:
        st.caption('Saved manual review: '+current[case]['category']+' · '+current[case]['created_utc']+' · '+current[case]['note'])
    with st.form(key+'_manual_form_'+case):
        category = st.selectbox('Manual classification', ['clear_sky', 'not_clear_sky', 'uncertain'],
                                index=['clear_sky', 'not_clear_sky', 'uncertain'].index(row.category))
        note = st.text_input('Review note', placeholder='Clouds visible east of site, for example')
        reviewer = st.text_input('Reviewer (optional)')
        save = st.form_submit_button('Save persistent manual override')
        clear = st.form_submit_button('Remove override / use thresholds')
    if save or clear:
        try:
            store.save(case, category if save else None, note, image, reviewer)
        except Exception as exc:
            st.error('Review was not saved: '+str(exc))
        else:
            if on_review is not None:
                try:
                    on_review()
                except Exception as exc:
                    st.session_state.pop('cloud_active', None)
                    st.error('Manual review was saved, but the new classification snapshot could not be saved. Reopen the editor and apply again: '+str(exc))
                    st.stop()
            st.rerun()


def review_plot(preview, rules, image_root, store, key='classification', on_review=None):
    left, right = st.columns([3, 2])
    with left:
        grouping = st.selectbox('Group cases by', ['Classification', 'Season', 'Month', 'Time of day (UTC)',
                                                  'ASI classification', 'Radiance classification', 'Year'], key=key+'_group')
        fields = [f'radiance_{rules.window}_radiance_{part}' for part in ('mean', 'std')]
        if all(f in preview for f in fields):
            figure, plotted = plots.radiance_plot(preview, rules.window, grouping,
                                                  rules.radiance_mean_max, rules.radiance_std_max,
                                                  rules.use_radiance, rules.use_radiance)
            # Append stable case IDs for selection; hover remains a readable date.
            for trace in figure.data:
                trace_ids = plotted.loc[plotted[grouping] == trace.name, 'case_id'].tolist()
                if len(trace_ids) == len(trace.x):
                    trace.customdata = [list(row)+[case_id] for row, case_id in zip(trace.customdata, trace_ids)]
            figure.update_layout(clickmode='event+select')
            event = st.plotly_chart(figure, **plotly_size_kwargs(st.plotly_chart), key=key+'_scatter',
                                   on_select='rerun', selection_mode='points', config={'displaylogo': False})
            points = event.selection.points
            if points:
                point = points[-1]
                payload = point.get('customdata', [])
                if len(payload) >= 6:
                    picked = payload[-1]
                    # Do not override a subsequent dropdown selection on every rerun.
                    event_token = json.dumps(points, sort_keys=True, default=str)
                    if st.session_state.get(key+'_last_event') != event_token and picked in set(preview.case_id):
                        st.session_state[key+'_case'] = picked
                        st.session_state[key+'_last_event'] = event_token
            st.caption(f'{len(plotted):,} / {len(preview):,} cases have finite radiance mean/std. All cases are classified; missing-coordinate cases remain accessible in the case selector. Click a point to inspect it.')
        else:
            st.info('Radiance summaries for this window are absent. All cases remain available in the case selector; enabled radiance evidence will be uncertain.')
        st.caption('The shaded rectangle represents the radiance criterion only. With an “either” rule, ASI may also establish clear sky outside that rectangle. Manual decisions always take precedence.')
    with right:
        inspect_case(preview, image_root, store, key, on_review)


def classification_gate(default_manifest, default_root, default_sonde, default_images, default_output):
    """Return a frozen classified dataset only after its compact manifest is saved."""
    with st.sidebar:
        st.header('Master data and saved classifications')
        with st.form('source_form'):
            manifest = st.text_input('Master manifest CSV (legacy manifests can be imported)', default_manifest)
            root = st.text_input('Retrieval directory', default_root)
            catalog = st.text_input('Catalog profiles.csv (optional)', '')
            sonde = st.text_input('Sounding search directory (optional)', default_sonde)
            image_root = st.text_input('Satellite PNG directory', default_images,
                                       help='Search includes subdirectories. Click Load / refresh master data to apply a changed path; it must be visible inside the app/container.')
            output = st.text_input('Classification and manual-review directory', default_output,
                                   help='Use the same persistent directory for future runs so manual overrides carry forward.')
            load = st.form_submit_button('Load / refresh master data', type='primary')
    if load or ('cloud_loaded' not in st.session_state and Path(default_manifest or '__missing__').is_file()):
        try:
            read_satellite_inventory.clear()
            master = prepare_master(manifest)
            cases = data.read_manifest(master)
            # Master on disk has no classes; read_manifest adds placeholders only in memory.
            store = ReviewStore(output)
            st.session_state.cloud_loaded = dict(master=str(master), master_hash=fingerprint(master), cases=cases,
                root=str(Path(root).expanduser().resolve()), catalog=str(Path(catalog).expanduser().resolve()) if catalog else '',
                sonde_root=str(Path(sonde).expanduser()) if sonde else '', image_root=str(Path(image_root).expanduser()),
                output=str(store.root))
            st.session_state.pop('cloud_active', None)
            st.session_state.pop('loaded_source', None)
        except Exception as exc:
            st.error('Could not load master: '+str(exc))
            st.stop()
    loaded = st.session_state.get('cloud_loaded')
    if loaded is None:
        st.subheader('Choose cloud classification thresholds')
        st.info('Load your master manifest using the sidebar. Existing classified manifests are imported into an unclassified master; original files are retained.')
        st.stop()
    with st.sidebar:
        st.caption('Master: '+loaded['master'])
        active = st.session_state.get('cloud_active')
        if active and st.button('Review images / change classification thresholds'):
            st.session_state.cloud_draft_rules = active['rules']
            st.session_state.pop('cloud_active', None)
            st.rerun()
    if active:
        st.caption('Classification snapshot: '+active['path'])
        return loaded, active
    st.subheader('Classify all available cases')
    st.caption('Choose limits, inspect satellite images, and then apply. Changing a threshold updates the preview; Apply saves a new classification snapshot and opens the dashboard.')
    draft = ClassificationRules(**st.session_state.get('cloud_draft_rules', {}))
    a, b, c = st.columns(3)
    with a:
        window = st.selectbox('Classification window', ['core', 'context'], index=['core', 'context'].index(draft.window), key='class_window')
        use_asi = st.checkbox('Use ASI', value=draft.use_asi, key='class_asi')
        zenith = st.number_input('ASI near-zenith mean cloud maximum (%)', min_value=0., max_value=100., value=draft.asi_zenith_max, key='class_zenith')
        total = st.number_input('ASI total mean cloud maximum (%)', min_value=0., max_value=100., value=draft.asi_total_max, key='class_total')
    with b:
        use_rad = st.checkbox('Use 985 radiance', value=draft.use_radiance, key='class_rad')
        mean = st.number_input('985 radiance mean maximum', min_value=0., value=draft.radiance_mean_max, key='class_mean')
        std = st.number_input('985 radiance std maximum', min_value=0., value=draft.radiance_std_max, key='class_std')
    with c:
        combine = st.selectbox('When both instruments are enabled', ['either', 'both'], index=['either', 'both'].index(draft.combine),
                               format_func=lambda v: 'Either may establish clear sky' if v == 'either' else 'Both must establish clear sky', key='class_combine')
        st.caption('ASI uses window-mean cloud percentages. Each instrument passes when both of its finite metrics are at or below their maxima. Missing required evidence is uncertain. No coverage or uncertainty gate is applied.')
    if not use_asi and not use_rad:
        st.warning('Enable at least one instrument to classify cases.')
        st.stop()
    rules = ClassificationRules(window, use_asi, use_rad, combine, zenith, total, mean, std)
    try:
        store = ReviewStore(loaded['output'])
        overrides, revision = store.snapshot()
        preview = classify(loaded['cases'], rules, overrides)
    except Exception as exc:
        st.error('Could not read classification data: '+str(exc))
        st.stop()
    counts = preview.category.value_counts()
    for column, category in zip(st.columns(3), ('clear_sky', 'not_clear_sky', 'uncertain')):
        column.metric(category.replace('_', ' ').title(), int(counts.get(category, 0)))
    review_plot(preview, rules, loaded['image_root'], store)
    st.caption(f'{int(preview.classification_source.eq("manual").sum())} persistent manual overrides applied. Review revision {revision}.')
    with st.expander('Manual review history'):
        history = store.history()
        st.dataframe(history, **plotly_size_kwargs(st.dataframe))
        st.download_button('Download review history', history.to_csv(index=False), 'manual_review_history.csv', 'text/csv')
    if st.button('Apply classification and open dashboard', type='primary'):
        try:
            if fingerprint(loaded['master']) != loaded['master_hash']:
                raise ValueError('Master changed on disk; reload master data before applying')
            classified, path = save_run(loaded['master'], loaded['cases'], rules, store)
            st.session_state.cloud_active = dict(cases=classified, path=str(path), rules=asdict(rules))
        except Exception as exc:
            st.error('Classification was not saved: '+str(exc))
        else:
            st.rerun()
    st.stop()

