"""Detailed individual-band verification against observed sounding profiles."""
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import dashboard_data as data


def render_performance(cases, models, profiles, observations, edges, source, chart, download):
    model = st.selectbox('Band to examine', models, key='performance_band')
    centers = (edges[:-1]+edges[1:])/2
    meta = data.case_metadata(cases)
    from sounding_pwv import catalog_pwv, pwv_cache_path
    import json
    cache_path = pwv_cache_path(source['master'], source['output'])
    key = 'observed_pwv:'+json.dumps([source['master'], source.get('master_hash'), source.get('sonde_root', ''), str(cache_path)])
    try:
        if key not in st.session_state:
            with st.spinner('Reading observed sounding PWV…'):
                st.session_state[key] = catalog_pwv(source['cases'], source['master'], source.get('sonde_root', ''), cache_path)
        meta = meta.drop(columns=['pwv_mm'], errors='ignore').merge(
            st.session_state[key][['case_id', 'pwv_mm']], on='case_id', how='left')
    except Exception as exc:
        st.warning('PWV unavailable: '+str(exc))
        meta['pwv_mm'] = np.nan
    meta['PWV bin (mm)'] = pd.cut(pd.to_numeric(meta.pwv_mm, errors='coerce'),
        bins=[0,10,20,30,40,50,60,np.inf], right=False).astype(str).replace('nan','Missing')
    grouping = st.selectbox('Compare performance by', ['Season', 'Time of day (UTC)', 'PWV bin (mm)'])
    st.caption(f'Metrics use all uniform height-bin centers in {edges[0]:g}–{edges[-1]:g} km AGL. '
               'RMSE and Pearson correlation are computed separately for each case against the raw observed profile. '
               'Correlation measures vertical co-variation, not bias or amplitude accuracy; constant profiles have undefined correlation.')
    ids = cases.sort_values('sounding_time').case_id.tolist()
    labels = cases.set_index('case_id').sounding_time.map(data.case_label)
    for v in ('T', 'q'):
        analysis = data.build_analysis(cases, [model], profiles, observations, v, edges, paired=False)
        matrix = np.full((len(centers), len(ids)), np.nan)
        for j, cid in enumerate(ids):
            # Show available heights even when whole-layer metrics cannot be computed.
            ret, obs = profiles.get((cid, model)), observations.get(cid)
            if ret is not None and obs is not None and v in ret:
                matrix[:,j] = data.interpolate(ret,v,centers)-data.interpolate(obs,v,centers)
        bound = float(np.nanmax(np.abs(matrix))) if np.isfinite(matrix).any() else 1.
        bound = bound or 1.
        fig = go.Figure(go.Heatmap(x=[labels[c] for c in ids], y=centers, z=matrix,
            colorscale='RdBu_r', zmin=-bound, zmax=bound, zmid=0,
            colorbar=dict(title=data.VARIABLES[v][1]), hoverongaps=False,
            hovertemplate='%{x}<br>%{y:.2f} km AGL<br>Error: %{z:.3f}<extra></extra>'))
        fig.update_layout(title=model+' · '+data.VARIABLES[v][0]+' · retrieved − observed',
            xaxis_title='Case (chronological; zoom to inspect)', yaxis_title='Height (km AGL)', height=450)
        chart(fig,'performance_errors_'+v)
        metrics = analysis['metrics']
        if metrics.empty:
            st.info('No complete-layer metrics for '+data.VARIABLES[v][0])
            continue
        metrics = metrics.merge(meta[['case_id',grouping,'pwv_mm']], on='case_id', how='left')
        summary = metrics.groupby(grouping, observed=True).agg(
            cases=('case_id','size'), mean_case_RMSE=('rmse','mean'),
            median_case_RMSE=('rmse','median'), mean_profile_correlation=('correlation','mean'),
            median_profile_correlation=('correlation','median'), valid_correlations=('correlation','count')).reset_index()
        st.markdown('**'+data.VARIABLES[v][0]+' performance by '+grouping+'**')
        st.dataframe(summary, hide_index=True)
        download('Download per-case '+v+' metrics',metrics,'band_performance_'+v+'.csv','performance_csv_'+v)
        download('Download grouped '+v+' metrics',summary,'band_performance_groups_'+v+'.csv','performance_groups_'+v)
        if not analysis['problems'].empty:
            with st.expander('Cases excluded from whole-layer '+v+' statistics'):
                st.dataframe(analysis['problems'], hide_index=True)
    st.caption('Blank cells indicate unavailable data. Summary statistics require complete selected-layer coverage; '
               'each eligible case has equal weight. PWV is the observed sounding column, not the selected plotting layer.')

def render_profile_skew(case, models, profiles, row, source, chart):
    import streamlit as st
    from dashboard_review_sounding import read_review_sounding, skew_t_figure
    from dashboard_data import sounding_path, signature
    from pathlib import Path
    choices = st.multiselect('Retrievals on Skew-T', models, default=models[:1], key='profile_skew_bands')
    try:
        path = sounding_path(row.sounding_file, Path(source['master']).parent, source.get('sonde_root',''))
        p, t, td = read_review_sounding(signature(path))
        fig = skew_t_figure(p,t,td)
        for model in choices:
            ret = profiles.get((case,model), {})
            if not all(k in ret for k in ('P','T','q')):
                st.caption(model+': pressure, temperature, or humidity unavailable.')
                continue
            pressure = np.asarray(ret['P'],float)
            q = np.asarray(ret['q'],float)
            valid = np.isfinite(pressure)&(pressure>0)&(pressure<=1100)
            with np.errstate(divide='ignore',invalid='ignore'):
                e = pressure*q/(622.+q)
                a = np.log(e/6.112)
                dew = 243.5*a/(17.67-a)
            dew[(q<=0)|~np.isfinite(q)] = np.nan
            for values,label,color in [(ret['T'],'T','#d62728'),(dew,'Td','#00884a')]:
                values = np.asarray(values,float)[valid]
                pp = pressure[valid]
                fig.add_trace(go.Scatter(x=values+35*np.log(1000/pp),y=pp,customdata=values,
                    mode='lines',name=model+' '+label,connectgaps=False,
                    line=dict(color=color,dash='dash',width=1.5),
                    hovertemplate=model+' '+label+': %{customdata:.1f} °C<br>%{y:.1f} hPa<extra></extra>'))
        chart(fig,'vertical_observed_skew')
        st.caption('Solid: observed. Dashed: retrieval. Full pressure column; hover shows actual temperature.')
    except Exception as exc:
        st.warning('Skew-T unavailable: '+str(exc))
