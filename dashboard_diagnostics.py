"""DFS comparison and per-case uncertainty views (no Streamlit dependency)."""
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from dashboard_data import VARIABLES
from dashboard_plots import finish, dfs_height95, colors
from information_content import remap_dfs

SEQUENTIAL = ['#ffffff', '#ffffd9', '#c7e9b4', '#7fcdbb', '#41b6c4', '#1d91c0', '#225ea8', '#253494', '#081d58']


def profile_heatmap(matrix, edges, models, title, unit, difference=False, counts=None, cumulative_variable=None):
    """One shaded cell per height interval, with no vertical cell borders."""
    fig = go.Figure()
    matrix = np.asarray(matrix, float)
    actual = matrix.copy()
    delta = matrix.copy()
    if difference:
        for j, model in enumerate(models):
            if model == 'Ch1':
                delta[:, j] = np.nan
            else:
                actual[:, j] = np.nan
    n = np.tile(counts if counts is not None else [1]*len(models), (matrix.shape[0], 1))
    fig.add_trace(go.Heatmap(x=models, y=edges, z=actual, xgap=2, ygap=0, zsmooth=False, hoverongaps=False,
        coloraxis='coloraxis', customdata=n,
        hovertemplate='%{x}<br>Height bin: %{y:.3f} km<br>Value: %{z:.3f}<br>Cases: %{customdata}<extra></extra>'))
    finite = actual[np.isfinite(actual)]
    low = min(0., float(finite.min())) if len(finite) else 0.
    high = max(1e-9, float(finite.max())) if len(finite) else 1.
    fig.update_layout(coloraxis=dict(colorscale=SEQUENTIAL if low >= 0 else 'RdBu_r',
        cmin=low if low >= 0 else -max(abs(low),high), cmax=high if low >= 0 else max(abs(low),high),
        colorbar=dict(title=('Ch1 actual<br>' if difference else '')+unit, x=1.02)))
    if cumulative_variable is not None:
        # Discrete terrain_r intervals, shared by case and aggregate plots.
        from matplotlib import colormaps
        from matplotlib.colors import to_hex
        maximum = {'T': 5., 'q': 3.}[cumulative_variable]
        shades = [to_hex(colormaps['terrain_r'](x)) for x in np.linspace(0, 1, 100)]
        scale = [[edge, color] for i, color in enumerate(shades)
                 for edge in (i/len(shades), (i+1)/len(shades))]
        fig.update_layout(coloraxis=dict(colorscale=scale, cmin=0., cmax=maximum,
            colorbar=dict(tick0=0, dtick=1 if maximum == 5 else .5)))
    if difference:
        fig.add_trace(go.Heatmap(x=models, y=edges, z=delta, xgap=2, ygap=0, zsmooth=False, hoverongaps=False,
            coloraxis='coloraxis2', customdata=n,
            hovertemplate='%{x}<br>Height bin: %{y:.3f} km<br>Band − Ch1: %{z:.3f}<br>Paired cases: %{customdata}<extra></extra>'))
        finite = delta[np.isfinite(delta)]
        extent = max(1e-9, float(np.max(np.abs(finite)))) if len(finite) else 1.
        fig.update_layout(coloraxis2=dict(colorscale='RdBu_r', cmin=-extent, cmax=extent,
            colorbar=dict(title='Δ '+unit, x=1.22)))
    finish(fig, title, 'Band', 'Height AGL (km)')
    fig.update_layout(margin=dict(r=230 if difference else 100))
    fig.update_xaxes(categoryorder='array', categoryarray=models, tickangle=-45)
    fig.update_yaxes(range=[edges[0], edges[-1]])
    return fig


def dfs_profile_panels(analysis, models, mode, difference=False):
    """Median profiles per source; differences use same-case/same-source pairs."""
    info = analysis['information']
    field = 'cumulative' if mode == 'Cumulative profiles' else 'density'
    edges = analysis['edges']
    models = list(dict.fromkeys((['Ch1'] if difference else [])+list(models)))
    sources = sorted({v['source'] for (case, band), v in info.items() if band in models})
    panels = []
    for source in sources:
        columns, counts, used = [], [], {}
        for band in models:
            values = []
            for (case, model), item in info.items():
                if model != band or item['source'] != source:
                    continue
                value = np.asarray(item[field], float)
                if difference and band != 'Ch1':
                    reference = info.get((case, 'Ch1'))
                    if reference is None or reference['source'] != source:
                        continue
                    value = value-np.asarray(reference[field], float)
                if not np.isfinite(value).all():
                    continue
                values.append(value[1:] if field == 'cumulative' else value)
                used[(case, band)] = item
            columns.append(np.median(values, axis=0) if values else np.full(len(edges)-1, np.nan))
            counts.append(len(values))
        matrix = np.column_stack(columns)
        unit = 'DFS' if field == 'cumulative' else 'DFS / km'
        title = f"{VARIABLES[analysis['variable']][0]} · {mode} · {edges[0]:g}–{edges[-1]:g} km AGL<br>Diagnostic: {source}"
        if difference:
            title += ' · median paired differences from Ch1'
        fig = profile_heatmap(matrix, edges, models, title, unit, difference, counts,
            cumulative_variable=analysis['variable'] if field == 'cumulative' else None)
        if field == 'cumulative':
            heights, _ = dfs_height95(dict(analysis, information=used))
            for row in heights.itertuples(index=False, name=None):
                band, _, height, valid, total = row
                if np.isfinite(height):
                    fig.add_trace(go.Scatter(x=[band], y=[height], mode='markers', showlegend=False,
                        marker=dict(symbol='line-ew', size=20, color='black', line=dict(width=2)),
                        hovertemplate=f'{band}<br>Mean full-column 95% height: {height:.3f} km AGL<br>{valid}/{total} cases<extra></extra>'))
        panels.append((source, fig, pd.DataFrame({'Band':models, 'Cases':counts})))
    return panels


def case_diagnostic(case, profiles, models, variable, edges, mode):
    columns, issues, sources = [], [], set()
    centers = (edges[:-1]+edges[1:])/2
    for band in models:
        profile = profiles.get((case,band))
        values = np.full(len(centers), np.nan)
        source = ''
        try:
            if profile is None:
                raise ValueError('No loaded retrieval')
            if mode == '1-sigma uncertainty':
                key = 'sigma_'+variable
                if key not in profile:
                    raise ValueError(profile.get('errors', {}).get(key, 'Missing '+key))
                values = np.interp(centers, profile['z'], profile[key], left=np.nan, right=np.nan)
                source = 'sigma_temperature' if variable == 'T' else 'sigma_waterVapor'
            else:
                item = profile.get('information', {}).get('variables', {}).get(variable)
                if item is None:
                    raise ValueError(profile.get('information', {}).get('errors', {}).get(variable, 'Missing DFS diagnostic'))
                source = item['source']
                mapped = remap_dfs(profile['z'], item['dfs_level'], edges)
                values = mapped['cumulative'][1:] if mode == 'Cumulative DFS' else mapped['density']
            if not np.isfinite(values).all():
                issues.append(dict(Band=band, Variable=variable, Diagnostic=source, Issue='Missing values or incomplete layer coverage'))
        except (KeyError, ValueError) as exc:
            issues.append(dict(Band=band, Variable=variable, Diagnostic=source, Issue=str(exc)))
        if source:
            sources.add(source)
        columns.append(values)
    matrix = np.column_stack(columns) if columns else np.empty((len(centers),0))
    unit = VARIABLES[variable][1] if mode == '1-sigma uncertainty' else 'DFS' if mode == 'Cumulative DFS' else 'DFS / km'
    fig = profile_heatmap(matrix, edges, models,
        f'{VARIABLES[variable][0]} · {mode} · {edges[0]:g}–{edges[-1]:g} km AGL<br>Diagnostic: '+', '.join(sorted(sources)), unit,
        cumulative_variable=variable if mode == 'Cumulative DFS' else None)
    export = pd.DataFrame(matrix, columns=models)
    export.insert(0, 'height_km', edges[1:] if mode == 'Cumulative DFS' else centers)
    export.insert(1, 'bin_bottom_km', edges[:-1])
    export.insert(2, 'bin_top_km', edges[1:])
    return fig, export, pd.DataFrame(issues)


def rmsr_summary(case, profiles, models):
    rows = []
    for band in models:
        profile = profiles.get((case,band), {})
        row = dict(Band=band, QC=profile.get('qc_flag', np.nan))
        for key, label in [('rmsr', 'RMSR'), ('rmsa', 'RMSA'), ('gamma', 'Gamma')]:
            value = profile.get(key, np.nan)
            row[label] = value if np.isfinite(value) else np.nan
        rows.append(row)
    table = pd.DataFrame(rows).sort_values(['RMSA','Band'], na_position='last').reset_index(drop=True)
    table.insert(0,'Rank',table.RMSA.rank(method='min').astype('Int64'))
    available = table.loc[table.RMSA.notna()]
    fig = go.Figure(go.Bar(x=available.RMSA, y=available.Band, orientation='h',
        marker=dict(color=[colors(models)[m] for m in available.Band]),
        hovertemplate='%{y}<br>RMSA: %{x:.4f}<extra></extra>'))
    finish(fig, 'Spectral RMSA by band · lower values first', 'RMSA (output value)', 'Band')
    fig.update_yaxes(autorange='reversed')
    return table, fig
