"""Explicit, side-by-side raw and AK-smoothed sonde verification."""
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from dashboard_data import build_analysis, VARIABLES
from dashboard_plots import colors, finish
from dashboard_vertical import plotly_size_kwargs


def render_ak_rmse(cases, models, profiles, observations, edges, paired,
                   display_chart, download_table, load_problems):
    st.subheader('RMSE against averaging-kernel-smoothed radiosondes')
    st.latex(r'x_{s}=x_a+A(x_{sonde}-x_a)')
    st.caption('Uses each matched retrieval’s full-observation Akernal and Xa at full native depth, '
               'including T–q cross terms, before selecting this layer. Non-T/q state components '
               'remain at the prior (zero departure). DFS-source/no-model controls do not change this metric. '
               'Raw and smoothed RMSE below always use the same eligible case–band pairs.')
    extension = st.checkbox('Use prior outside sounding height coverage', value=False, key='ak_prior_extension',
        help='Outside the sonde height range, set T/q to Xa. Interior missing values still exclude the case. '
             'Raw observations must cover the selected verification layer.')
    st.caption('Smoothed RMSE is band-specific: different kernels define different reference profiles. '
               'A low smoothed RMSE alone does not establish better resolution or atmospheric accuracy.')
    analyses = {v: build_analysis(cases, models, profiles, observations, v, edges, paired,
                                  reference='ak_smoothed', allow_prior_extension=extension) for v in ('T', 'q')}
    for column, variable in zip(st.columns(2), ('T', 'q')):
        with column:
            name, unit, _ = VARIABLES[variable]
            frame = analyses[variable]['metrics']
            st.subheader(name)
            if frame.empty:
                st.warning('No eligible comparisons. Inspect exclusions below.')
            else:
                fig = go.Figure()
                palette = colors(models)
                for band in models:
                    sub = frame.loc[frame.model.eq(band)]
                    fig.add_trace(go.Scatter(x=sub.raw_rmse, y=sub.rmse, mode='markers', name=band,
                        marker=dict(color=palette[band], size=8, opacity=.7),
                        text=sub.case_id.map(analyses[variable]['case_labels']),
                        hovertemplate='%{text}<br>Raw RMSE: %{x:.3f}<br>AK-smoothed RMSE: %{y:.3f}<extra>%{fullData.name}</extra>'))
                upper = max(float(frame[['raw_rmse','rmse']].max().max())*1.05, .01)
                fig.add_shape(type='line', x0=0, y0=0, x1=upper, y1=upper, line=dict(color='gray', dash='dash'))
                finish(fig, f'{name} · raw vs AK-smoothed RMSE<br>{edges[0]:g}–{edges[-1]:g} km AGL',
                       f'Raw-sonde RMSE ({unit})', f'AK-smoothed-sonde RMSE ({unit})')
                fig.update_xaxes(range=[0,upper])
                fig.update_yaxes(range=[0,upper])
                display_chart(fig, 'ak_rmse_'+variable)
                summary = frame.groupby('model', sort=False).agg(
                    cases=('rmse','size'), mean_raw_rmse=('raw_rmse','mean'),
                    mean_ak_rmse=('rmse','mean'), median_raw_rmse=('raw_rmse','median'),
                    median_ak_rmse=('rmse','median'),
                    cases_with_prior_extension=('prior_extension_levels',lambda x: int((x>0).sum()))).reset_index()
                st.dataframe(summary, hide_index=True, **plotly_size_kwargs(st.dataframe))
                download_table('Download '+name+' summary', summary, 'ak_rmse_'+variable+'_summary.csv', 'ak_summary_'+variable)
                frame = frame.assign(auxiliary_policy='prior (zero departure)',
                    allow_prior_extension=extension, layer_bottom_km=edges[0], layer_top_km=edges[-1],
                    kernel_source='Akernal', paired=paired)
                download_table('Download '+name+' case metrics', frame, 'ak_rmse_'+variable+'_cases.csv', 'ak_cases_'+variable)
            with st.expander(name+' exclusions'):
                st.dataframe(analyses[variable]['problems'], **plotly_size_kwargs(st.dataframe))
    if load_problems:
        with st.expander('Retrieval and sounding load errors'):
            st.dataframe(pd.DataFrame(load_problems), **plotly_size_kwargs(st.dataframe))
