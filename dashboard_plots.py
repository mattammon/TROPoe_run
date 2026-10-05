"""Interactive Plotly figures for the retrieval explorer."""
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from dashboard_data import VARIABLES, model_sort

PALETTE = ['#172B4D', '#007F86', '#D1495B', '#7057A3', '#C07800', '#167B48', '#356FDB', '#BA4C91']


def colors(models):
    return {m: PALETTE[0] if m == 'Ch1' else PALETTE[1+(int(m.split('_B')[1])-1) % (len(PALETTE)-1)] for m in models}


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
    unit = VARIABLES[analysis['variable']][1]
    if style == 'Distributions':
        fig = px.box(df, x='model', y='rmse', color='model', points='all',
                     hover_data=['case_id', 'time', 'bias', 'category'], color_discrete_map=colors(models),
                     category_orders={'model': models})
        return finish(fig, 'Case RMSE distributions', 'Retrieval band', f'RMSE ({unit})')
    if style == 'Timeline':
        fig = px.scatter(df, x='time', y='rmse', color='model', color_discrete_map=colors(models),
                         hover_data=['case_id', 'category', 'bias'])
        return finish(fig, 'RMSE through time', 'Sounding time (UTC)', f'RMSE ({unit})')
    matrix = df.pivot(index='case_id', columns='model', values='rmse').reindex(columns=models)
    matrix = matrix.reindex(df.sort_values('time').case_id.drop_duplicates())
    if baseline:
        matrix = matrix.subtract(matrix[baseline], axis=0)
    fig = go.Figure(go.Heatmap(z=matrix.T.values, x=matrix.index, y=matrix.columns,
                              colorscale='RdBu_r' if baseline else 'Viridis',
                              zmid=0 if baseline else None, colorbar=dict(title=f'Δ RMSE ({unit})' if baseline else f'RMSE ({unit})'),
                              hovertemplate='%{x}<br>%{y}<br>%{z:.3f}<extra></extra>'))
    return finish(fig, f'RMSE difference from {baseline}' if baseline else 'RMSE by case and band', 'Case (chronological)', 'Band')


def error_plot(analysis, model, mode):
    entries = [(case, data) for (case, band), data in analysis['curves'].items() if band == model]
    matrix = np.array([d['error'] for _, d in entries])
    unit = VARIABLES[analysis['variable']][1]
    if mode == 'Vertical RMSE':
        fig = go.Figure(go.Scatter(x=np.sqrt(np.mean(matrix**2, axis=0)), y=analysis['centers'],
                                  mode='lines', name=model))
        return finish(fig, f'{model} · RMSE across {len(entries)} cases', f'RMSE ({unit})', 'Height AGL (km)')
    fig = go.Figure(go.Heatmap(z=matrix.T, x=[c for c, _ in entries], y=analysis['centers'],
                              colorscale='RdBu_r', zmid=0, colorbar=dict(title=f'Error ({unit})')))
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
    finite_ratios = table.std_ratio[np.isfinite(table.std_ratio)] if len(table) else []
    radius = max(1.5, max(finite_ratios, default=1)*1.15)
    theta = np.linspace(0, np.pi, 240)
    for r in np.linspace(0, radius, 5)[1:]:
        fig.add_trace(go.Scatter(x=r*np.cos(theta), y=r*np.sin(theta), mode='lines',
                                line=dict(color='#D5DEE9', width=1), showlegend=False, hoverinfo='skip'))
    for corr in (-1, -0.8, -0.5, 0, 0.5, 0.8, 0.95, 1):
        x, y = radius*corr, radius*np.sqrt(1-corr**2)
        fig.add_trace(go.Scatter(x=[0, x], y=[0, y], mode='lines', line=dict(color='#E6EBF1', width=1), showlegend=False, hoverinfo='skip'))
        fig.add_annotation(x=x, y=y, text=str(corr), showarrow=False, yshift=8)
    for r in (0.25, 0.5, 1.0):
        x, y = 1+r*np.cos(theta), r*np.sin(theta)
        mask = x*x+y*y <= radius*radius
        fig.add_trace(go.Scatter(x=x[mask], y=y[mask], mode='lines', name=f'Centered RMSE / σobs = {r}',
                                line=dict(color='#9EADB9', dash='dot', width=1)))
    fig.add_trace(go.Scatter(x=[1], y=[0], mode='markers', marker=dict(symbol='star', size=15, color='black'), name='Radiosonde'))
    for row in table.itertuples():
        if not np.isfinite(row.correlation) or not np.isfinite(row.std_ratio):
            continue
        fig.add_trace(go.Scatter(x=[row.std_ratio*row.correlation], y=[row.std_ratio*np.sqrt(max(0, 1-row.correlation**2))],
                                mode='markers', name=row.model, marker=dict(size=13, color=colors(models)[row.model]),
                                text=[f'{row.model}<br>r={row.correlation:.4f}<br>σ/σobs={row.std_ratio:.3f}<br>RMSE={row.rmse:.3f}<br>N={row.cases} cases'],
                                hovertemplate='%{text}<extra></extra>'))
    fig.update_xaxes(range=[-radius*1.06, radius*1.06])
    fig.update_yaxes(range=[-0.05, radius*1.1], scaleanchor='x', scaleratio=1)
    return finish(fig, 'Normalized Taylor diagram · pooled height samples', 'σretrieval / σobserved × correlation', 'Normalized standard deviation component'), table


def info_frame(analysis):
    return pd.DataFrame([dict(case_id=case, model=model, dfs=d['dfs'], source=d['source'],
                              series=f"{model} · {d['source']}") for (case, model), d in analysis['information'].items()])


def info_plot(analysis, mode):
    df = info_frame(analysis)
    if mode == 'Layer distributions':
        fig = px.box(df, x='series', y='dfs', color='series', points='all', hover_data=['case_id'])
        return finish(fig, 'Accumulated DFS in the selected layer', 'Band · diagnostic source', 'DFS')
    fig = go.Figure()
    for (model, source), group in df.groupby(['model', 'source'], sort=False):
        field = 'cumulative' if mode == 'Cumulative profiles' else 'density'
        values = np.array([analysis['information'][(case, model)][field] for case in group.case_id])
        low, median, high = np.percentile(values, [25, 50, 75], axis=0)
        z = analysis['edges'] if field == 'cumulative' else analysis['centers']
        name = f'{model} · {source} · N={len(values)}'
        color = colors(sorted(df.model.unique(), key=model_sort))[model]
        fig.add_trace(go.Scatter(x=np.r_[low, high[::-1]], y=np.r_[z, z[::-1]], fill='toself', opacity=0.14,
                                line=dict(width=0, color=color), fillcolor=color,
                                name=name, legendgroup=name, showlegend=False, hoverinfo='skip'))
        fig.add_trace(go.Scatter(x=median, y=z, mode='lines', name=name, legendgroup=name, line=dict(color=color)))
    return finish(fig, 'DFS median and interquartile range', 'DFS accumulated from layer bottom' if mode == 'Cumulative profiles' else 'DFS density (km⁻¹)', 'Height AGL (km)')


def dfs_rmse_plot(analysis, individual=True):
    df = analysis['metrics'].dropna(subset=['dfs']).copy()
    df['series'] = df.model + ' · ' + df.dfs_source
    fig = go.Figure()
    summary = []
    color_map = colors(sorted(df.model.unique(), key=model_sort))
    for series, group in df.groupby('series', sort=False):
        color = color_map[group.model.iloc[0]]
        if individual:
            fig.add_trace(go.Scatter(x=group.dfs, y=group.rmse, mode='markers', name=series+' cases',
                                    marker=dict(color=color, opacity=0.35, size=7), text=group.case_id,
                                    hovertemplate='%{text}<br>DFS=%{x:.3f}<br>RMSE=%{y:.3f}<extra></extra>'))
        summary.append(dict(series=series, n_cases=len(group), mean_dfs=group.dfs.mean(), mean_rmse=group.rmse.mean()))
        fig.add_trace(go.Scatter(x=[group.dfs.mean()], y=[group.rmse.mean()], mode='markers', name=series+' mean',
                                marker=dict(color=color, symbol='diamond', size=16, line=dict(color='white', width=1)),
                                error_x=dict(type='data', array=[group.dfs.std(ddof=0)]),
                                error_y=dict(type='data', array=[group.rmse.std(ddof=0)]),
                                text=[f'N={len(group)}; bars = population standard deviation'], hovertemplate='%{text}<br>DFS=%{x:.3f}<br>RMSE=%{y:.3f}<extra></extra>'))
    return finish(fig, 'Information content versus retrieval error', 'Accumulated DFS in selected layer', f"RMSE ({VARIABLES[analysis['variable']][1]})"), pd.DataFrame(summary)


def screening_plot(cases, x, y):
    data = cases.copy()
    data[x], data[y] = pd.to_numeric(data[x], errors='coerce'), pd.to_numeric(data[y], errors='coerce')
    fig = px.scatter(data, x=x, y=y, color='category', symbol='asi_state',
                     hover_data=['case_id', 'sounding_time', 'radiance_state'],
                     color_discrete_map={'clear_sky': '#008A75', 'uncertain': '#CF8B19', 'not_clear_sky': '#C04D65'})
    return finish(fig, 'Cloud screening diagnostics', x, y)
