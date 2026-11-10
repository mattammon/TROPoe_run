"""Live coverage of manually selected case collections."""
import json
import calendar
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from cloud_screening import solar_zenith
from sounding_pwv import pwv_cache_path


def coverage_figures(frame, lon, lat):
    frame = frame.drop_duplicates('case_id')
    times = pd.to_datetime(frame.sounding_time, utc=True, errors='coerce')
    seasons = [('Winter (DJF)', [12, 1, 2], '#0072B2'),
               ('Spring (MAM)', [3, 4, 5], '#009E73'),
               ('Summer (JJA)', [6, 7, 8], '#D55E00'),
               ('Autumn (SON)', [9, 10, 11], '#CC79A7')]
    month = go.Figure()
    for label, months, color in seasons:
        counts = times.dt.month.value_counts()
        month.add_bar(x=months, y=[int(counts.get(m, 0)) for m in months],
                      name=f'{label}: {int(times.dt.month.isin(months).sum())}',
                      marker_color=color)
    month.update_xaxes(tickmode='array', tickvals=list(range(1, 13)),
                       ticktext=list(calendar.month_abbr)[1:], range=[0.5, 12.5],
                       title='Month (all years)')
    valid = times.notna()
    period = pd.Series('Unknown', index=frame.index)
    if valid.any():
        zenith = np.asarray(solar_zenith(pd.DatetimeIndex(times[valid]), lat, lon))
        period.loc[valid] = np.where(np.isfinite(zenith),
                                    np.where(zenith < 90, 'Day', 'Night'), 'Unknown')
    hour = go.Figure()
    for label, color in [('Day', '#E69F00'), ('Night', '#663399'), ('Unknown', '#999999')]:
        counts = times.loc[period.eq(label)].dt.hour.value_counts()
        hour.add_bar(x=list(range(24)), y=[int(counts.get(h, 0)) for h in range(24)],
                     name=f'{label}: {int(period.eq(label).sum())}', marker_color=color)
    hour.update_layout(barmode='stack')
    hour.update_xaxes(title='Sounding hour (UTC)', dtick=3, range=[-0.5, 23.5])
    pwv = pd.to_numeric(frame.get('pwv_mm', pd.Series(np.nan, index=frame.index)), errors='coerce')
    pwv = pwv[np.isfinite(pwv) & (pwv >= 0)]
    edges = np.arange(0, max(60., (np.floor(pwv.max()/5)+1)*5 if len(pwv) else 60.)+5, 5.)
    counts, edges = np.histogram(pwv, bins=edges)
    water = go.Figure(go.Bar(x=(edges[:-1]+edges[1:])/2, y=counts, width=4.7,
                             marker_color='#1655a0', customdata=np.column_stack([edges[:-1], edges[1:]]),
                             hovertemplate='%{customdata[0]}–%{customdata[1]} mm: %{y} cases<extra></extra>'))
    water.update_xaxes(title='Observed PWV (mm)', range=[0, edges[-1]])
    for fig, title in zip((month, hour, water), ('Month / season', 'Hour / day and night', 'Observed sounding PWV')):
        fig.update_layout(title=title, template='plotly_white', height=360,
                          margin=dict(l=35, r=10, t=50, b=90),
                          legend=dict(orientation='h', y=-0.3), bargap=0.1)
        fig.update_yaxes(title='Cases', rangemode='tozero', dtick=1 if len(frame)<10 else None)
    return (month, hour, water), int(times.isna().sum()), len(frame)-len(pwv)


def render_collection_coverage(preview, chosen, source):
    import config
    frame = preview.loc[preview.case_id.isin(chosen)].drop_duplicates('case_id').copy()
    cache_path = pwv_cache_path(source['master'], source['output'])
    cache_key = 'observed_pwv:'+json.dumps([source['master'], source.get('master_hash'),
                                          source.get('sonde_root', ''), str(cache_path)])
    table = st.session_state.get(cache_key)
    if table is not None:
        frame = frame.drop(columns=['pwv_mm'], errors='ignore').merge(
            table[['case_id', 'pwv_mm']], on='case_id', how='left', validate='one_to_one')
    lon, lat = config.site_coordinates[config.SITE]
    figures, missing_time, missing_pwv = coverage_figures(frame, lon, lat)
    st.markdown('#### Collection coverage')
    st.caption(f'{len(frame):,} collection cases, including those hidden by plot filters. '
               'Day/night uses solar zenith at sounding time (day <90°; night includes twilight).')
    for column, fig, name in zip(st.columns(3), figures, ('month', 'hour', 'pwv')):
        column.plotly_chart(fig, use_container_width=True, key='collection_coverage_'+name,
                            config={'displaylogo': False})
    st.caption(f'Missing sounding time: {missing_time}; missing/incomplete observed PWV: {missing_pwv}. '
               'These cases remain in the collection but are excluded from the corresponding histogram.')
