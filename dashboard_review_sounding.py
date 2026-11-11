"""Observed ascent temperature/dewpoint on interactive Skew-T log-P axes."""
import numpy as np
import plotly.graph_objects as go
import streamlit as st
import xarray as xr
from pathlib import Path
from dashboard_data import _convert, sounding_path, signature


@st.cache_data(show_spinner=False, max_entries=256)
def read_review_sounding(file_signature):
    with xr.open_dataset(file_signature[0]) as ds:
        p, t = _convert(ds.pres, 'P'), _convert(ds.tdry, 'T')
        z = np.asarray(ds.alt.values, float).ravel()
        rh = np.asarray(ds.rh.values, float).ravel()
        unit = str(ds.rh.attrs.get('units', '%')).strip().lower()
        if unit in ('1', 'fraction'):
            rh *= 100.
        elif unit not in ('%', 'percent', 'percentage'):
            raise ValueError('Unsupported RH units: '+unit)
    if not len(p) == len(t) == len(z) == len(rh):
        raise ValueError('Sounding variables have different lengths')
    keep, top = [], -np.inf
    for i, height in enumerate(z):
        if np.isfinite(height) and height > top:
            keep.append(i)
            top = height
    p, t, rh = p[keep], t[keep], rh[keep]
    t[(t < -150) | (t > 60) | ~np.isfinite(t)] = np.nan
    with np.errstate(divide='ignore', invalid='ignore'):
        a = np.log(rh/100.) + 17.67*t/(t+243.5)
        td = 243.5*a/(17.67-a)
    td[(rh <= 0) | (rh > 100) | ~np.isfinite(rh)] = np.nan
    valid = np.isfinite(p) & (p > 0) & (p <= 1100)
    p, t, td = p[valid], t[valid], td[valid]
    if np.isfinite(t).sum() < 2:
        raise ValueError('Fewer than two valid ascent temperatures')
    return p, t, td


def skew_t_figure(p, t, td):
    # Linear skew in log-pressure coordinates: a constant T slopes up/right.
    skew = lambda temp, pressure: temp + 35.*np.log(1000./pressure)
    fig = go.Figure()
    grid = np.geomspace(1050., 100., 100)
    for temp in range(-120, 51, 10):
        fig.add_trace(go.Scatter(x=skew(temp, grid), y=grid, mode='lines',
            line=dict(color='#cccccc' if temp else '#888888', width=1),
            showlegend=False, hoverinfo='skip'))
    for values, label, color in [(t, 'Temperature', '#d62728'), (td, 'Dewpoint', '#00884a')]:
        fig.add_trace(go.Scatter(x=skew(values, p), y=p, customdata=values, mode='lines',
            name=label, connectgaps=False, line=dict(color=color, width=3.5),
            hovertemplate=label+': %{customdata:.1f} °C<br>%{y:.1f} hPa<extra></extra>'))
    fig.update_layout(template='plotly_white', title='Observed sounding · Skew-T log-P',
        height=480, margin=dict(l=55, r=15, t=55, b=60),
        xaxis=dict(title='Temperature (°C at 1000 hPa)', range=[-40, 50], dtick=10, showgrid=False),
        yaxis=dict(title='Pressure (hPa)', type='log', range=[np.log10(1050), 2],
                   tickmode='array', tickvals=[1000, 925, 850, 700, 500, 400, 300, 250, 200, 150, 100]),
        legend=dict(orientation='h', y=1.08), uirevision='review-skew-t')
    return fig


def render_review_sounding(row, source, key):
    try:
        path = sounding_path(row.sounding_file, Path(source['master']).parent, source.get('sonde_root', ''))
        p, t, td = read_review_sounding(signature(path))
        st.plotly_chart(skew_t_figure(p, t, td), use_container_width=True,
                        key=key+'_skew_t', config={'displaylogo': False})
        st.caption('Observed ascent only; dewpoint derived from measured temperature and RH. '
                   'Follow the sloping gray isotherms to read temperature. No retrieval smoothing applied.')
        if np.isfinite(td).sum() < 2:
            st.warning('Insufficient valid humidity for a dewpoint profile.')
        with st.expander('Sounding source'):
            st.code(str(path), language='text')
    except Exception as exc:
        st.warning('Observed sounding unavailable: '+str(exc))

