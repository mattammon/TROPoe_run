"""Detailed individual-band verification against observed sounding profiles."""
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st
import dashboard_data as data


def render_performance(cases, models, profiles, observations, edges, source, chart, download, correlation_models=None):
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
    analyses = {}
    for v in ('T', 'q'):
        analysis = data.build_analysis(cases, [model], profiles, observations, v, edges, paired=False)
        analyses[v] = analysis
        matrix = np.full((len(centers), len(ids)), np.nan)
        for j, cid in enumerate(ids):
            # Show available heights even when whole-layer metrics cannot be computed.
            ret, obs = profiles.get((cid, model)), observations.get(cid)
            if ret is not None and obs is not None and v in ret:
                matrix[:,j] = data.interpolate(ret,v,centers)-data.interpolate(obs,v,centers)
        bound = float(np.nanmax(np.abs(matrix))) if np.isfinite(matrix).any() else 1.
        bound = bound or 1.
        counts = np.isfinite(matrix).sum(axis=1)
        mean = np.divide(np.nansum(matrix,axis=1), counts,
                         out=np.full(len(centers),np.nan),where=counts>0)
        std_error = np.array([np.std(row[np.isfinite(row)],ddof=1) if np.isfinite(row).sum()>=2 else np.nan for row in matrix])
        fig = make_subplots(rows=1,cols=3,column_widths=[.84,.08,.08],shared_yaxes=True,
                            horizontal_spacing=.025,subplot_titles=('Cases','Mean error','Error SD'))
        for col, xx, zz in [(1,[labels[c] for c in ids],matrix),(2,['Mean'],mean[:,None])]:
            fig.add_trace(go.Heatmap(x=xx,y=centers,z=zz,colorscale='RdBu_r',
                zmin=-bound,zmax=bound,showscale=col==1,hoverongaps=False,
                colorbar=dict(title=data.VARIABLES[v][1],x=1.02,y=.78,len=.42),
                hovertemplate='%{x}<br>%{y:.2f} km AGL<br>Error: %{z:.3f}<extra></extra>'),1,col)
        fig.add_trace(go.Heatmap(x=['SD'],y=centers,z=std_error[:,None],
            colorscale='Purples',zmin=0,hoverongaps=False,
            colorbar=dict(title='SD',x=1.02,y=.22,len=.42),
            hovertemplate='Error SD: %{z:.3f}<br>%{y:.2f} km AGL<extra></extra>'),1,3)
        fig.update_layout(margin=dict(r=110))
        fig.update_layout(title=model+' · '+data.VARIABLES[v][0]+' · retrieved − observed',height=450)
        fig.update_yaxes(title_text='Height (km AGL)',row=1,col=1)
        chart(fig,'performance_errors_'+v)
    for v in ('T', 'q'):
        analysis = analyses[v]
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
    st.subheader('Profile correlation across collection bands')
    correlation_models = correlation_models or models
    for v in ('T','q'):
        metrics = data.build_analysis(cases,correlation_models,profiles,observations,v,edges,paired=False)['metrics']
        corr = np.full((len(correlation_models),len(ids)),np.nan)
        if not metrics.empty:
            lookup = metrics.set_index(['model','case_id']).correlation
            for i,band in enumerate(correlation_models):
                for j,cid in enumerate(ids):
                    corr[i,j] = lookup.get((band,cid),np.nan)
        std = np.array([np.std(row[np.isfinite(row)],ddof=1) if np.isfinite(row).sum()>=2 else np.nan for row in corr])
        mean_corr = np.array([np.mean(row[np.isfinite(row)]) if np.isfinite(row).any() else np.nan for row in corr])
        fig = make_subplots(rows=1,cols=3,column_widths=[.84,.08,.08],shared_yaxes=True,
                            horizontal_spacing=.04,subplot_titles=('Cases','SD','Mean r'))
        fig.add_trace(go.Heatmap(x=[labels[c] for c in ids],y=correlation_models,z=corr,
            colorscale='PiYG',zmin=-1,zmax=1,hoverongaps=False,
            colorbar=dict(title='r',x=1.02,y=.78,len=.42),
            hovertemplate='%{y}<br>%{x}<br>r = %{z:.3f}<extra></extra>'),1,1)
        fig.add_trace(go.Heatmap(x=['SD'],y=correlation_models,z=std[:,None],
            colorscale='Purples',zmin=0,zmax=1.42,hoverongaps=False,
            colorbar=dict(title='SD',x=1.02,y=.22,len=.42),
            hovertemplate='%{y}<br>Correlation SD = %{z:.3f}<extra></extra>'),1,2)
        fig.add_trace(go.Heatmap(x=['Mean'],y=correlation_models,z=mean_corr[:,None],
            colorscale='PiYG',zmin=-1,zmax=1,showscale=False,hoverongaps=False,
            hovertemplate='%{y}<br>Mean r = %{z:.3f}<extra></extra>'),1,3)
        fig.update_layout(margin=dict(r=110,b=140))
        fig.update_layout(title=data.VARIABLES[v][0],height=max(450,25*len(correlation_models)+200))
        chart(fig,'performance_correlations_'+v)
    st.caption('PiYG: Pearson r and arithmetic mean r (−1 to +1). Purple: sample standard deviation of r across cases '
               '(requires two valid correlations). All collection bands are included. '
               'Mean-error and error-SD columns summarize available cases separately at each height; SD uses ddof=1.')
    st.caption('Blank cells indicate unavailable data. Summary statistics require complete selected-layer coverage; '
               'each eligible case has equal weight. PWV is the observed sounding column, not the selected plotting layer.')

def render_profile_skew(case, models, profiles, row, source, chart):
    import streamlit as st
    from dashboard_review_sounding import read_review_sounding, skew_t_figure
    from dashboard_data import sounding_path, signature
    from pathlib import Path
    choices = st.multiselect('Retrievals on Skew-T', models, default=['Ch1'] if 'Ch1' in models else [], key='profile_skew_bands_v2')
    try:
        path = sounding_path(row.sounding_file, Path(source['master']).parent, source.get('sonde_root',''))
        p, t, td, z = read_review_sounding(signature(path))
        fig = skew_t_figure(p,t,td,z)
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
                    opacity=.5 if model == 'Ch1' else 1.,
                    line=dict(color=color,dash='solid' if model == 'Ch1' else 'dash',width=2),
                    hovertemplate=model+' '+label+': %{customdata:.1f} °C<br>%{y:.1f} hPa<extra></extra>'))
        chart(fig,'vertical_observed_skew')
        st.caption('Thick solid: observed. Faint solid: Ch1. Dashed: additional bands. Full pressure column; hover shows actual temperature.')
    except Exception as exc:
        st.warning('Skew-T unavailable: '+str(exc))


