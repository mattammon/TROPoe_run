"""Joint T/q verification and interactive vertical-error figures."""
import inspect
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from dashboard_data import build_analysis, VARIABLES
from dashboard_plots import colors, finish


def plotly_size_kwargs(chart_function):
    """Streamlit 1.50 accepts dataframe width, but not plotly_chart width."""
    parameters = inspect.signature(chart_function).parameters
    return {'width': 'stretch'} if 'width' in parameters else {'use_container_width': True}


def compare_variables(cases, models, profiles, observations, edges):
    analyses = {v: build_analysis(cases, models, profiles, observations, v, edges, False) for v in ('T', 'q')}
    common = [c for c in cases.case_id if all((c, m) in analyses[v]['curves'] for m in models for v in analyses)]
    scales = {}
    for v, a in analyses.items():
        obs = np.concatenate([a['curves'][(c, models[0])]['observed'] for c in common]) if common else np.array([])
        scales[v] = float(np.std(obs)) if len(obs) else np.nan
    rows = []
    for m in models:
        rmses = {}
        for v, a in analyses.items():
            errors = np.array([a['curves'][(c, m)]['error'] for c in common])
            rmses[v] = float(np.sqrt(np.mean(errors**2))) if errors.size else np.nan
        total = np.sqrt(np.mean([(rmses[v]/scales[v])**2 for v in ('T', 'q')])) if all(np.isfinite(scales[v]) and scales[v] > 0 for v in scales) else np.nan
        rows.append({'Band': m, 'Temperature RMSE (°C)': rmses['T'], 'Mixing ratio RMSE (g/kg)': rmses['q'], 'Combined normalized RMSE': total})
    return analyses, common, pd.DataFrame(rows).set_index('Band'), scales


def vertical_rmse(analysis, models, common):
    fig = go.Figure()
    for m in models:
        errors = np.array([analysis['curves'][(c, m)]['error'] for c in common])
        if errors.size:
            fig.add_trace(go.Scatter(x=np.sqrt(np.mean(errors**2, axis=0)), y=analysis['centers'], mode='lines', name=m, line=dict(color=colors(models)[m])))
    name, units, _ = VARIABLES[analysis['variable']]
    return finish(fig, f'{name} · {len(common)} common cases', f'RMSE ({units})', 'Height AGL (km)')


def ranking_plot(table):
    ranked = table.dropna(subset=['Combined normalized RMSE']).sort_values('Combined normalized RMSE', kind='stable')
    fig = go.Figure(go.Bar(x=ranked['Combined normalized RMSE'], y=ranked.index, orientation='h',
                          marker_color=[colors(list(ranked.index))[m] for m in ranked.index],
                          text=[f'{x:.3f}' for x in ranked['Combined normalized RMSE']], textposition='auto'))
    fig.update_yaxes(autorange='reversed')
    return finish(fig, 'Band ranking · lower is better', 'Combined normalized RMSE (dimensionless)', 'Band')


def case_error_panels(analysis, model, visible_models, case, ordered_cases):
    """Signed error heatmaps; a single-case pointwise RMSE is absolute error."""
    z = analysis['centers']
    curves = analysis['curves']
    ids = [c for c in ordered_cases if (c, model) in curves]
    error = np.array([curves[(c, model)]['error'] for c in ids]).T if ids else np.empty((len(z), 0))
    delta = np.array([curves[(c, model)]['error']-curves[(c, 'Ch1')]['error'] if 'Ch1' in visible_models and (c, 'Ch1') in curves else np.full(len(z), np.nan) for c in ids]).T if ids else error.copy()
    labels = [analysis['case_labels'][c] for c in ids]
    fig = make_subplots(rows=1, cols=3, column_widths=[.38, .24, .38], shared_yaxes=True,
                        subplot_titles=[f'{model} − radiosonde', 'Selected case · absolute error', f'{model} error − Ch1 error'], horizontal_spacing=.07)
    for col, values in [(1, error), (3, delta)]:
        fig.add_trace(go.Heatmap(z=values, x=list(range(len(ids))), y=z, colorscale='RdBu_r', zmid=0,
                                customdata=np.tile(labels, (len(z), 1)),
                                hovertemplate='%{customdata}<br>%{y:.2f} km<br>%{z:.3f}<extra></extra>',
                                colorbar=dict(x=.30 if col == 1 else 1.01, thickness=10, len=.7), showscale=True), row=1, col=col)
        ticks = list(range(0, len(ids), max(1, int(np.ceil(len(ids)/5)))))
        fig.update_xaxes(tickmode='array', tickvals=ticks, ticktext=[labels[i] for i in ticks], tickangle=-45, row=1, col=col)
        if case in ids:
            fig.add_vline(x=ids.index(case), line_color='black', line_dash='dot', row=1, col=col)
    for m in visible_models:
        if (case, m) in curves:
            fig.add_trace(go.Scatter(x=np.abs(curves[(case, m)]['error']), y=z, mode='lines', name=m,
                                    line=dict(color=colors(visible_models)[m])), row=1, col=2)
    name, units, _ = VARIABLES[analysis['variable']]
    finish(fig, f'{name} · {analysis["case_labels"].get(case, "")}', y=None)
    fig.update_layout(height=640, margin=dict(l=50, r=70, t=100, b=150), legend=dict(y=-.4))
    fig.update_yaxes(title_text='Height AGL (km)', row=1, col=1)
    fig.update_xaxes(title_text=f'Absolute error ({units})', row=1, col=2)
    return fig, int(sum('Ch1' in visible_models and (c, 'Ch1') in curves for c in ids)), len(ids)


def render_vertical(cases, models, profiles, observations, edges, display_chart, download_table, load_problems):
    import streamlit as st
    table_size = {'width': 'stretch'} if tuple(int(x) for x in st.__version__.split('.')[:2]) >= (1, 50) else {'use_container_width': True}
    analyses, common, table, scales = compare_variables(cases, models, profiles, observations, edges)
    with st.sidebar:
        st.subheader('Vertical-error band visibility')
        visible = [m for m in models if st.checkbox(m, value=True, key='vertical_visible_'+m)]
        st.caption('Visibility only; the common comparison cohort and ranking remain fixed. Use Bands above to change the comparison cohort.')
    st.caption(f'{len(common)} cases have finite T and q throughout the layer for every selected band. Both RMSE curves and the table use this identical cohort.')
    left, right = st.columns(2)
    for column, v in zip((left, right), ('T', 'q')):
        with column:
            display_chart(vertical_rmse(analyses[v], visible, common), 'vertical_rmse_'+v)
    st.dataframe(table, **table_size)
    st.caption('Each RMSE pools squared errors over all common cases and equally spaced height-bin centers, then takes the square root. '
               'Combined = sqrt(((RMSE_T / σobs,T)² + (RMSE_q / σobs,q)²) / 2); the observed population standard deviations are shared by all bands. '
               f'σobs,T = {scales["T"]:.3g} °C; σobs,q = {scales["q"]:.3g} g/kg. This is a dimensionless ranking score, not a sum of unlike units.')
    if not common:
        st.warning('No joint complete cases across selected bands. Reduce the comparison bands or height layer; individual case panels below can still be inspected.')
    if table['Combined normalized RMSE'].isna().all():
        st.info('Combined ranking is unavailable without common cases and nonzero observed variance for both variables.')
    else:
        display_chart(ranking_plot(table), 'vertical_ranking')
    download_table('Download pooled RMSE and ranking', table.reset_index(), 'vertical_rmse_summary.csv', 'vertical_summary_csv')
    download_table('Download common comparison cases', cases.loc[cases.case_id.isin(common)], 'vertical_common_cases.csv', 'vertical_common_csv')
    download_table('Download vertical comparison settings', pd.DataFrame([dict(bands=', '.join(models), layer_bottom_km=edges[0], layer_top_km=edges[-1], bins=len(edges)-1, common_cases=len(common), temperature_scale=scales['T'], mixing_ratio_scale=scales['q'], combined_formula='sqrt(mean((RMSE_variable / observed_population_std_variable)^2))')]), 'vertical_settings.csv', 'vertical_settings_csv')
    st.subheader('Case-height errors and individual profiles')
    band = st.selectbox('Band for case-height errors', models)
    candidates = [c for c in cases.case_id if any((c, m) in analyses[v]['curves'] for m in models for v in analyses)]
    if candidates:
        case = st.selectbox('Case for error profiles', candidates, format_func=analyses['T']['case_labels'].get)
        st.caption('These panels use available cases for each variable. The center panel shows absolute error at each height (single-case RMSE). '
                   'The right panel shows signed error difference: selected band minus Ch1 when Ch1 is selected and visible, on the same case and height; '
                   'positive does not necessarily mean less accurate. A dotted line marks the selected case. Missing Ch1 comparisons are blank.')
        for v in ('T', 'q'):
            fig, paired_count, total = case_error_panels(analyses[v], band, visible, case, cases.case_id.tolist())
            display_chart(fig, 'case_error_'+v)
            st.caption(f'{VARIABLES[v][0]}: {paired_count}/{total} heatmap cases have a Ch1 comparison.')
    errors = pd.concat([pd.DataFrame(load_problems)]+[a['problems'].assign(variable=v) for v, a in analyses.items()], ignore_index=True)
    with st.expander('Sample counts and exclusions'):
        st.dataframe(pd.DataFrame([{'Band': m, 'T cases': sum(mm == m for _, mm in analyses['T']['curves']),
                                   'q cases': sum(mm == m for _, mm in analyses['q']['curves']), 'Joint cases': len(common)} for m in models]), **table_size)
        if len(errors):
            download_table('Download vertical-error exclusions', errors, 'vertical_exclusions.csv', 'vertical_exclusions_csv')
        for v, a in analyses.items():
            download_table('Download '+v+' case metrics', a['metrics'], 'vertical_'+v+'_cases.csv', 'vertical_cases_'+v)

