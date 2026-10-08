"""Interactive Plotly figures for the retrieval explorer."""
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from dashboard_data import VARIABLES, model_sort, case_metadata, GROUP_ORDERS

# Fixed identities for Ch1 and all 18 configured Ch2 bands. Never assign colors
# by the currently visible subset or cycle through a short palette.
PALETTE = ['#202020', '#E6194B', '#3CB44B', '#4363D8', '#F58231',
           '#911EB4', '#00BCD4', '#F032E6', '#808000', '#9A6324',
           '#469990', '#800000', '#000075', '#A170C4', '#C8AC00',
           '#A6D854', '#E08095', '#0080FF', '#707070']


def colors(models):
    return {m: PALETTE[0] if m == 'Ch1' else PALETTE[int(m.split('_B')[1])] for m in models}


def finish(fig, title, x=None, y=None):
    fig.update_layout(title=title, template='plotly_white', height=570,
                      margin=dict(l=55, r=30, t=65, b=55), font=dict(size=13),
                      legend=dict(title_text='', orientation='h', y=-0.18),
                      hoverlabel=dict(namelength=-1))
    if x:
        fig.update_xaxes(title=x)
    if y:
        fig.update_yaxes(title=y)
    return fig


def profile_plot(case, models, profiles, observations, variable, layer):
    fig = go.Figure()
    for model in ['Radiosonde']+models:
        p = observations.get(case) if model == 'Radiosonde' else profiles.get((case, model))
        if p is None or variable not in p:
            continue
        mask = (p['z'] >= layer[0]) & (p['z'] <= layer[1])
        fig.add_trace(go.Scatter(x=p[variable][mask], y=p['z'][mask], mode='lines', name=model,
                                line=dict(color='#111111' if model == 'Radiosonde' else colors(models)[model],
                                          width=3, dash='dash' if model == 'Radiosonde' else 'solid')))
    name, unit, _ = VARIABLES[variable]
    return finish(fig, 'Vertical profiles', f'{name} ({unit})', 'Height AGL (km)')


def rmse_plot(analysis, models, style, baseline=None):
    df = analysis['metrics'].copy()
    df['Case'] = df.case_id.map(analysis['case_labels'])
    unit = VARIABLES[analysis['variable']][1]
    if style == 'Distributions':
        fig = px.box(df, x='model', y='rmse', color='model', points='all',
                     hover_name='Case', hover_data=['bias', 'category'], color_discrete_map=colors(models),
                     category_orders={'model': models})
        return finish(fig, 'Case RMSE distributions', 'Retrieval band', f'RMSE ({unit})')
    if style == 'Timeline':
        fig = px.scatter(df, x='time', y='rmse', color='model', color_discrete_map=colors(models),
                         hover_name='Case', hover_data=['category', 'bias'])
        return finish(fig, 'RMSE through time', 'Sounding time (UTC)', f'RMSE ({unit})')
    matrix = df.pivot(index='case_id', columns='model', values='rmse').reindex(columns=models)
    matrix = matrix.reindex(df.sort_values('time').case_id.drop_duplicates())
    if baseline:
        matrix = matrix.subtract(matrix[baseline], axis=0)
    fig = go.Figure(go.Heatmap(z=matrix.T.values, x=list(range(len(matrix))), y=matrix.columns,
                              customdata=np.tile([analysis['case_labels'][c] for c in matrix.index], (len(matrix.columns), 1)),
                              colorscale='RdBu_r' if baseline else 'Viridis',
                              zmid=0 if baseline else None, colorbar=dict(title=f'Δ RMSE ({unit})' if baseline else f'RMSE ({unit})'),
                              hovertemplate='%{customdata}<br>%{y}<br>%{z:.3f}<extra></extra>'))
    ticks = list(range(0, len(matrix), max(1, int(np.ceil(len(matrix)/10)))))
    fig.update_xaxes(tickmode='array', tickvals=ticks,
                     ticktext=[analysis['case_labels'][matrix.index[i]] for i in ticks])
    return finish(fig, f'RMSE difference from {baseline}' if baseline else 'RMSE by case and band', 'Case (chronological)', 'Band')


def error_plot(analysis, model, mode):
    entries = [(case, data) for (case, band), data in analysis['curves'].items() if band == model]
    matrix = np.array([d['error'] for _, d in entries])
    unit = VARIABLES[analysis['variable']][1]
    if mode == 'Vertical RMSE':
        fig = go.Figure(go.Scatter(x=np.sqrt(np.mean(matrix**2, axis=0)), y=analysis['centers'],
                                  mode='lines', name=model, line=dict(color=colors([model])[model])))
        return finish(fig, f'{model} · RMSE across {len(entries)} cases', f'RMSE ({unit})', 'Height AGL (km)')
    fig = go.Figure(go.Heatmap(z=matrix.T, x=list(range(len(entries))), y=analysis['centers'],
                              customdata=np.tile([analysis['case_labels'][c] for c, _ in entries], (len(analysis['centers']), 1)),
                              hovertemplate='%{customdata}<br>Height: %{y:.2f} km<br>Error: %{z:.3f}<extra></extra>',
                              colorscale='RdBu_r', zmid=0, colorbar=dict(title=f'Error ({unit})')))
    ticks = list(range(0, len(entries), max(1, int(np.ceil(len(entries)/10)))))
    fig.update_xaxes(tickmode='array', tickvals=ticks,
                     ticktext=[analysis['case_labels'][entries[i][0]] for i in ticks])
    return finish(fig, f'{model} · retrieval minus radiosonde', 'Case (chronological)', 'Height AGL (km)')


def taylor_plot(analysis, models):
    fig, rows = go.Figure(), []
    for model in models:
        curves = [v for (c, m), v in analysis['curves'].items() if m == model]
        if not curves:
            continue
        obs = np.concatenate([v['observed'] for v in curves])
        ret = np.concatenate([v['retrieved'] for v in curves])
        so, sr = np.std(obs), np.std(ret)
        corr = np.corrcoef(obs, ret)[0, 1] if so > 0 and sr > 0 else np.nan
        ratio = sr/so if so > 0 else np.nan
        crmse = np.sqrt(np.mean(((ret-ret.mean())-(obs-obs.mean()))**2))
        rows.append(dict(model=model, cases=len(curves), samples=len(obs), correlation=corr,
                         std_ratio=ratio, centered_rmse=crmse, normalized_centered_rmse=crmse/so if so > 0 else np.nan,
                         rmse=np.sqrt(np.mean((ret-obs)**2)), bias=np.mean(ret-obs),
                         observed_std=so, retrieved_std=sr))
    table = pd.DataFrame(rows)
    units = VARIABLES[analysis['variable']][1]
    deviations = table.std_ratio.to_numpy() if len(table) else np.array([])
    radius = max(1.5, max(deviations[np.isfinite(deviations)], default=1)*1.15)
    theta = np.linspace(0, np.pi/2, 160)
    for r in np.linspace(0, radius, 5)[1:]:
        fig.add_trace(go.Scatter(x=r*np.cos(theta), y=r*np.sin(theta), mode='lines',
                                line=dict(color='#D5DEE9', width=1), showlegend=False, hoverinfo='skip'))
    for corr in (0, 0.5, 0.8, 0.95, 1):
        x, y = radius*corr, radius*np.sqrt(1-corr**2)
        fig.add_trace(go.Scatter(x=[0, x], y=[0, y], mode='lines', line=dict(color='#E6EBF1', width=1), showlegend=False, hoverinfo='skip'))
        fig.add_annotation(x=x, y=y, text=str(corr), showarrow=False, yshift=8)
    theta = np.linspace(0, np.pi, 240)
    for r in (.25, .5, 1.):
        x, y = 1+r*np.cos(theta), r*np.sin(theta)
        mask = (x >= 0) & (x*x+y*y <= radius*radius)
        fig.add_trace(go.Scatter(x=x[mask], y=y[mask], mode='lines', showlegend=False,
            name=f'Centered RMSE / σobs = {r:g}',
            hovertemplate=f'Centered RMSE / σobs: {r:g}<extra></extra>',
            line=dict(color='#9EADB9', dash='dot', width=1)))
    fig.add_trace(go.Scatter(x=[1], y=[0], mode='markers',
        marker=dict(symbol='star', size=20, color='black'), name='Radiosonde'))
    for row in table.itertuples():
        if not np.isfinite(row.correlation) or row.correlation < 0 or not np.isfinite(row.std_ratio):
            continue
        fig.add_trace(go.Scatter(x=[row.std_ratio*row.correlation], y=[row.std_ratio*np.sqrt(max(0, 1-row.correlation**2))],
                                mode='markers', name=row.model, marker=dict(size=22, opacity=.6, color=colors(models)[row.model], line=dict(width=1, color=colors(models)[row.model])),
                                text=[f'{row.model}<br>r={row.correlation:.4f}<br>σ/σobs={row.std_ratio:.3f}<br>σretrieval={row.retrieved_std:.3f} {units}<br>σobserved={row.observed_std:.3f} {units}<br>RMSE={row.rmse:.3f} {units}<br>N={row.cases} cases'],
                                hovertemplate='%{text}<extra></extra>'))
    fig.update_xaxes(range=[0, radius*1.06], constrain='domain')
    fig.update_yaxes(range=[-0.05, radius*1.1], scaleanchor='x', scaleratio=1)
    return finish(fig, VARIABLES[analysis['variable']][0]+' · Taylor diagram', 'Normalized standard deviation', 'Normalized standard deviation'), table


def taylor_pair(analyses, models):
    """Two positive-correlation panels with one legend controlling both."""
    fig = make_subplots(rows=1, cols=2, horizontal_spacing=.12,
                        subplot_titles=[VARIABLES[v][0] for v in ('T', 'q')])
    tables, seen = {}, set()
    for col, variable in enumerate(('T', 'q'), 1):
        panel, tables[variable] = taylor_plot(analyses[variable], models)
        for trace in panel.data:
            if trace.showlegend is not False:
                trace.legendgroup = trace.name
                trace.showlegend = trace.name not in seen
                seen.add(trace.name)
            fig.add_trace(trace, row=1, col=col)
        for annotation in panel.layout.annotations:
            item = annotation.to_plotly_json()
            item.pop('xref', None)
            item.pop('yref', None)
            fig.add_annotation(**item, row=1, col=col)
        fig.update_xaxes(range=list(panel.layout.xaxis.range), constrain='domain',
                         title_text=panel.layout.xaxis.title.text, row=1, col=col)
        fig.update_yaxes(range=list(panel.layout.yaxis.range), scaleanchor='x' if col == 1 else 'x2',
                         scaleratio=1, constrain='domain', title_text=panel.layout.yaxis.title.text, row=1, col=col)
    finish(fig, 'Normalized Taylor diagrams · positive correlations')
    fig.update_layout(height=650, legend=dict(groupclick='togglegroup', y=-.22), margin=dict(b=130))
    return fig, tables


def info_frame(analysis):
    return pd.DataFrame([dict(case_id=case, Case=analysis['case_labels'][case], model=model, dfs=d['dfs'], source=d['source'],
                              series=f"{model} · {d['source']}") for (case, model), d in analysis['information'].items()])


def dfs_height95(analysis):
    """Mean of individual-case 95%-of-layer-total heights, by band/source."""
    rows = []
    edges = np.asarray(analysis['edges'], dtype=float)
    for (case, model), item in analysis['information'].items():
        curve = np.asarray(item['cumulative'], dtype=float)
        height, reason = np.nan, ''
        if len(curve) != len(edges) or not np.isfinite(curve).all():
            reason = 'Missing/nonfinite cumulative profile'
        elif curve[-1]-curve[0] <= 0:
            reason = 'Nonpositive layer-total DFS'
        elif np.any(np.diff(curve) < -1e-10):
            reason = 'Nonmonotonic cumulative DFS'
        else:
            curve = np.maximum.accumulate(curve)
            target = curve[0] + .95*(curve[-1]-curve[0])
            i = int(np.searchsorted(curve, target, side='left'))
            height = float(np.interp(target, curve[i-1:i+1], edges[i-1:i+1]))
        rows.append(dict(case_id=case, Band=model, Source=item['source'], height95_km=height, exclusion=reason))
    cases = pd.DataFrame(rows, columns=['case_id', 'Band', 'Source', 'height95_km', 'exclusion'])
    summary = cases.groupby(['Band', 'Source'], sort=False).height95_km.agg(['mean', 'count', 'size']).reset_index()
    summary.columns = ['Band', 'Source', 'Mean 95% height (km AGL)', 'Valid cases', 'Total cases']
    return summary, cases


def info_plot(analysis, mode):
    df = info_frame(analysis)
    sources = list(df.source.unique())
    layer = f"{analysis['edges'][0]:g}–{analysis['edges'][-1]:g} km AGL"
    source_title = 'Diagnostic: '+', '.join(sources)
    models = sorted(df.model.unique(), key=model_sort)
    if mode == 'Layer distributions':
        fig = go.Figure()
        seen = set()
        for (model, source), group in df.groupby(['model', 'source'], sort=False):
            fig.add_trace(go.Box(x=[model]*len(group), y=group.dfs, name=model,
                legendgroup=model, offsetgroup=source, showlegend=model not in seen, boxpoints='all',
                marker_color=colors(models)[model],
                customdata=group[['Case', 'source']].to_numpy(),
                hovertemplate='%{customdata[0]}<br>%{customdata[1]}<br>DFS=%{y:.3f}<extra>%{fullData.name}</extra>'))
            seen.add(model)
        fig.update_layout(boxmode='group')
        fig.update_xaxes(categoryorder='array', categoryarray=models)
        return finish(fig, f'Accumulated DFS · {layer}<br>{source_title}', 'Band', 'DFS')
    # Keep diagnostic sources separate: auto mode can mix kernel and cdfs
    # records, whose values must not be pooled into one median.
    field = 'cumulative' if mode == 'Cumulative profiles' else 'density'
    fig = make_subplots(rows=1, cols=len(sources), shared_yaxes=True,
                        subplot_titles=sources if len(sources) > 1 else None)
    z = analysis['edges'] if field == 'cumulative' else analysis['centers']
    matrices, counts = [], []
    for source in sources:
        columns, ns = [], []
        for model in models:
            group = df.loc[df.model.eq(model) & df.source.eq(source)]
            values = [analysis['information'][(case, model)][field] for case in group.case_id]
            columns.append(np.median(values, axis=0) if values else np.full(len(z), np.nan))
            ns.append(len(values))
        matrices.append(np.column_stack(columns))
        counts.append(ns)
    finite = np.concatenate([m[np.isfinite(m)] for m in matrices])
    low = min(0., float(finite.min())) if len(finite) else 0.
    high = max(1e-9, float(finite.max())) if len(finite) else 1.
    palette = ['#ffffff', '#ffffd9', '#c7e9b4', '#7fcdbb', '#41b6c4', '#1d91c0', '#225ea8', '#253494', '#081d58']
    zero = -low/(high-low)
    scale = ([[0., '#b2182b']] if low < 0 else []) + [[zero+(1-zero)*i/(len(palette)-1), c] for i, c in enumerate(palette)]
    heights, _ = dfs_height95(analysis)
    for col, (source, matrix, ns) in enumerate(zip(sources, matrices, counts), 1):
        if field == 'cumulative':
            # One color per analysis interval, evaluated at its upper edge.
            # Explicit edges preserve the selected height grid without gaps.
            plot_z, values = analysis['edges'], matrix[1:]
        else:
            plot_z = np.linspace(analysis['edges'][0], analysis['edges'][-1], max(256, len(z)))
            values = np.column_stack([np.interp(plot_z, z, matrix[:, i]) for i in range(len(models))])
        fig.add_trace(go.Heatmap(x=models, y=plot_z, z=values, xgap=2, ygap=0, zsmooth=False,
            coloraxis='coloraxis', customdata=np.tile(ns, (len(values), 1)),
            hovertemplate='%{x}<br>Height: %{y:.3f} km<br>Median: %{z:.3f}<br>N=%{customdata}<extra>'+source+'</extra>'), row=1, col=col)
        if field == 'cumulative':
            subset = heights.loc[heights.Source.eq(source) & heights['Mean 95% height (km AGL)'].notna()]
            fig.add_trace(go.Scatter(x=subset.Band, y=subset['Mean 95% height (km AGL)'],
                mode='markers', name='Mean 95% DFS height', legendgroup='height95', showlegend=col == 1,
                marker=dict(symbol='line-ew', size=22, color='black', line=dict(width=2, color='black')),
                customdata=subset[['Valid cases', 'Total cases']].to_numpy(),
                hovertemplate='%{x}<br>Mean 95% height: %{y:.3f} km AGL<br>%{customdata[0]}/%{customdata[1]} valid cases<extra></extra>'), row=1, col=col)
        fig.update_xaxes(title_text='Band', tickangle=-45, row=1, col=col)
    units = 'Cumulative DFS' if field == 'cumulative' else 'DFS density (km⁻¹)'
    finish(fig, f'Median {units} · {layer}<br>{source_title}')
    fig.update_layout(coloraxis=dict(colorscale=scale, cmin=low, cmax=high, colorbar=dict(title=units)))
    fig.update_yaxes(title_text='Height AGL (km)', range=[analysis['edges'][0], analysis['edges'][-1]], row=1, col=1)
    return fig


def dfs_rmse_plot(analysis, individual=True):
    df = analysis['metrics'].dropna(subset=['dfs']).copy()
    df['series'] = df.model + ' · ' + df.dfs_source
    df['Case'] = df.case_id.map(analysis['case_labels'])
    fig = go.Figure()
    summary = []
    color_map = colors(sorted(df.model.unique(), key=model_sort))
    for series, group in df.groupby('series', sort=False):
        color = color_map[group.model.iloc[0]]
        if individual:
            fig.add_trace(go.Scatter(x=group.dfs, y=group.rmse, mode='markers', name=group.model.iloc[0], legendgroup=group.model.iloc[0], showlegend=False,
                                    marker=dict(color=color, opacity=0.35, size=7), text=group.Case+'<br>'+group.dfs_source,
                                    hovertemplate='%{text}<br>DFS=%{x:.3f}<br>RMSE=%{y:.3f}<extra></extra>'))
        summary.append(dict(series=series, n_cases=len(group), mean_dfs=group.dfs.mean(), mean_rmse=group.rmse.mean()))
        fig.add_trace(go.Scatter(x=[group.dfs.mean()], y=[group.rmse.mean()], mode='markers', name=group.model.iloc[0], legendgroup=group.model.iloc[0],
                                marker=dict(color=color, symbol='diamond', size=16, line=dict(color='white', width=1)),
                                error_x=dict(type='data', array=[group.dfs.std(ddof=0)]),
                                error_y=dict(type='data', array=[group.rmse.std(ddof=0)]),
                                text=[f'{series}<br>N={len(group)}; bars = population standard deviation'], hovertemplate='%{text}<br>DFS=%{x:.3f}<br>RMSE=%{y:.3f}<extra></extra>'))
    return finish(fig, f"{VARIABLES[analysis['variable']][0]} · {analysis['edges'][0]:g}–{analysis['edges'][-1]:g} km AGL", 'Accumulated DFS in selected layer', f"RMSE ({VARIABLES[analysis['variable']][1]})"), pd.DataFrame(summary)


def dfs_rmse_pair(analyses, individual=True):
    fig = make_subplots(rows=1, cols=2, subplot_titles=[VARIABLES[v][0] for v in ('T', 'q')], horizontal_spacing=.12)
    tables, seen = {}, set()
    for col, v in enumerate(('T', 'q'), 1):
        analysis = analyses[v]
        if analysis['metrics'].empty or not analysis['metrics'].dfs.notna().any():
            tables[v] = pd.DataFrame()
            fig.add_annotation(text='No matched DFS/RMSE cases', x=.5, y=.5,
                               xref='x domain' if col == 1 else 'x2 domain',
                               yref='y domain' if col == 1 else 'y2 domain', showarrow=False)
        else:
            panel, tables[v] = dfs_rmse_plot(analysis, individual)
            for trace in panel.data:
                if trace.showlegend is not False:
                    trace.showlegend = trace.name not in seen
                    seen.add(trace.name)
                fig.add_trace(trace, row=1, col=col)
        fig.update_xaxes(title_text='Accumulated DFS in selected layer', row=1, col=col)
        fig.update_yaxes(title_text=f'RMSE ({VARIABLES[v][1]})', row=1, col=col)
    edges = analyses['T']['edges']
    finish(fig, f'Information content versus retrieval error · {edges[0]:g}–{edges[-1]:g} km AGL')
    fig.update_layout(legend=dict(groupclick='togglegroup'), height=650)
    return fig, tables


def screening_plot(cases, x, y):
    data = case_metadata(cases)
    data[x], data[y] = pd.to_numeric(data[x], errors='coerce'), pd.to_numeric(data[y], errors='coerce')
    fig = px.scatter(data, x=x, y=y, color='category', symbol='asi_state',
                     hover_name='Case', hover_data=['radiance_state'],
                     color_discrete_map={'clear_sky': '#008A75', 'uncertain': '#CF8B19', 'not_clear_sky': '#C04D65'})
    return finish(fig, 'Cloud screening diagnostics', x, y)


def radiance_plot(cases, window, group_by, mean_limit, std_limit,
                  mean_enabled=False, std_enabled=False, categories=None):
    """One point per manifest case; threshold overlays never reclassify cases."""
    df = case_metadata(cases)
    x, y = f'radiance_{window}_radiance_mean', f'radiance_{window}_radiance_std'
    for field in (x, y):
        df[field] = pd.to_numeric(df[field], errors='coerce')
    df = df.loc[np.isfinite(df[x]) & np.isfinite(df[y])].copy()
    if categories is not None:
        df = df.loc[df[group_by].isin(categories)]
    order = GROUP_ORDERS.get(group_by, sorted(df[group_by].unique()))
    color_map = {name: px.colors.qualitative.Dark24[i % 24] for i, name in enumerate(order)}
    df['Group'] = df[group_by]
    fig = px.scatter(df, x=x, y=y, color=group_by, hover_name='Case',
                     category_orders={group_by: order}, color_discrete_map=color_map,
                     custom_data=['Case', 'Classification', 'ASI classification', 'Radiance classification', 'Group'])
    fig.update_traces(marker=dict(size=9, opacity=0.8, line=dict(width=0.5, color='white')),
                      hovertemplate='<b>%{customdata[0]}</b><br>Mean: %{x:.3f}<br>Std: %{y:.3f}'
                                    '<br>Class: %{customdata[1]}<br>ASI: %{customdata[2]}'
                                    '<br>Radiance: %{customdata[3]}<br>Group: %{customdata[4]}<extra></extra>')
    # Bounds include negative radiances if present, and always keep limits visible.
    xmin = min(0., float(df[x].min())) if len(df) else 0.
    ymin = min(0., float(df[y].min())) if len(df) else 0.
    xmax = max(mean_limit, float(df[x].max()) if len(df) else 0.)
    ymax = max(std_limit, float(df[y].max()) if len(df) else 0.)
    dx, dy = max(xmax-xmin, 1.)*0.08, max(ymax-ymin, .1)*0.12
    shade_x = mean_limit if mean_enabled else xmax+dx
    shade_y = std_limit if std_enabled else ymax+dy
    if mean_enabled or std_enabled:
        fig.add_shape(type='rect', x0=xmin-dx, x1=shade_x, y0=ymin-dy, y1=shade_y,
                      fillcolor='rgba(0,138,117,0.10)', line_width=0, layer='below')
    for value, enabled, name, add_line in [(mean_limit, mean_enabled, 'Mean', fig.add_vline),
                                         (std_limit, std_enabled, 'Std', fig.add_hline)]:
        label = f'{name} ≤ {value:g}' + (' (active)' if enabled else ' (reference; inactive)')
        add_line(value, line_dash='dash' if enabled else 'dot',
                 line_color='#008A75' if enabled else '#8795A8',
                 annotation_text=label, annotation_position='top left' if name == 'Mean' else 'top right',
                 exclude_empty_subplots=False,
                 annotation_font_size=12)
    fig.update_xaxes(range=[xmin-dx, xmax+dx])
    fig.update_yaxes(range=[ymin-dy, ymax+dy])
    finish(fig, f'985 cm⁻¹ radiance · {window.capitalize()} window',
           'Mean radiance (manifest units)', 'Radiance standard deviation (manifest units)')
    fig.update_layout(legend=dict(title_text=group_by, itemclick='toggle', itemdoubleclick='toggleothers'),
                      uirevision=f'radiance-{window}-{group_by}')
    return fig, df

