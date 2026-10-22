"""Classification-first Streamlit workflow and satellite review."""
from spectralBands import available_ch2_bands
from dataclasses import asdict
import json
from pathlib import Path

import pandas as pd
import streamlit as st

import dashboard_data as data
import dashboard_plots as plots
from dashboard_classification import (ClassificationRules, ReviewStore, classify, fingerprint,
                                      prepare_master, save_run, satellite_inventory, match_satellite_images,
                                      saved_catalogs, restore_saved_catalog)
from dashboard_satellite import generate_satellite_image
from dashboard_vertical import plotly_size_kwargs
from dashboard_scatter import persistent_scatter


@st.cache_data(show_spinner=False, ttl=60)
def read_satellite_inventory(root):
    return satellite_inventory(root)


def inspect_case(frame, image_root, store, key, on_review=None):
    """Select on the scatter or use the list for cases with missing radiance."""
    labels = dict(zip(frame.case_id, frame.sounding_time.map(data.case_label)))
    selected_key = key+'_case'
    if st.session_state.get(selected_key) not in labels:
        st.session_state[selected_key] = frame.case_id.iloc[0]
    def request_image():
        st.session_state[key+'_image_request'] = st.session_state[selected_key]
    case = st.selectbox('Inspect case / satellite image', list(labels), format_func=labels.get, key=selected_key, on_change=request_image)
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
        inventory = read_satellite_inventory(image_root) if Path(image_root).exists() else []
        result = match_satellite_images(inventory, row.sounding_time, row.get('retrieval_time'), tolerance)
        matches = result['matches']
        request = st.session_state.pop(key+'_image_request', None)
        attempt_key = (image_root, str(case), str(row.sounding_time))
        attempts = st.session_state.setdefault('satellite_generation_attempts', {})
        retry = False
        if not matches:
            retry = st.button('Retry satellite generation' if attempt_key in attempts else 'Generate satellite image',
                              key=key+'_generate_'+case)
        if not matches and (retry or (request == case and attempt_key not in attempts)):
            # Record before launching: ordinary Streamlit reruns must not repeat downloads.
            attempts[attempt_key] = {'ok': False, 'log': 'Generation started.'}
            with st.spinner('Generating satellite image for '+data.case_label(row.sounding_time)+'…'):
                try:
                    log = generate_satellite_image(row.sounding_time, image_root)
                    attempts[attempt_key] = {'ok': True, 'log': log}
                except Exception as exc:
                    attempts[attempt_key] = {'ok': False, 'log': str(exc)}
            read_satellite_inventory.clear()
            inventory = read_satellite_inventory(image_root) if Path(image_root).exists() else []
            result = match_satellite_images(inventory, row.sounding_time, row.get('retrieval_time'), tolerance)
            matches = result['matches']
        if attempt_key in attempts:
            outcome = attempts[attempt_key]
            if not outcome['ok'] and not matches:
                st.error('Satellite generation failed. See the output below; use Retry satellite generation after resolving the error.')
            with st.expander('Satellite generation output', expanded=not outcome['ok'] and not matches):
                st.code(outcome['log'], language='text')
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


def plot_filter_controls(preview, source, key):
    """Cache observed PWV independently of classification thresholds/retrievals."""
    from sounding_pwv import catalog_pwv, pwv_cache_path, COLUMNS
    with st.expander('Filter plotted cases', expanded=True):
        st.caption('Selections combine: a case must match every active filter. Multiple choices within one filter are alternatives. These filters only change the plot and case selector; classification still applies to all master cases.')
        if source is not None:
            cache_path = pwv_cache_path(source['master'], source['output'])
            cache_key = "observed_pwv:"+json.dumps([source["master"], source.get("master_hash"), source.get("sonde_root", ""), str(cache_path)])
            refresh = st.button('Refresh sounding PWV', key=key+'_refresh_pwv',
                                help='Checks for new or changed soundings; unchanged files use the saved PWV cache.')
            if cache_key not in st.session_state or refresh:
                progress = st.progress(0., text='Computing observed-sounding PWV for all cases…')
                try:
                    table = catalog_pwv(source['cases'], source['master'], source.get('sonde_root', ''), cache_path,
                        progress=lambda n, total, reused: progress.progress(n/total, text=f'PWV {n:,}/{total:,} cases · {reused:,} cached'))
                    st.session_state[cache_key] = table
                except Exception as exc:
                    st.error('PWV catalog could not be saved: '+str(exc))
                finally:
                    progress.empty()
            table = st.session_state.get(cache_key)
            if table is not None:
                preview = preview.drop(columns=COLUMNS, errors='ignore').merge(table[['case_id']+COLUMNS], on='case_id', how='left', validate='one_to_one')
                st.caption(f'PWV available for {preview.pwv_mm.notna().sum():,}/{len(preview):,} cases. Cache: {cache_path}')
                st.download_button('Download sounding PWV catalog', table.to_csv(index=False), 'sounding_pwv.csv', 'text/csv', key=key+'_pwv_download')
                issues = table.loc[table.pwv_status != 'ok']
                if len(issues):
                    st.caption('Missing/incomplete PWV cases remain visible unless excluded with the PWV filter. Partial-column integrals are recorded separately in the download.')
                    if st.checkbox('Show PWV coverage / read problems', key=key+'_pwv_problems'):
                        st.dataframe(issues[['case_id', 'pwv_status', 'pwv_observed_mm', 'pwv_top_hpa', 'pwv_error']], hide_index=True)
        a, b, c = st.columns(3)
        with a:
            seasons = st.multiselect('Seasons', data.GROUP_ORDERS['Season'], default=data.GROUP_ORDERS['Season'], key=key+'_seasons')
        with b:
            hours = st.multiselect('Time of day (UTC)', data.GROUP_ORDERS['Time of day (UTC)'], default=data.GROUP_ORDERS['Time of day (UTC)'], key=key+'_hours')
        with c:
            options = ['Clear sky', 'Not clear sky', 'Uncertain', 'Disabled', 'Unknown']
            asi = st.multiselect('ASI classifications', options, default=options, key=key+'_asi_filter',
                                help='ASI state from the current window and ASI thresholds. Disabled means ASI is not enabled for classification.')
        limits = None
        missing = False
        if st.checkbox('Filter by observed PWV', key=key+'_pwv_enabled'):
            lo, hi = st.columns(2)
            lower = lo.number_input('Minimum PWV (mm)', min_value=0., value=0., step=1., key=key+'_pwv_min')
            upper = hi.number_input('Maximum PWV (mm)', min_value=0., value=100., step=1., key=key+'_pwv_max')
            missing = st.checkbox('Include missing / incomplete PWV', value=False, key=key+'_pwv_missing')
            st.caption('Inclusive range; observed surface-to-sounding-top column, independent of the dashboard layer. Requires ascent to ≤100 hPa, no humidity gap >100 hPa, and no missing launch layer >20 hPa.')
            if lower > upper:
                st.warning('Minimum PWV must not exceed maximum PWV.')
                return preview.iloc[:0].copy()
            limits = (lower, upper)
        filtered = data.filter_radiance_cases(preview, seasons, hours, asi, limits, missing)
        st.caption(f'{len(filtered):,} / {len(preview):,} cases match the plot filters.')
        return filtered


def review_plot(preview, rules, image_root, store, key='classification', on_review=None, source=None, collection_key=None):
    preview = plot_filter_controls(preview, source, key)
    if preview.empty:
        st.info('No cases match these filters. Broaden the selections to show cases.')
        return
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
            figure.update_layout(clickmode='event', dragmode='lasso' if collection_key else 'zoom')
            event = persistent_scatter(figure, key=key+'_scatter',
                                       scope=source['master'] if source else '', collection_mode=bool(collection_key))
            if event:
                picked = event.get('case_id')
                token = event.get('token')
                if collection_key and st.session_state.get(key+'_last_collection_event') != token:
                    # Plot selection is provisional; inspection never changes membership.
                    pending = set(event.get('case_ids', [])) & set(preview.case_id)
                    st.session_state[key+'_pending_collection_cases'] = sorted(pending)
                    st.session_state[key+'_last_collection_event'] = token
                if st.session_state.get(key+'_last_event') != token and picked in set(preview.case_id):
                    st.session_state[key+'_case'] = picked
                    st.session_state[key+'_image_request'] = picked
                    st.session_state[key+'_last_event'] = token
            st.caption(f'{len(plotted):,} / {len(preview):,} filtered cases have finite radiance mean/std. Missing-coordinate cases remain accessible in the filtered case selector. Click a point to inspect it.')
        else:
            st.info('Radiance summaries for this window are absent. All cases remain available in the case selector; enabled radiance evidence will be uncertain.')
        if collection_key:
            pending = st.session_state.get(key+'_pending_collection_cases', [])
            if pending:
                st.caption(f'{len(pending):,} cases selected on the plot; not yet added.')
                if st.button('Add selected cases to collection', key=key+'_add_selected'):
                    st.session_state[collection_key] = sorted(set(st.session_state.get(collection_key, [])) | set(pending))
                    st.session_state[key+'_pending_collection_cases'] = []
        st.caption('The shaded rectangle represents the radiance criterion only. With an “either” rule, ASI may also establish clear sky outside that rectangle. Manual decisions always take precedence.')
    with right:
        inspect_case(preview, image_root, store, key, on_review)
        if collection_key:
            inspected = st.session_state.get(key+'_case')
            if st.button('Add to collection', key=key+'_add_case', disabled=inspected not in set(preview.case_id),
                         help='Add only the currently inspected case. Selecting a case or viewing its image does not add it.'):
                st.session_state[collection_key] = sorted(set(st.session_state.get(collection_key, [])) | {inspected})


def classification_gate(default_manifest, default_root, default_sonde, default_images, default_output):
    """Return a frozen classified dataset only after its compact manifest is saved."""
    with st.sidebar:
        st.header('Master data and saved classifications')
        output = st.text_input('Classification and manual-review directory', default_output,
                               help='Saved catalogs in this directory appear on the opening page. Use a persistent directory so catalogs and manual overrides carry forward.')
        with st.form('source_form'):
            manifest = st.text_input('Master manifest CSV (legacy manifests can be imported)', default_manifest)
            root = st.text_input('Universal retrieval directory', default_root, help='Searches this directory recursively, including older group folders. Use the same UNIVERSAL_RETRIEVAL_DIR in every worker container.')
            catalog = ''  # Completion is checked against live files for clear cases.
            sonde = st.text_input('Sounding search directory (optional)', default_sonde)
            image_root = st.text_input('Satellite PNG directory', default_images,
                                       help='Search includes subdirectories. Click Load / refresh master data to apply a changed path; it must be visible inside the app/container.')
            load = st.form_submit_button('Load / refresh master data', type='primary')
    if not st.session_state.get('cloud_active') or load:
        st.subheader('Open a saved classification or case collection')
        try:
            catalogs, errors = saved_catalogs(output)
        except OSError as exc:
            catalogs, errors = [], [dict(path=output, error=str(exc))]
        if catalogs:
            choices = {item['path']: item for item in catalogs}
            chosen = st.selectbox('Saved classification catalog', list(choices),
                                  format_func=lambda path: choices[path]['label'])
            selection = choices[chosen]
            st.caption('Master: '+selection['master'])
            st.caption('Saved: '+selection['created']+' · Window: '+selection['rules']['window']+
                       ' · Instrument rule: '+selection['rules']['combine'])
            st.caption('Manual collections retain their chosen membership regardless of cloud classification. Saved classifications select clear-sky cases.')
            if st.button('Open selected catalog in dashboard', type='primary'):
                try:
                    restored, active, updated = restore_saved_catalog(chosen)
                    restored.update(root=str(Path(root).expanduser().resolve()), catalog='',
                                    sonde_root=str(Path(sonde).expanduser()) if sonde else '',
                                    image_root=str(Path(image_root).expanduser()))
                    st.session_state.cloud_loaded = restored
                    st.session_state.cloud_active = active
                    st.session_state.cloud_draft_rules = active['rules']
                    st.session_state.dashboard_view = 'Case catalog'
                    for key in ('loaded_source', 'retrieval_todo_key', 'class_window', 'class_asi', 'class_rad',
                                'class_zenith', 'class_total', 'class_mean', 'class_std', 'class_combine'):
                        st.session_state.pop(key, None)
                    if updated:
                        st.session_state.catalog_open_notice = 'Newer manual reviews were applied and an updated classification catalog was saved using the selected thresholds.'
                except Exception as exc:
                    st.error('Could not open the saved classification: '+str(exc))
                else:
                    st.rerun()
        else:
            st.info('No saved classification catalogs found in '+str(Path(output).expanduser())+'. You can create one below after loading a master manifest.')
        if errors:
            with st.expander('Catalog discovery errors'):
                st.dataframe(pd.DataFrame(errors), hide_index=True)
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
            from case_collections import read_bands
            from retrieval_todo import expected_models
            import config
            st.session_state.new_group_models = read_bands(active['path'], expected_models(config.RETRIEVAL_TODO_BANDS))
            st.session_state.cloud_draft_rules = active['rules']
            st.session_state.collection_mode = active.get('kind') == 'manual_collection'
            if st.session_state.collection_mode:
                st.session_state['collection_draft:'+loaded['master']] = active['cases'].case_id.tolist()
            st.session_state.pop('cloud_active', None)
            st.rerun()
        if active and st.button('Choose another saved classification'):
            st.session_state.pop('cloud_active', None)
            st.rerun()
    if active:
        notice = st.session_state.pop('catalog_open_notice', None)
        if notice:
            st.info(notice)
        st.caption('Classification snapshot: '+active['path'])
        return loaded, active
    from case_collections import save_collection, restore_collection, save_bands
    from retrieval_todo import expected_models
    import config
    collection_mode = st.checkbox('Build a manual case collection', key='collection_mode')
    collection_key = 'collection_draft:'+loaded['master']
    group_models = st.multiselect('Bands included in this group', expected_models(available_ch2_bands()),
        default=expected_models(config.RETRIEVAL_TODO_BANDS), key='new_group_models')
    if collection_mode:
        st.info('Click points to inspect satellite imagery, then press Add to collection. For lasso/box selections, press Add selected cases to collection. Only confirmed additions accumulate across filters. Remove cases below. Membership is independent of cloud classification.')
        collection_name = st.text_input('Collection name', key='collection_name')
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
    review_plot(preview, rules, loaded['image_root'], store, source=loaded,
                collection_key=collection_key if collection_mode else None)
    if collection_mode:
        chosen = st.session_state.get(collection_key, [])
        labels = dict(zip(preview.case_id, preview.sounding_time.map(data.case_label)))
        editor_key = 'collection_edit:'+str(hash(tuple(chosen)))
        def remove_collection_cases():
            st.session_state[collection_key] = st.session_state[editor_key]
        st.multiselect('Selected collection cases (remove to exclude)', chosen, default=chosen,
                       format_func=labels.get, key=editor_key, on_change=remove_collection_cases)
        st.caption(f'{len(chosen):,} selected cases, including cases hidden by current plot filters.')
        if st.button('Clear selected cases'):
            st.session_state[collection_key] = []
            st.rerun()
        if st.button('Save collection and open dashboard', type='primary'):
            try:
                if fingerprint(loaded['master']) != loaded['master_hash']:
                    raise ValueError('Master changed; reload before saving')
                path = save_collection(loaded['master'], loaded['cases'], chosen, collection_name, rules, loaded['output'], group_models)
                _, active, _ = restore_collection(path)
                st.session_state.cloud_active = active
                st.session_state.dashboard_view = 'Case catalog'
            except Exception as exc:
                st.error('Collection was not saved: '+str(exc))
            else:
                st.rerun()
        st.stop()
    st.caption(f'{int(preview.classification_source.eq("manual").sum())} persistent manual overrides applied. Review revision {revision}.')
    with st.expander('Manual review history'):
        history = store.history()
        st.dataframe(history, **plotly_size_kwargs(st.dataframe))
        st.download_button('Download review history', history.to_csv(index=False), 'manual_review_history.csv', 'text/csv')
    if st.button('Apply classification and open dashboard', type='primary'):
        try:
            if fingerprint(loaded['master']) != loaded['master_hash']:
                raise ValueError('Master changed on disk; reload master data before applying')
            if not group_models:
                raise ValueError('Choose at least one band')
            classified, path = save_run(loaded['master'], loaded['cases'], rules, store)
            save_bands(path, group_models)
            st.session_state.cloud_active = dict(cases=classified, path=str(path), rules=asdict(rules))
            st.session_state.dashboard_view = 'Case catalog'
        except Exception as exc:
            st.error('Classification was not saved: '+str(exc))
        else:
            st.rerun()
    st.stop()




