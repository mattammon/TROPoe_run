"""Launch: python -m streamlit run TROPoe_APP.py"""
from pathlib import Path
import logging

import numpy as np
import pandas as pd
import streamlit as st

import dashboard_data as data
import dashboard_plots as plots
from dashboard_vertical import plotly_size_kwargs, render_vertical
from dashboard_catalog import render_catalog
from catalog_retrievals import create_catalog
from dashboard_setup import classification_gate, review_plot
from dashboard_classification import ClassificationRules, ReviewStore, save_run, fingerprint
from retrieval_todo import expected_models, pending_retrievals, save_todo

st.set_page_config(page_title='TROPoe • Retrieval Explorer', page_icon='🌤️', layout='wide')
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
LOG = logging.getLogger(__name__)
STRETCH = {'width': 'stretch'} if tuple(int(x) for x in st.__version__.split('.')[:2]) >= (1, 50) else {'use_container_width': True}

# File signatures invalidate the cache when a file changes. A new source load
# invalidates the directory scan; missing clear-sky pairs are saved as a to-do CSV.
@st.cache_data(show_spinner=False, max_entries=20000)
def read_profile(signature, record, time, source, no_model, loader_schema=3):
    return data.load_retrieval(signature, record, time, source, no_model)


@st.cache_data(show_spinner=False, max_entries=5000)
def read_observation(signature):
    return data.load_sounding(signature)


def display_chart(fig, name):
    st.plotly_chart(fig, **plotly_size_kwargs(st.plotly_chart), key=name, config={'displaylogo': False, 'toImageButtonOptions': {'format': 'png', 'scale': 2}})
    with st.expander('Export this figure'):
        if st.button('Prepare standalone HTML', key='prepare_'+name):
            st.download_button('Download interactive figure', fig.to_html(include_plotlyjs=True),
                               file_name=name+'.html', mime='text/html', key='html_'+name)
        st.caption('Use the camera icon for PNG. Standalone HTML includes Plotly and works offline.')


def download_table(label, df, filename, key):
    df = data.display_cases(df, case_labels, keep_id=True)
    st.download_button(label, df.to_csv(index=False).encode(), filename, 'text/csv', key=key)


try:
    import config
    default_root = str(Path(config.RETRIEVAL_DIR)/config.GROUP_NAME)
    default_manifest = getattr(config, 'CLOUD_MASTER_MANIFEST', None) or config.CLOUD_SCREEN_MANIFEST or ''
    default_sonde = config.SONDE_DIR
    default_images = config.SAT_IMAGERY_DIR
    default_output = getattr(config, 'CLOUD_CLASSIFICATION_DIR', str(Path(config.DATA_DIR)/'cloud_classification'/config.SITE))
except (ImportError, AttributeError):
    default_root, default_manifest, default_sonde, default_images = '', '', '', ''
    default_output = str(Path.home()/'tropoe_classifications')

st.markdown('### TROPoe / Retrieval Explorer')
st.caption('Classify cloud conditions, review satellite imagery, and compare retrievals.')
use_saved = st.sidebar.checkbox('Use saved retrieval catalog (skip scan)', value=True,
    help='Load this retrieval directory’s saved catalog without checking retrieval files. Refresh explicitly after new retrievals finish.')
source, active = classification_gate(default_manifest, default_root, default_sonde, default_images, default_output)
all_cases = active['cases']
cases = all_cases.loc[all_cases.category == 'clear_sky'].copy()
rules = ClassificationRules(**active['rules'])
todo_path = getattr(config, 'RETRIEVAL_TODO_MANIFEST', None)
todo_bands = getattr(config, 'RETRIEVAL_TODO_BANDS', list(range(1, 19)))
todo_tolerance = getattr(config, 'RETRIEVAL_TODO_TOLERANCE_SECONDS', 60.)
refresh_requested = st.sidebar.button('Refresh retrieval catalog and to-do')
if refresh_requested:
    st.session_state.pop('loaded_source', None)
    st.session_state.pop('retrieval_todo_key', None)
scope = ('shared_catalog_v2', active['path'], source['root'], tuple(todo_bands), todo_tolerance, use_saved)
if st.session_state.get('loaded_source', {}).get('scope') != scope:
    saved_inventory = use_saved and not refresh_requested
    catalog_dir = Path(source['root'])/'catalog'
    if saved_inventory and not (catalog_dir/'summary.json').is_file():
        st.info('No retrieval catalog exists for this directory yet. The classification is saved. '
                'Click Refresh retrieval catalog and to-do in the sidebar to build the first inventory. '
                'The first scan validates each retrieval file and may take time; progress will be displayed.')
        st.stop()
    status = st.status('Loading saved retrieval catalog…' if saved_inventory else 'Updating retrieval catalog…', expanded=True)
    def report_catalog(message):
        status.update(label=message)
        LOG.info('Retrieval catalog: %s', message)
    try:
        summary = {}
        if not Path(source['root']).exists():
            index = pd.DataFrame(columns=['file', 'model', 'profile_index', 'time', 'status'])
            index_errors = pd.DataFrame()
            catalog_dir = None
        else:
            catalog_dir, summary, scanned_files = create_catalog(
                source['root'], active['path'], todo_bands, category='clear_sky',
                tolerance_seconds=todo_tolerance, progress=report_catalog, reuse_inventory=saved_inventory)
            report_catalog('Reading updated retrieval profiles…')
            index, index_errors = data.read_index(source['root'], catalog=catalog_dir/'profiles.csv')
            file_errors = pd.DataFrame([f for f in scanned_files if f.get('error')])
            if not file_errors.empty:
                index_errors = pd.concat([index_errors, file_errors], ignore_index=True)
    except Exception as exc:
        status.update(label='Retrieval catalog could not be loaded', state='error')
        st.error('Could not load/update the retrieval catalog; no new to-do manifest was written. '
                 'Use Refresh retrieval catalog and to-do to create or repair a saved catalog. Details: '+str(exc))
        st.stop()
    status.update(label='Retrieval inventory ready', state='complete', expanded=False)
    st.session_state.loaded_source = dict(index=index, errors=index_errors, manifest=source['master'],
                                         root=source['root'], catalog=str(catalog_dir/'profiles.csv') if catalog_dir else '',
                                         sonde_root=source['sonde_root'], scope=scope, saved_inventory=saved_inventory,
                                         inventory_time=summary.get('inventory_updated_utc', 'unknown'))
loaded = st.session_state.loaded_source
index, index_errors = loaded['index'], loaded['errors']
catalog_models = expected_models(todo_bands)
todo_key = (scope, str(todo_path), tuple(todo_bands), todo_tolerance)
if st.session_state.get('retrieval_todo_key') != todo_key:
    try:
        todo = pending_retrievals(cases, index, todo_bands, active['path'], source['root'], todo_tolerance)
        if todo_path:
            save_todo(todo_path, todo)
        st.session_state.retrieval_todo = todo
        st.session_state.retrieval_todo_key = todo_key
    except Exception as exc:
        st.error('Could not write the retrieval to-do manifest: '+str(exc))
        st.stop()
todo = st.session_state.retrieval_todo
st.caption(f"{len(cases):,} clear-sky cases out of {len(all_cases):,} classified cases. Retrieval comparisons load only clear-sky cases.")
st.caption(f"Master: {source['master']} · Classification: {active['path']}")
if loaded.get('saved_inventory'):
    st.caption('Using inventory saved '+loaded['inventory_time']+'. Retrieval files were not rescanned. '
               'summary.json, case counts and the to-do list now describe the active classification. '
               'Refresh the catalog to include new or removed retrievals.')
if loaded['catalog']:
    st.caption('Retrieval catalog: '+str(Path(loaded['catalog']).parent/'summary.json'))
with st.sidebar:
    st.download_button('Download active classification', Path(active['path']).read_bytes(), 'classification.csv', 'text/csv')
    st.caption(f'Retrieval to-do: {todo.case_id.nunique():,} cases · {len(todo):,} missing case–band pairs (Ch1 + {len(todo_bands)} Ch2 bands).')
    st.caption('Saved to: '+str(todo_path) if todo_path else 'Automatic to-do saving is disabled in config.py.')
    st.download_button('Download retrieval to-do', todo.to_csv(index=False), 'retrieval_todo.csv', 'text/csv')

case_labels = dict(zip(all_cases.case_id, all_cases.sounding_time.map(data.case_label)))
with st.sidebar:
    st.header('Bands')
    # One immediate selector controls the grid, comparisons, and exported statistics.
    models = st.multiselect('Bands', catalog_models, default=catalog_models,
                            key='selection_'+active['path']+'bands')
from dashboard_satellite_panel import style_satellite_panel
style_satellite_panel()
show_satellite = st.checkbox('Show satellite imagery panel', value=False, key='show_dashboard_satellite')
if show_satellite:
    dashboard_main, satellite_side = st.columns([3, 1.4], gap='large')
    with satellite_side:
        from dashboard_satellite_panel import render_satellite_panel
        with st.container(key='satellite_dock'):
            render_satellite_panel(all_cases, source)
else:
    dashboard_main = st.container()
with dashboard_main:
    view = st.selectbox('Plot', ['Case catalog', 'Vertical profiles', 'RMSE comparisons', 'Vertical errors', 'Taylor diagram',
                                'Information content', 'DFS vs RMSE', '985 radiance scatter', 'Aerosol / AOD', 'Cloud diagnostics'], key='dashboard_view')
    if view == 'Aerosol / AOD':
        from dashboard_aod import render_aod
        render_aod(cases, index, models, loaded, config.AOD_DIR, config.AOD_DATASTREAM,
                   read_profile, read_observation, display_chart, download_table)
        st.stop()
    if view == 'Case catalog':
        render_catalog(cases, index, models, case_labels, todo_tolerance, index_errors,
                       catalog_models, 'selection_'+active['path']+'bands')
        st.stop()
    if view == '985 radiance scatter':
        from dataclasses import asdict
        store = ReviewStore(source['output'])
        def refresh_review_snapshot():
            if fingerprint(source['master']) != source['master_hash']:
                raise ValueError('Master changed; reload the master before applying')
            classified, path = save_run(source['master'], source['cases'], rules, store)
            st.session_state.cloud_active = dict(cases=classified, path=str(path), rules=asdict(rules))
        review_plot(all_cases, rules, source['image_root'], store, key='dashboard_review', on_review=refresh_review_snapshot, source=source)
        download_table('Download classified radiance cases', all_cases, 'radiance_cases.csv', 'radiance_csv')
        st.stop()

    if cases.empty:
        st.info('No cases are classified as clear sky. The retrieval to-do manifest is empty. Use the radiance scatter or classification editor to review cases.')
        st.stop()

    if index.empty:
        st.warning('No readable retrieval profiles were found. Inspect the scan errors below, or select the 985 radiance scatter to explore the manifest.')
        st.dataframe(index_errors, **STRETCH)
        st.stop()

    with st.sidebar:
        st.header('Comparison')
        # Snapshot-specific keys prevent stale category selections after reclassification.
        prefix = 'selection_'+active['path']
        with st.form('filters_'+prefix):
            dates = st.date_input('Sounding date range (UTC)',
                                  (cases.sounding_time.min().date(), cases.sounding_time.max().date()),
                                  min_value=cases.sounding_time.min().date(), max_value=cases.sounding_time.max().date())
            selections = {}
            for key, label in [('category', 'Cloud category'), ('asi_state', 'ASI classification'), ('radiance_state', '985 radiance classification')]:
                choices = sorted(cases[key].unique())
                selections[key] = st.multiselect(label, choices, default=choices)
            rules = ClassificationRules(**active['rules'])
            window = rules.window
            bounds = {}
            include_missing = True
            radiance_limits = {'radiance_{}_radiance_mean': (rules.radiance_mean_max, rules.use_radiance),
                               'radiance_{}_radiance_std': (rules.radiance_std_max, rules.use_radiance)}
            st.caption('Cloud classifications come from the saved snapshot. Use Review images / change classification thresholds above to create a new snapshot.')
            paired = st.checkbox('Compare the same cases across selected bands', value=True,
                                 help='Accuracy and DFS each use their own common cohort. DFS vs RMSE uses their intersection.')
            tolerance = st.number_input('Maximum retrieval time offset (seconds)', min_value=0., max_value=449., value=60.,
                                        help='Compared to manifest retrieval_time, using NetCDF timestamps.')
            information_source = st.selectbox('DFS diagnostic source', ['auto', 'kernel', 'cdfs'])
            no_model = st.checkbox('Use *_no_model DFS diagnostics', value=False)
            st.form_submit_button('Apply filters', type='primary')

    if not models:
        st.info('Select at least one band in the sidebar.')
        st.stop()
    if len(dates) != 2:
        st.info('Choose both endpoints of the date range.')
        st.stop()
    missing_columns = [c for c in bounds if c not in cases]
    if missing_columns:
        st.warning('The selected metric is absent from this manifest: '+', '.join(missing_columns))
        if not include_missing and (view != '985 radiance scatter' or any(not c.startswith('radiance_') for c in missing_columns)):
            st.stop()
    bounds = {k: v for k, v in bounds.items() if k in cases}

    selected = data.filter_cases(cases, dates, selections, bounds, include_missing)
    if selected.empty:
        st.warning('No cases match these filters. Broaden the dates or cloud filters.')
        st.stop()

    # Analysis controls do not cause disk rereads: native profiles are cached.
    rmse_style = st.radio('RMSE view', ['Distributions', 'Timeline', 'Case heatmap'], horizontal=True) if view == 'RMSE comparisons' else None
    a, b, c, d = st.columns([2, 1, 1, 1])
    variable = 'T' if view in ('Vertical profiles', 'Vertical errors', 'Taylor diagram', 'DFS vs RMSE', 'Information content') or rmse_style == 'Distributions' else a.selectbox('Variable', ['T', 'q'], format_func=lambda v: data.VARIABLES[v][0])
    bottom = b.number_input('Layer bottom (km AGL)', min_value=0., max_value=19.9, value=0.0, step=0.1)
    top = c.number_input('Layer top (km AGL)', min_value=0.1, max_value=20., value=1.5, step=0.1)
    spacing = d.selectbox('Vertical bin size (m)', [25, 50, 100, 200, 250, 500], index=2)
    if bottom >= top:
        st.warning('Layer top must exceed layer bottom.')
        st.stop()
    edges = np.linspace(bottom, top, max(2, int(np.ceil((top-bottom)*1000/spacing)))+1)

    info_mode, info_difference = None, False
    if view == 'Information content':
        info_mode = st.radio('Information view', ['Cumulative profiles', 'Density profiles', 'Layer distributions'], horizontal=True)
        if info_mode != 'Layer distributions':
            info_difference = st.checkbox('Shade differences from Ch1', value=False, key='info_difference')
            if info_difference:
                st.caption('Ch1 retains its actual values. Other bands show median same-case, same-source differences: red above Ch1, blue below. Ch1 is loaded as a reference even if deselected.')
    load_models = list(dict.fromkeys(models + ['Ch1'])) if view == 'Vertical errors' or info_difference else models
    problems = []
    matches = data.match_cases(selected, index, load_models, tolerance)
    shared = matches.loc[matches.file.ne('')].duplicated(['model', 'file', 'profile_index'], keep=False)
    if shared.any():
        st.warning('Some manifest cases match the same retrieval record. Inspect the matched-record catalog before treating cases as independent samples.')
    profiles, observations = {}, {}
    matched = matches.loc[matches.file.ne('')]
    st.caption(f'{len(selected):,} filtered cases × {len(load_models)} bands = {len(matches):,} possible case–band pairs; '
               f'{len(matched):,} pairs have a time-matched retrieval record. A file can contain multiple records.')
    if len(matched):
        progress = st.progress(0, text='Loading matched retrieval records…')
        for n, row in enumerate(matched.itertuples(), 1):
            try:
                profiles[(row.case_id, row.model)] = read_profile(data.signature(row.file), row.profile_index,
                                                                 row.matched_time, information_source, no_model)
            except Exception as exc:
                problems.append(dict(case_id=row.case_id, model=row.model, stage='retrieval load', reason=str(exc)))
                LOG.warning('%s / %s: %s', row.case_id, row.model, exc)
            if n % 25 == 0 or n == len(matched):
                progress.progress(n/len(matched), text=f'Loading matched retrieval {n:,} / {len(matched):,}')
        progress.empty()
    sounding_progress = st.progress(0, text='Loading radiosondes…')
    for n, row in enumerate(selected.itertuples(), 1):
        try:
            path = data.sounding_path(row.sounding_file, Path(loaded['manifest']).parent, loaded['sonde_root'])
            observations[row.case_id] = read_observation(data.signature(path))
        except Exception as exc:
            problems.append(dict(case_id=row.case_id, model='Radiosonde', stage='sounding load', reason=str(exc)))
            LOG.warning('%s / radiosonde: %s', row.case_id, exc)
        if n % 25 == 0 or n == len(selected):
            sounding_progress.progress(n/len(selected), text=f'Loading radiosonde {n:,} / {len(selected):,}')
    sounding_progress.empty()

    if view == 'Vertical errors':
        render_vertical(selected, models, profiles, observations, edges, display_chart, download_table, problems)
        st.stop()

    if view == 'Taylor diagram':
        st.caption('Temperature and water vapor use the same layer and band selection. '
                   'Each variable uses its own available/common cohort according to the comparison setting. '
                   'Angle encodes correlation; radius is retrieved / observed standard deviation. '
                   'Dotted arcs show centered RMSE divided by observed standard deviation, which excludes bias.')
        st.caption('Only nonnegative correlations are plotted; negative correlations remain in the statistics tables. '
                   'The shared legend toggles each band in both panels.')
        analyses = {v: data.build_analysis(selected, models, profiles, observations, v, edges, paired) for v in ('T', 'q')}
        figure, tables = plots.taylor_pair(analyses, models)
        display_chart(figure, 'taylor_both')
        for column, v in zip(st.columns(2), ('T', 'q')):
            with column:
                st.write(data.VARIABLES[v][0]+' statistics')
                if analyses[v]['metrics'].empty:
                    st.info('No complete '+data.VARIABLES[v][0]+' comparisons in this layer.')
                st.dataframe(tables[v], **STRETCH, hide_index=True)
                download_table('Download '+data.VARIABLES[v][0]+' Taylor statistics', tables[v],
                               'taylor_'+v+'_statistics.csv', 'taylor_csv_'+v)
        with st.expander('Load errors and comparison settings'):
            if problems:
                st.dataframe(pd.DataFrame(problems), **STRETCH)
            download_table('Download Taylor comparison settings', pd.DataFrame([dict(
                classification_manifest=active['path'], bands=','.join(models),
                start_date=str(dates[0]), end_date=str(dates[1]), layer_bottom_km=bottom,
                layer_top_km=top, bins=len(edges)-1, paired=paired, tolerance_seconds=tolerance)]),
                'taylor_settings.csv', 'taylor_settings_csv')
        st.stop()

    if view == 'DFS vs RMSE':
        individual = st.checkbox('Show individual cases', value=True, key='dfs_show_individual')
        st.caption('This toggle controls case points in both panels. Diamonds show band/source means; '
                   'bars show ±1 population standard deviation across the plotted pairs.')
        analyses = {v: data.build_analysis(selected, models, profiles, observations, v, edges, paired) for v in ('T', 'q')}
        figure, tables = plots.dfs_rmse_pair(analyses, individual)
        display_chart(figure, 'dfs_rmse_both')
        for column, v in zip(st.columns(2), ('T', 'q')):
            with column:
                st.write(data.VARIABLES[v][0]+' statistics')
                st.dataframe(tables[v], **STRETCH)
                download_table('Download '+data.VARIABLES[v][0]+' DFS–RMSE summary', tables[v],
                               'dfs_rmse_'+v+'_summary.csv', 'dfs_rmse_csv_'+v)
                if not analyses[v]['metrics'].empty:
                    download_table('Download '+data.VARIABLES[v][0]+' case pairs', analyses[v]['metrics'].dropna(subset=['dfs']),
                                   'dfs_rmse_'+v+'_cases.csv', 'dfs_rmse_cases_'+v)
        st.stop()

    if view == 'Vertical profiles':
        if st.session_state.get('dashboard_case') in set(selected.case_id):
            st.session_state.dashboard_profile_case = st.session_state.dashboard_case
        elif st.session_state.get('dashboard_profile_case') not in set(selected.case_id):
            st.session_state.dashboard_profile_case = selected.case_id.iloc[0]
        def select_profile_case():
            st.session_state.dashboard_case = st.session_state.dashboard_profile_case
        case = st.selectbox('Case', selected.case_id.tolist(), format_func=case_labels.get,
                            key='dashboard_profile_case', on_change=select_profile_case)
        row = selected.set_index('case_id').loc[case]
        st.caption(f"{case_labels[case]} · {row.category} · ASI: {row.asi_state} · radiance: {row.radiance_state}")
        display_chart(plots.skewed_profile_pair(case, models, profiles, observations, (bottom, top)), 'profiles_both')
        from dashboard_diagnostics import case_diagnostic, rmsr_summary
        mode = st.radio('Case profile shading', ['Cumulative DFS', 'DFS density', '1-sigma uncertainty'], horizontal=True)
        diagnostics = []
        for column, v in zip(st.columns(2), ('T', 'q')):
            with column:
                fig, table, errors = case_diagnostic(case, profiles, models, v, edges, mode)
                display_chart(fig, 'case_diagnostic_'+v)
                download_table('Download '+data.VARIABLES[v][0]+' diagnostic', table,
                               'case_diagnostic_'+v+'.csv', 'case_diagnostic_csv_'+v)
                if not errors.empty:
                    diagnostics.append(errors)
        st.caption('DFS is remapped conservatively to the selected height bins; cumulative DFS starts at the layer bottom. Uncertainty is interpolated to bin centers without extrapolation. Missing diagnostics remain blank.')
        if diagnostics:
            with st.expander('Missing case diagnostics'):
                st.dataframe(pd.concat(diagnostics, ignore_index=True), **STRETCH, hide_index=True)
        rmsr, rmsr_fig = rmsr_summary(case, profiles, models)
        st.subheader('Spectral fit diagnostics by band')
        st.caption('RMSR, RMSA and gamma are read directly from the selected retrieval record. Ranked by RMSA, smallest first; missing RMSA values remain unranked.')
        left, right = st.columns(2)
        with left:
            st.dataframe(rmsr, **STRETCH, hide_index=True)
            download_table('Download spectral fit comparison', rmsr, 'case_rmsr.csv', 'case_rmsr_csv')
        with right:
            if rmsr.RMSA.notna().any():
                display_chart(rmsr_fig, 'case_rmsr')
            else:
                st.info('No scalar rmsa values are available for this case.')
        with st.expander('Source files and matched records'):
            st.dataframe(data.display_cases(matches.loc[matches.case_id == case], case_labels), **STRETCH)
        st.caption('Slanted grid lines indicate constant temperature or mixing ratio; bottom-axis labels apply along those lines. '
                   'Hover shows actual values. Height remains linear in km AGL: this is not a log-pressure thermodynamic diagram. '
                   'The shared legend toggles bands in both panels.')
        st.stop()

    if view == 'Information content':
        from dashboard_diagnostics import dfs_profile_panels
        for v in ('T', 'q'):
            st.subheader(data.VARIABLES[v][0])
            current = data.build_analysis(selected, models, profiles, observations, v, edges, paired)
            if info_difference and 'Ch1' not in models:
                reference = data.build_analysis(selected, ['Ch1'], profiles, observations, v, edges, paired=False)
                current['information'].update(reference['information'])
            if info_difference:
                available = current['information']
                current['information'] = {key: item for key, item in available.items()
                    if key[1] == 'Ch1' or ((key[0], 'Ch1') in available
                        and available[(key[0], 'Ch1')]['source'] == item['source'])}
            if not current['information']:
                st.info('No DFS profiles cover this layer for '+data.VARIABLES[v][0]+'.')
                continue
            if info_mode == 'Layer distributions':
                display_chart(plots.info_plot(current, info_mode), 'information_'+v)
            else:
                for source_number, (diagnostic, fig, counts) in enumerate(dfs_profile_panels(current, models, info_mode, info_difference)):
                    display_chart(fig, 'information_'+v+'_'+str(source_number))
                    with st.expander(data.VARIABLES[v][0]+' · '+diagnostic+' sample counts'):
                        st.dataframe(counts, **STRETCH, hide_index=True)
                        st.caption('Zero cases means no valid matching Ch1/source pairs in difference mode; those cells are blank.')
            if info_mode == 'Cumulative profiles':
                heights, per_case = plots.dfs_height95(current)
                st.caption('Black ticks show mean full-column 95% DFS height; ticks outside the selected layer are not clamped. Difference-mode ticks and table use the same paired cohort for each band.')
                st.dataframe(heights, **STRETCH, hide_index=True)
                download_table('Download '+v+' full-column DFS heights', per_case, 'dfs_height95_'+v+'.csv', 'dfs_h95_'+v)
            download_table('Download '+v+' layer DFS', plots.info_frame(current), 'layer_dfs_'+v+'.csv', 'layer_dfs_'+v)
            if not current['problems'].empty:
                with st.expander(data.VARIABLES[v][0]+' exclusions'):
                    st.dataframe(data.display_cases(current['problems'], case_labels), **STRETCH, hide_index=True)
        st.caption('Profile shading uses medians across cases. Ch1-relative shading subtracts profiles before taking the median and never mixes diagnostic sources. Cumulative curves describe the selected layer; 95% heights use the full retrieval column.')
        st.stop()

    if view == 'RMSE comparisons' and rmse_style == 'Distributions':
        choices = st.columns(2)
        show_t = choices[0].checkbox('Show temperature', value=True, key='rmse_show_t')
        show_q = choices[1].checkbox('Show water vapor mixing ratio', value=True, key='rmse_show_q')
        variables = [v for v, enabled in [('T', show_t), ('q', show_q)] if enabled]
        analyses = {v: data.build_analysis(selected, models, profiles, observations, v, edges, paired) for v in ('T', 'q')}
        st.caption('Temperature: filled box, circles on the left. Water vapor: outline box, open diamonds on the right. '
                   'Band colors are shared across variables. The legend also toggles each variable across all bands. '
                   'Values retain their native units (°C and g/kg); equal numerical RMSE does not imply equal error importance.')
        if not variables:
            st.info('Enable at least one variable to display distributions.')
        elif all(analyses[v]['metrics'].empty for v in variables):
            st.warning('No complete comparisons for the selected variables in this layer. Review exclusions below.')
        else:
            display_chart(plots.rmse_distributions(analyses, models, variables), 'rmse_distributions_both')
        st.caption(f"{'Paired across bands' if paired else 'Available per band'} comparisons · {bottom:g}–{top:g} km AGL. "
                   'Each variable uses its own valid case cohort; toggling visibility does not change the statistics.')
        with st.expander('Sample counts, exclusions, and downloads'):
            counts = pd.DataFrame({'model': models})
            for v in ('T', 'q'):
                frame = analyses[v]['metrics']
                counts[v+' cases'] = [int(frame.model.eq(m).sum()) if len(frame) else 0 for m in models]
                download_table('Download '+data.VARIABLES[v][0]+' case metrics', frame,
                               'rmse_'+v+'_cases.csv', 'rmse_cases_'+v)
                issues = analyses[v]['problems']
                if not issues.empty:
                    st.write(data.VARIABLES[v][0]+' exclusions')
                    st.dataframe(data.display_cases(issues, case_labels), **STRETCH, hide_index=True)
            st.dataframe(counts, **STRETCH, hide_index=True)
            if problems:
                st.dataframe(pd.DataFrame(problems), **STRETCH)
            if not index_errors.empty:
                st.dataframe(index_errors, **STRETCH)
            download_table('Download distribution settings', pd.DataFrame([dict(
                classification_manifest=active['path'], bands=','.join(models), visible_variables=','.join(variables),
                start_date=str(dates[0]), end_date=str(dates[1]), layer_bottom_km=bottom, layer_top_km=top,
                bins=len(edges)-1, paired=paired, tolerance_seconds=tolerance)]), 'rmse_settings.csv', 'rmse_settings')
        st.stop()

    analysis = data.build_analysis(selected, models, profiles, observations, variable, edges, paired)
    metrics = analysis['metrics']
    issues = pd.concat([pd.DataFrame(problems), analysis['problems']], ignore_index=True)
    info = plots.info_frame(analysis)
    a, b, c, d = st.columns(4)
    a.metric('Filtered cases', f'{len(selected):,}', help=f'Of {len(cases):,} manifest cases')
    b.metric('Loaded retrievals', f'{len(profiles):,}', help='Case-band pairs; a readable output is not certification of convergence.')
    c.metric('RMSE case-band pairs', f'{len(metrics):,}')
    d.metric('DFS case-band pairs', f'{len(info):,}')
    st.caption(f"{'Paired' if paired else 'Available per band'} comparisons · {bottom:g}–{top:g} km AGL · {len(edges)-1} equal vertical bins. "
               'RMSE requires finite retrieval and sounding data throughout this layer. DFS has a separate cohort; sources stay labeled.')

    if view == 'RMSE comparisons':
        if metrics.empty:
            st.warning('No complete radiosonde comparisons in this layer. Review exclusions below, reduce the layer, or turn off paired comparisons.')
        else:
            style = rmse_style
            baseline = None
            if style == 'Case heatmap':
                baseline = st.selectbox('Subtract baseline', ['None']+models)
                baseline = None if baseline == 'None' else baseline
            display_chart(plots.rmse_plot(analysis, models, style, baseline), 'rmse')
    elif view == 'Cloud diagnostics':
        fields = [k for k in selected if (k.startswith('asi_') or k.startswith('radiance_'))
                  and pd.to_numeric(selected[k], errors='coerce').notna().any()]
        if len(fields) < 2:
            st.info('This manifest does not contain two numeric cloud diagnostics.')
        else:
            x = st.selectbox('X diagnostic', fields, index=fields.index('radiance_core_radiance_mean') if 'radiance_core_radiance_mean' in fields else 0)
            y = st.selectbox('Y diagnostic', fields, index=fields.index('asi_core_total_mean') if 'asi_core_total_mean' in fields else 1)
            display_chart(plots.screening_plot(selected, x, y), 'screening')
            n = (pd.to_numeric(selected[x], errors='coerce').notna() & pd.to_numeric(selected[y], errors='coerce').notna()).sum()
            st.caption(f'{n} / {len(selected)} cases have both plotted diagnostics. Missing metrics remain in the cohort when requested.')
    with st.expander('Sample counts, exclusions, and downloads'):
        counts = pd.DataFrame({'model': models})
        counts['loaded'] = [sum(m == model for _, m in profiles) for model in models]
        counts['rmse'] = [int((metrics.model == model).sum()) if len(metrics) else 0 for model in models]
        counts['dfs'] = [int((info.model == model).sum()) if len(info) else 0 for model in models]
        st.dataframe(counts, **STRETCH, hide_index=True)
        st.caption('These counts describe data availability. The app does not apply convergence/QC, LWP, or config.bad_dts filters automatically.')
        if not issues.empty:
            st.dataframe(data.display_cases(issues, case_labels), **STRETCH, hide_index=True)
            download_table('Download exclusions', issues, 'exclusions.csv', 'issues_csv')
        if not index_errors.empty:
            st.write('Indexing errors')
            st.dataframe(index_errors, **STRETCH)
        if len(metrics):
            download_table('Download per-case metrics', metrics, 'retrieval_metrics.csv', 'metrics_csv')
        download_table('Download filtered manifest', selected, 'filtered_manifest.csv', 'manifest_csv')
        settings = pd.DataFrame([dict(source=loaded['manifest'], classification_manifest=active['path'], bands=','.join(models),
                                      start_date=str(dates[0]), end_date=str(dates[1]), variable=variable,
                                      layer_bottom_km=bottom, layer_top_km=top, bins=len(edges)-1,
                                      paired=paired, tolerance_seconds=tolerance, dfs_source=information_source,
                                      no_model=no_model, cloud_filters=str(bounds), classifications=str(selections),
                                      include_missing_cloud_metrics=include_missing)])
        download_table('Download analysis settings', settings, 'analysis_settings.csv', 'settings_csv')
    with st.expander('Band definitions (cm⁻¹)'):
        from spectralBands import ch1_bands, ch2_bands
        st.dataframe(pd.DataFrame([dict(band=m, wavenumbers=ch1_bands if m == 'Ch1' else ch2_bands.get('band'+m.split('_B')[1], 'Unknown')) for m in models]), hide_index=True)


