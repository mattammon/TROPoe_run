"""Launch: python -m streamlit run TROPoe_APP.py"""
from pathlib import Path
import logging

import numpy as np
import pandas as pd
import streamlit as st

import dashboard_data as data
import dashboard_plots as plots
from dashboard_vertical import plotly_size_kwargs, render_vertical

st.set_page_config(page_title='TROPoe • Retrieval Explorer', page_icon='🌤️', layout='wide')
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
LOG = logging.getLogger(__name__)
STRETCH = {'width': 'stretch'} if tuple(int(x) for x in st.__version__.split('.')[:2]) >= (1, 50) else {'use_container_width': True}

# File signatures invalidate the cache when a file changes. A new source load
# invalidates the directory scan; no catalog or retrieval is modified by this app.
@st.cache_data(show_spinner=False, max_entries=20000)
def read_profile(signature, record, time, source, no_model):
    return data.load_retrieval(signature, record, time, source, no_model)


@st.cache_data(show_spinner=False, max_entries=5000)
def read_observation(signature):
    return data.load_sounding(signature)


@st.cache_data(show_spinner=False)
def demo():
    return data.demo_data()


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
    default_manifest = config.CLOUD_SCREEN_MANIFEST or ''
    default_sonde = config.SONDE_DIR
except (ImportError, AttributeError):
    default_root, default_manifest, default_sonde = '', '', ''

st.markdown('### TROPoe Retrieval Evaluation Toolbox')
st.caption('Compare spectral bands, cloud conditions, and vertical information content.')
with st.sidebar:
    st.header('Data source')
    source_mode = st.radio('Source', ['Synthetic demo', 'Retrieval files'], key='source_mode')
    if source_mode == 'Retrieval files':
        with st.form('source_form'):
            manifest_path = st.text_input('Screening manifest CSV', str(default_manifest))
            root_path = st.text_input('Retrieval directory', default_root, help='Scan recursively; select one experiment/group to avoid mixing configurations.')
            catalog_path = st.text_input('Catalog profiles.csv (optional)', '', help='Speeds up loading. Rebuild it after new retrievals finish.')
            sonde_root = st.text_input('Sounding search directory (optional)', default_sonde, help='Used when a manifest sounding path has moved. Duplicate basenames are rejected.')
            load = st.form_submit_button('Load / refresh data', type='primary')
        if load:
            st.session_state.pop('loaded_source', None)
            try:
                manifest_path = str(Path(manifest_path).expanduser().resolve())
                root_path = str(Path(root_path).expanduser().resolve())
                catalog_path = str(Path(catalog_path).expanduser().resolve()) if catalog_path.strip() else ''
                with st.spinner('Reading manifest and indexing retrieval timestamps…'):
                    cases = data.read_manifest(manifest_path)
                    index, index_errors = data.read_index(root_path, catalog_path)
                st.session_state.loaded_source = dict(cases=cases, index=index, errors=index_errors,
                                                       manifest=manifest_path, root=root_path,
                                                       catalog=catalog_path, sonde_root=str(Path(sonde_root).expanduser()) if sonde_root else '')
                LOG.info('Loaded %d manifest cases and %d indexed retrieval records', len(cases), len(index))
            except Exception as exc:
                st.error(str(exc))
                LOG.exception('Could not load source')

is_demo = source_mode == 'Synthetic demo'
if is_demo:
    cases, available_models, all_profiles, all_observations = demo()
    index_errors, matches = pd.DataFrame(), pd.DataFrame()
    st.info('SYNTHETIC DEMO — generated profiles and cloud diagnostics for exploring the controls. These are not measured retrievals.')
else:
    loaded = st.session_state.get('loaded_source')
    if loaded is None:
        st.info('Enter the paths on the machine running this app, then select “Load / refresh data”.')
        st.stop()
    cases, index, index_errors = loaded['cases'], loaded['index'], loaded['errors']
    available_models = sorted(index.model.unique(), key=data.model_sort)
    st.caption(f"Manifest: {loaded['manifest']} · Retrievals: {loaded['root']}")
    if loaded['catalog']:
        st.caption('Using catalog timestamps. New files appear after rebuilding the catalog and refreshing data.')

case_labels = dict(zip(cases.case_id, cases.sounding_time.map(data.case_label)))
view = st.selectbox('Plot', ['Vertical profiles', 'RMSE comparisons', 'Vertical errors', 'Taylor diagram',
                            'Information content', 'DFS vs RMSE', '985 radiance scatter', 'Cloud diagnostics', 'Case catalog'])
if not available_models and view != '985 radiance scatter':
    st.warning('No readable retrieval profiles were found. Inspect the scan errors below, or select the 985 radiance scatter to explore the manifest.')
    st.dataframe(index_errors, **STRETCH)
    st.stop()

with st.sidebar:
    st.header('Comparison')
    # Keys change between sources so a demo band/date selection cannot silently
    # suppress an unrelated real dataset.
    prefix = 'demo_' if is_demo else 'real_'+loaded['manifest']
    with st.form('filters_'+prefix):
        models = st.multiselect('Bands', available_models, default=available_models, key=prefix+'bands')
        dates = st.date_input('Sounding date range (UTC)',
                              (cases.sounding_time.min().date(), cases.sounding_time.max().date()),
                              min_value=cases.sounding_time.min().date(), max_value=cases.sounding_time.max().date())
        selections = {}
        for key, label in [('category', 'Cloud category'), ('asi_state', 'ASI classification'), ('radiance_state', '985 radiance classification')]:
            choices = sorted(cases[key].unique())
            selections[key] = st.multiselect(label, choices, default=choices)
        st.caption('Optional cloud-metric limits (manifest values; no reclassification).')
        window = st.selectbox('Screening window', ['core', 'context'])
        bounds = {}
        radiance_limits = {}
        for stem, label, limit in [('asi_{}_total_mean', 'Total cloud cover (%)', 100.),
                                    ('asi_{}_zenith_mean', 'Near-zenith cloud cover (%)', 100.),
                                    ('radiance_{}_radiance_mean', '985 radiance mean', 7.),
                                    ('radiance_{}_radiance_std', '985 radiance standard deviation', 0.3)]:
            enabled = st.checkbox('Limit '+label, key=prefix+stem+'enabled')
            maximum = st.number_input('Maximum '+label, min_value=0., value=limit, key=prefix+stem+'maximum')
            if stem.startswith('radiance_'):
                radiance_limits[stem] = (maximum, enabled)
            if enabled:
                bounds[stem.format(window)] = (-np.inf, maximum)
        include_missing = st.checkbox('Include missing cloud metrics', value=True)
        paired = st.checkbox('Compare the same cases across selected bands', value=True,
                             help='Accuracy and DFS each use their own common cohort. DFS vs RMSE uses their intersection.')
        tolerance = st.number_input('Maximum retrieval time offset (seconds)', min_value=0., max_value=449., value=60.,
                                    help='Compared to manifest retrieval_time, using NetCDF timestamps.')
        information_source = st.selectbox('DFS diagnostic source', ['auto', 'kernel', 'cdfs'])
        no_model = st.checkbox('Use *_no_model DFS diagnostics', value=False)
        st.form_submit_button('Apply filters', type='primary')

if not models and view != '985 radiance scatter':
    st.info('Select at least one band, then apply filters.')
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
if view == '985 radiance scatter':
    show_outside = st.checkbox('Include cases outside radiance limits', value=True,
                               help='Retains cases rejected by active radiance limits for visual context. Dates, classifications, and ASI limits still apply.')
    plot_bounds = {k: v for k, v in bounds.items() if not (show_outside and k.startswith('radiance_'))}
    scatter_cases = data.filter_cases(cases, dates, selections, plot_bounds, include_missing)
    fields = [f'radiance_{window}_radiance_mean', f'radiance_{window}_radiance_std']
    absent = [f for f in fields if f not in cases]
    if absent:
        st.warning('This manifest has no '+window+' radiance mean/std pair: '+', '.join(absent)+'. Choose another screening window and apply filters.')
        st.stop()
    grouping = st.selectbox('Group cases by', ['Classification', 'Season', 'Month', 'Time of day (UTC)',
                                              'ASI classification', 'Radiance classification', 'Year'])
    metadata = data.case_metadata(scatter_cases)
    available = set(metadata[grouping])
    ordered = data.GROUP_ORDERS.get(grouping, sorted(available))
    options = [g for g in ordered if g in available]
    categories = st.multiselect('Visible categories', options, default=options,
                               key=prefix+'radiance_categories_'+grouping+'_'+window)
    mean_limit, mean_enabled = radiance_limits['radiance_{}_radiance_mean']
    std_limit, std_enabled = radiance_limits['radiance_{}_radiance_std']
    st.caption(f'{window.capitalize()} screening window · Mean ≤ {mean_limit:g} ({"active" if mean_enabled else "reference only"}) · '
               f'Standard deviation ≤ {std_limit:g} ({"active" if std_enabled else "reference only"}). '
               'Shading marks the region meeting active radiance limits; it does not change classifications.')
    figure, plotted = plots.radiance_plot(scatter_cases, window, grouping, mean_limit, std_limit,
                                          mean_enabled, std_enabled, categories)
    display_chart(figure, '985_radiance')
    st.caption(f'{len(plotted):,} plotted cases / {len(scatter_cases):,} cases before category toggles and missing-value removal. '
               'Click a legend label to toggle its points; double-click to isolate it. Hover for the case date and diagnostics. '
               'Season, month, and six-hour time blocks use the sounding time in UTC. Each case appears once, independent of retrieval availability.')
    if plotted.empty:
        st.info('No cases with finite radiance mean and standard deviation match these selections.')
    download_table('Download plotted radiance cases', plotted, 'radiance_cases.csv', 'radiance_csv')
    settings = pd.DataFrame([dict(window=window, mean_limit=mean_limit, std_limit=std_limit,
                                  mean_active=mean_enabled, std_active=std_enabled, group_by=grouping,
                                  visible_categories=', '.join(categories), include_outside_limits=show_outside,
                                  start_date=str(dates[0]), end_date=str(dates[1]), filters=str(plot_bounds),
                                  classifications=str(selections), include_missing=include_missing)])
    download_table('Download radiance plot settings', settings, 'radiance_settings.csv', 'radiance_settings')
    st.stop()

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

load_models = list(dict.fromkeys(models + (['Ch1'] if view == 'Vertical errors' else [])))
problems = []
if is_demo:
    profiles = {k: v for k, v in all_profiles.items() if k[0] in set(selected.case_id) and k[1] in load_models}
    observations = {k: v for k, v in all_observations.items() if k in set(selected.case_id)}
    if no_model or information_source == 'cdfs':
        # Demo only supplies Akernal; honor source controls rather than substitute.
        profiles = {k: dict(v, information={'variables': {}, 'errors': dict.fromkeys(['T', 'q'], 'Synthetic demo supplies only Akernal')}) for k, v in profiles.items()}
else:
    matches = data.match_cases(selected, index, load_models, tolerance)
    shared = matches.loc[matches.file.ne('')].duplicated(['model', 'file', 'profile_index'], keep=False)
    if shared.any():
        st.warning('Some manifest cases match the same retrieval record. Inspect the matched-record catalog before treating cases as independent samples.')
    profiles, observations = {}, {}
    progress = st.progress(0, text='Loading selected profiles…')
    for n, row in enumerate(matches.itertuples(), 1):
        if row.file:
            try:
                profiles[(row.case_id, row.model)] = read_profile(data.signature(row.file), row.profile_index,
                                                                 row.matched_time, information_source, no_model)
            except Exception as exc:
                problems.append(dict(case_id=row.case_id, model=row.model, stage='retrieval load', reason=str(exc)))
                LOG.warning('%s / %s: %s', row.case_id, row.model, exc)
        if n % 25 == 0 or n == len(matches):
            progress.progress(n/len(matches), text=f'Loading retrieval {n:,} / {len(matches):,}')
    for row in selected.itertuples():
        try:
            path = data.sounding_path(row.sounding_file, Path(loaded['manifest']).parent, loaded['sonde_root'])
            observations[row.case_id] = read_observation(data.signature(path))
        except Exception as exc:
            problems.append(dict(case_id=row.case_id, model='Radiosonde', stage='sounding load', reason=str(exc)))
            LOG.warning('%s / radiosonde: %s', row.case_id, exc)
    progress.empty()

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
        if is_demo:
            st.write('Synthetic profiles; no source files.')
        else:
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
else:
    st.dataframe(data.display_cases(selected, case_labels), **STRETCH, hide_index=True)
    if not matches.empty:
        st.subheader('Matched retrieval records')
        st.dataframe(data.display_cases(matches, case_labels), **STRETCH, hide_index=True)
        download_table('Download matched records', matches, 'matched_records.csv', 'matches_csv')

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
    settings = pd.DataFrame([dict(source='synthetic' if is_demo else loaded['manifest'], bands=','.join(models),
                                  start_date=str(dates[0]), end_date=str(dates[1]), variable=variable,
                                  layer_bottom_km=bottom, layer_top_km=top, bins=len(edges)-1,
                                  paired=paired, tolerance_seconds=tolerance, dfs_source=information_source,
                                  no_model=no_model, cloud_filters=str(bounds), classifications=str(selections),
                                  include_missing_cloud_metrics=include_missing)])
    download_table('Download analysis settings', settings, 'analysis_settings.csv', 'settings_csv')
with st.expander('Band definitions (cm⁻¹)'):
    from spectralBands import ch1_bands, ch2_bands
    st.dataframe(pd.DataFrame([dict(band=m, wavenumbers=ch1_bands if m == 'Ch1' else ch2_bands.get('band'+m.split('_B')[1], 'Unknown')) for m in models]), hide_index=True)
