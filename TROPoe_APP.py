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
def read_profile(signature, record, time, source, no_model):
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
source, active = classification_gate(default_manifest, default_root, default_sonde, default_images, default_output)
all_cases = active['cases']
cases = all_cases.loc[all_cases.category == 'clear_sky'].copy()
rules = ClassificationRules(**active['rules'])
todo_path = getattr(config, 'RETRIEVAL_TODO_MANIFEST', None)
todo_bands = getattr(config, 'RETRIEVAL_TODO_BANDS', list(range(1, 19)))
todo_tolerance = getattr(config, 'RETRIEVAL_TODO_TOLERANCE_SECONDS', 60.)
if st.sidebar.button('Refresh retrieval inventory and to-do'):
    st.session_state.pop('loaded_source', None)
    st.session_state.pop('retrieval_todo_key', None)
scope = (active['path'], source['root'])
if st.session_state.get('loaded_source', {}).get('scope') != scope:
    with st.spinner('Checking retrieval timestamps and clear-sky profile completeness…'):
        try:
            if not Path(source['root']).exists() or cases.empty:
                index = pd.DataFrame(columns=['file', 'model', 'profile_index', 'time', 'status'])
                index_errors = pd.DataFrame()
            else:
                # Read timestamps for discovery, but T/q only near clear-case targets.
                # Cover the dashboard's allowed matching tolerance. The queue uses
                # the stricter configured completion tolerance below.
                index, index_errors = data.read_index(source['root'], target_times=cases.retrieval_time,
                                                      tolerance_seconds=449.)
        except Exception as exc:
            st.error('Could not check retrieval completion; no new to-do manifest was written: '+str(exc))
            st.stop()
    st.session_state.loaded_source = dict(index=index, errors=index_errors, manifest=source['master'],
                                         root=source['root'], catalog=source['catalog'], sonde_root=source['sonde_root'], scope=scope)
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
view = st.selectbox('Plot', ['Case catalog', 'Vertical profiles', 'RMSE comparisons', 'Vertical errors', 'Taylor diagram',
                            'Information content', 'DFS vs RMSE', '985 radiance scatter', 'Cloud diagnostics'])
if view == 'Case catalog':
    render_catalog(cases, index, models, case_labels, todo_tolerance, index_errors)
    st.stop()
if view == '985 radiance scatter':
    from dataclasses import asdict
    store = ReviewStore(source['output'])
    def refresh_review_snapshot():
        if fingerprint(source['master']) != source['master_hash']:
            raise ValueError('Master changed; reload the master before applying')
        classified, path = save_run(source['master'], source['cases'], rules, store)
        st.session_state.cloud_active = dict(cases=classified, path=str(path), rules=asdict(rules))
    review_plot(all_cases, rules, source['image_root'], store, key='dashboard_review', on_review=refresh_review_snapshot)
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
a, b, c, d = st.columns([2, 1, 1, 1])
variable = 'T' if view == 'Vertical errors' else a.selectbox('Variable', ['T', 'q'], format_func=lambda v: data.VARIABLES[v][0])
bottom = b.number_input('Layer bottom (km AGL)', min_value=0., max_value=19.9, value=0.1, step=0.1)
top = c.number_input('Layer top (km AGL)', min_value=0.1, max_value=20., value=3., step=0.1)
spacing = d.selectbox('Vertical bin size (m)', [25, 50, 100, 200, 250, 500], index=2)
if bottom >= top:
    st.warning('Layer top must exceed layer bottom.')
    st.stop()
edges = np.linspace(bottom, top, max(2, int(np.ceil((top-bottom)*1000/spacing)))+1)

load_models = models
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

if view == 'Vertical profiles':
    case = st.selectbox('Case', selected.case_id.tolist(), format_func=case_labels.get)
    row = selected.set_index('case_id').loc[case]
    st.caption(f"{case_labels[case]} · {row.category} · ASI: {row.asi_state} · radiance: {row.radiance_state}")
    display_chart(plots.profile_plot(case, models, profiles, observations, variable, (bottom, top)), 'profiles')
    with st.expander('Source files and matched records'):
        st.dataframe(data.display_cases(matches.loc[matches.case_id == case], case_labels), **STRETCH)
    if not any((case, m) in profiles and variable in profiles[(case, m)] for m in models):
        st.warning('No selected retrieval profile is available for this case and variable.')
elif view in ('RMSE comparisons', 'Taylor diagram'):
    if metrics.empty:
        st.warning('No complete radiosonde comparisons in this layer. Review exclusions below, reduce the layer, or turn off paired comparisons.')
    elif view == 'RMSE comparisons':
        style = st.radio('RMSE view', ['Distributions', 'Timeline', 'Case heatmap'], horizontal=True)
        baseline = None
        if style == 'Case heatmap':
            baseline = st.selectbox('Subtract baseline', ['None']+models)
            baseline = None if baseline == 'None' else baseline
        display_chart(plots.rmse_plot(analysis, models, style, baseline), 'rmse')
    else:
        figure, table = plots.taylor_plot(analysis, models)
        display_chart(figure, 'taylor')
        st.caption('Angle encodes correlation; radius is retrieved / observed standard deviation. Dotted arcs are normalized centered RMSE. Bias is excluded from centered RMSE.')
        st.dataframe(table, **STRETCH)
        download_table('Download Taylor statistics', table, 'taylor_statistics.csv', 'taylor_csv')
elif view in ('Information content', 'DFS vs RMSE'):
    if info.empty:
        st.warning('No valid DFS diagnostics cover this layer for the current cohort. Review source selection and exclusions below.')
    elif view == 'Information content':
        mode = st.radio('Information view', ['Cumulative profiles', 'Density profiles', 'Layer distributions'], horizontal=True)
        display_chart(plots.info_plot(analysis, mode), 'information')
        download_table('Download layer DFS', info, 'layer_dfs.csv', 'dfs_csv')
    elif metrics.empty or not metrics.dfs.notna().any():
        st.warning('No cases have both valid RMSE and DFS in this layer.')
    else:
        individual = st.checkbox('Show individual cases', value=True)
        figure, table = plots.dfs_rmse_plot(analysis, individual)
        display_chart(figure, 'dfs_rmse')
        st.caption('Diamonds are band/source means over the same case pairs; bars show case spread (±1 population standard deviation), not confidence intervals.')
        st.dataframe(table, **STRETCH)
        download_table('Download DFS–RMSE summary', table, 'dfs_rmse_summary.csv', 'dfs_rmse_csv')
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


