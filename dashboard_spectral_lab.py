"""Interactive spectral attribution and prior-constraint laboratory."""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

import dashboard_data as data
import spectral_debug as debug


@st.cache_data(show_spinner=False, ttl=60, max_entries=4)
def scan_archive(root):
    return debug.inventory(root)


@st.cache_data(show_spinner=False, max_entries=16)
def load_metadata(sig, record):
    return debug.read_companion(sig, record)


@st.cache_data(show_spinner=False, max_entries=6)
def load_analysis(files, sig, record, analysis_version=debug.ANALYSIS_VERSION):
    return debug.analyze(debug.read_iteration(files), load_metadata(sig, record))


def table_download(frame, name):
    st.download_button('Download '+name.replace('_',' '), frame.to_csv(index=False),
                       name+'.csv', 'text/csv', key='spectral_download_'+name)


def profiles(z, curves, title, unit, bottom, top):
    fig = go.Figure()
    colors = ['#777777','#0072B2','#D55E00','#111111','#009E73']
    for i,(name,values) in enumerate(curves.items()):
        fig.add_trace(go.Scatter(x=values, y=z, mode='lines', name=name,
            line=dict(color=colors[i%len(colors)], width=2.5, dash='dash' if 'Prior' in name else 'solid')))
    fig.update_layout(template='plotly_white', title=title, height=480,
                      xaxis_title=unit, yaxis_title='Height (km AGL)', legend=dict(orientation='h',y=-.2))
    fig.update_yaxes(range=[bottom,top])
    return fig


def heatmap(values, x, y, title, unit, diverging=True):
    finite = np.asarray(values)[np.isfinite(values)]
    limit = max(float(np.max(np.abs(finite))) if finite.size else 1.,1e-12)
    fig = go.Figure(go.Heatmap(z=values,x=x,y=y, colorscale='RdBu_r' if diverging else 'Viridis',
        zmin=-limit if diverging else None,zmax=limit if diverging else None,
        colorbar=dict(title=unit),hovertemplate='x: %{x}<br>y: %{y}<br>%{z:.5g}<extra></extra>'))
    fig.update_layout(template='plotly_white',title=title,height=520,margin=dict(b=150))
    return fig


def spectral_map(values, labels, y, bin_starts, model, width, title, unit,
                 chart, key, diverging=True, counts=None, ylabel='Height (km AGL)', correlation=False):
    x, matrix, limits = debug.channel_grid(values,labels,bin_starts,model,width)
    plot, controls = st.columns([5,1])
    with controls:
        st.caption('Reference optical thickness')
        h2o = st.checkbox('H₂O',key=key+'_h2o')
        co2 = st.checkbox('CO₂',key=key+'_co2')
    fig = heatmap(matrix,x,y,title,unit,diverging)
    fig.update_layout(plot_bgcolor='#d6d6d6', margin=dict(r=150,b=95),
        xaxis=dict(title='Wavenumber (cm⁻¹)',range=list(limits)),
        yaxis=dict(title=ylabel),
        yaxis2=dict(title='Reference τ (log)',type='log',overlaying='y',side='right',showgrid=False))
    fig.data[0].update(hoverongaps=False,colorbar=dict(title=unit,x=1.15))
    if correlation:
        fig.data[0].update(zmin=-1.,zmax=1.,zmid=0.,colorscale='PiYG')
    if counts is not None:
        _,count_matrix,_ = debug.channel_grid(counts,labels,bin_starts,model,width)
        fig.data[0].customdata=count_matrix
        fig.data[0].hovertemplate='%{y}<br>%{x:.1f} cm⁻¹<br>Mean %{z:.5g}<br>Cases %{customdata}<extra></extra>'
    if correlation:
        fig.data[0].hovertemplate='Height %{y:.3f} km<br>%{x:.1f} cm⁻¹<br>Pearson r %{z:.3f}<br>Paired cases %{customdata}<extra></extra>'
    if h2o or co2:
        try:
            ref = pd.read_csv(Path(__file__).parent/'reference_data'/'oxford_zenith_optical_depth.csv')
            ref = ref.loc[ref.wavenumber.between(*limits)]
            for gas,on,color in [('H2O',h2o,'#008cff'),('CO2',co2,'#ff8c00')]:
                if on:
                    fig.add_trace(go.Scatter(x=ref.wavenumber,y=ref[gas].where(ref[gas]>0),
                        mode='lines',name=gas+' reference τ',yaxis='y2',line=dict(color=color,width=1.3),
                        hovertemplate='%{x:.2f} cm⁻¹<br>τ %{y:.4g}<extra>%{fullData.name}</extra>'))
            fig.update_layout(legend=dict(orientation='h',y=1.12))
        except (OSError,ValueError,KeyError) as exc:
            st.warning('Reference optical thickness unavailable: '+str(exc))
    with plot: chart(fig,key)
    st.caption('Grey = no included IR observations / no available values in that bin; zero is a valid colored value. '
               'Auxiliary observations remain in tables, not on the wavenumber axis. Bins can contain partially sampled intervals.')
    if h2o or co2:
        st.caption('Reference: [Oxford EODG ATLAS](https://eodg.atm.ox.ac.uk/ATLAS/zenith-absorption), '
                   'RFM / HITRAN 2012 / US Standard Atmosphere. Published ~1 cm⁻¹ display dataset, '
                   'not case-specific or instrument-convolved optical depth; τ uses its own logarithmic right axis.')


def render_accuracy(a,table,sounding,variable,bottom,top,model,width,chart):
    st.subheader('Do the spectral contributions improve agreement with the radiosonde?')
    if sounding is None:
        st.info('Observed sounding unavailable; accuracy attribution cannot be computed.')
        return
    try:
        result = debug.accuracy_attribution(a,table,sounding,variable,bottom,top)
    except ValueError as exc:
        st.warning(str(exc));return
    st.dataframe(pd.DataFrame([result['stats']]),hide_index=True)
    st.latex(r'I_{jg}=c_{jg}(2s_j-x_{a,j}-x_{p,j}),\quad \sum_g I_{jg}=(x_{a,j}-s_j)^2-(x_{p,j}-s_j)^2')
    st.caption('Positive = allocated squared-error reduction; negative = allocated degradation. '
               's is the unsmoothed radiosonde interpolated to native AGL levels, xp is the proposed update, '
               'and cg is the signed contribution from a spectral bin. This exact additive allocation shares '
               'interactions symmetrically; it is not the causal effect of removing a bin. The proposal may differ from the saved final profile. '
               'RMSE uses the same finite native-level pairs for prior, proposal and final; no extrapolation or filling missing sounding values.')
    unit = '°C²' if variable=='T' else '(g/kg)²'
    starts = table.groupby('group').bin_start.first().to_dict()
    spectral_map(result['improvement'],result['labels'],result['z'],starts,model,width,
        variable+' · allocated squared-error improvement from prior to proposal',unit,
        chart,'spectral_accuracy_map')
    st.dataframe(result['groups'].sort_values('mse_improvement',ascending=False),hide_index=True)
    export = pd.DataFrame(result['improvement'],columns=result['labels'])
    export.insert(0,'height_km',result['z'])
    table_download(export,'spectral_accuracy_by_height')
    with st.expander('Individual spectral elements · accuracy allocation'):
        st.dataframe(result['elements'].sort_values('mse_improvement',ascending=False),hide_index=True)
        table_download(result['elements'],'spectral_element_accuracy')


def metadata_controls(cases, source, config):
    from cloud_screening import solar_zenith
    frame = data.case_metadata(cases)
    lon,lat = config.site_coordinates[config.SITE]
    zenith = solar_zenith(pd.DatetimeIndex(pd.to_datetime(frame.sounding_time,utc=True)),lat,lon)
    frame['Day/night'] = np.where(np.isfinite(zenith),np.where(zenith<90,'Day','Night'),'Unknown')
    frame['case_minute'] = pd.to_datetime(frame.sounding_time,utc=True).dt.strftime('%Y%m%d%H%M')
    with st.expander('Collection filters · apply together',expanded=True):
        cols = st.columns(3)
        keep = pd.Series(True,index=frame.index)
        for col,field in zip(cols,['Season','Day/night','Classification']):
            options = sorted(frame[field].dropna().unique())
            chosen = col.multiselect(field,options,default=options,key='spectral_filter_'+field)
            keep &= frame[field].isin(chosen)
        pwv_key = 'spectral_pwv:'+str((source['master'],source.get('master_hash'),tuple(cases.case_id)))
        if st.button('Compute / refresh observed sounding PWV',key='spectral_load_pwv'):
            from sounding_pwv import catalog_pwv, pwv_cache_path
            try:
                with st.spinner('Reading observed sounding PWV…'):
                    st.session_state[pwv_key] = catalog_pwv(cases,source['master'],source.get('sonde_root',''),
                        pwv_cache_path(source['master'],source['output']))
            except Exception as exc:
                st.error('PWV unavailable: '+str(exc))
        if pwv_key in st.session_state:
            frame = frame.drop(columns=['pwv_mm'],errors='ignore').merge(
                st.session_state[pwv_key][['case_id','pwv_mm']],on='case_id',how='left')
        if 'pwv_mm' not in frame:
            frame['pwv_mm'] = np.nan
        st.caption('PWV uses the observed sounding. Missing or partial-column PWV is excluded only when the PWV filter is enabled. Day/night uses solar zenith 90° at sounding time.')
        if st.checkbox('Filter PWV (mm)',key='spectral_filter_pwv'):
            a,b = st.columns(2)
            low = a.number_input('PWV minimum',min_value=0.,value=0.,key='spectral_pwv_min')
            high = b.number_input('PWV maximum',min_value=0.,value=100.,key='spectral_pwv_max')
            keep &= pd.to_numeric(frame.pwv_mm,errors='coerce').between(low,high)
        frame = frame.loc[keep.to_numpy()].copy()
    return frame


def single_attempt(frame, inventory, index, model, tolerance):
    labels = dict(zip(frame.case_id,frame.Case))
    known = set(inventory.loc[inventory.model.eq(model),'case_minute'])
    has_debug = dict(zip(frame.case_id,frame.case_minute.isin(known)))
    initial = next((i for i,c in enumerate(labels) if has_debug[c]),0)
    case = st.selectbox('Case',list(labels),index=initial,
        format_func=lambda c:labels[c]+(' · debug available' if has_debug[c] else ' · no archived debug'),key='spectral_case')
    row = frame.loc[frame.case_id.eq(case)].iloc[0]
    available = inventory.loc[inventory.case_minute.eq(row.case_minute)&inventory.model.eq(model)].sort_values('updated_ns',ascending=False)
    legacy = st.checkbox('Use an explicit debug directory / companion output',value=False,key='spectral_explicit')
    if not legacy:
        if available.empty:
            st.info('No debug attempt for this case and band. Run GROUP_TROPoe.py --debug for pending retrievals, or SINGLE_TROPoe.py with --debug --clobber for a deliberate rerun. You can also open older debug files using the explicit-directory option.')
            return None
        chosen = st.selectbox('Debug attempt',available.attempt.tolist(),key='spectral_attempt',
            format_func=lambda p: Path(p).name+' · '+available.set_index('attempt').loc[p,'status'])
        work = available.set_index('attempt').loc[chosen,'work']
        try:
            file,record = debug.companion_in_attempt(chosen,row.retrieval_time,tolerance)
        except Exception as exc:
            st.warning(str(exc)); return None
    else:
        work = st.text_input('Directory containing debug_output.*.cdf',key='spectral_work')
        file = st.text_input('Companion retrieval NetCDF from the same attempt',key='spectral_companion')
        record = int(st.number_input('Companion time index',min_value=0,value=0,key='spectral_record'))
        if not work or not file:
            return None
    try:
        sig = debug.signature(file)
        meta = load_metadata(sig,record)
        delta = abs((pd.to_datetime(meta['time'],utc=True)-pd.to_datetime(row.retrieval_time,utc=True)).total_seconds())
        if delta > tolerance:
            raise ValueError('Companion retrieval time does not match the selected case')
        # A named model guard supplements the numerical Y/Xa/Sa checks for legacy files.
        if not Path(file).name.startswith('tropoeOutput_'+model+'.'):
            raise ValueError('Companion filename does not identify the selected band')
        steps = debug.iterations(work)
        if not steps:
            raise ValueError('No saved Jacobian iterations in '+work)
        matches = debug.matching_final_steps(work,meta)
        default = max(matches) if matches else max(steps)
        step = st.selectbox('Iteration',steps,index=steps.index(default),key='spectral_iteration:'+str(work),
            format_func=lambda s: str(s)+(' · matches saved final state/kernel' if s in matches else ' · intermediate / proposed'))
        files = debug.iteration_signature(work,step)
        st.caption('Debug directory: '+str(work)+' · Companion: '+str(file)+f' [record {record}]')
        if not matches:
            st.warning('No saved debug Xn/kernel matches the final output. This attempt remains useful for iteration analysis but is excluded from the final-solution cohort analysis.')
        try:
            result = load_analysis(files,sig,record,debug.ANALYSIS_VERSION)
        except Exception as exc:
            st.error('Quantitative attribution disabled: '+str(exc))
            raw = debug.read_iteration(files)
            with st.expander('Inspect raw observations / forward calculation',expanded=True):
                table = pd.DataFrame({'Y':raw['Y'],'FXn':raw['FXn']})
                st.dataframe(table)
                table_download(table,'invalid_debug_observations')
            return None
        return result,work,step,row
    except Exception as exc:
        st.error('Debug data could not be loaded: '+str(exc)); return None


def render_attribution(a, w, table, chart, bottom, top, variable, sounding, model, width):
    raw,meta = a['raw'],a['meta']
    z,n = meta['z'],len(meta['z'])
    st.latex(r'd=y-F(x_n)+K(x_n-x_a),\quad x_{n+1}-x_a=Gd=\sum_i G_{:,i}d_i')
    st.caption('Signed terms reconstruct this iteration’s proposed departure from the prior. They are not independent causal effects of removing channels, and large opposing terms can cancel. The final output may use an earlier Xn or additional solver constraints.')
    for col,offset,label,unit in zip(st.columns(2),(0,n),('Temperature','Water vapor'),('°C','g/kg')):
        sl = slice(offset,offset+n)
        curves = {'Prior':raw['Xa'][sl], 'Current Xn':raw['Xn'][sl],
                  'Proposed Xn+1':a['proposed'][sl], 'Saved final':meta['Xop'][sl]}
        if sounding is not None:
            curves['Observed sounding'] = np.interp(z,sounding['z'],sounding['T' if offset==0 else 'q'],left=np.nan,right=np.nan)
        with col: chart(profiles(z,curves,label,unit,bottom,top),'spectral_states_'+str(offset))
    unit = '°C' if variable=='T' else 'g/kg'
    amounts = pd.DataFrame([dict(prior_feature=float(w@raw['Xa']),current_feature=float(w@raw['Xn']),
        proposed_feature=float(w@a['proposed']), saved_final_feature=float(w@meta['Xop']),
        observation_departure=float(table.feature_contribution.sum()),
        absolute_terms=float(table.absolute_contribution.sum()),
        cancellation=1-abs(table.feature_contribution.sum())/table.absolute_contribution.sum()
        if table.absolute_contribution.sum()>0 else np.nan)])
    st.write('Selected feature values ('+unit+') and cancellation (0 = same direction; 1 = complete cancellation)')
    st.dataframe(amounts,hide_index=True)
    offset = 0 if variable=='T' else n
    ids = np.flatnonzero((z>=bottom)&(z<=top))+offset
    labels, matrix, dfs = debug.grouped_contributions(a,table,ids)
    starts = table.groupby('group').bin_start.first().to_dict()
    spectral_map(matrix,labels,z[ids-offset],starts,model,width,
        variable+' · signed spectral contributions to proposed departure',unit,chart,'spectral_contribution_map')
    render_accuracy(a,table,sounding,variable,bottom,top,model,width,chart)
    ranked = table.groupby('group',sort=False).agg(
        signed=('feature_contribution','sum'),absolute=('absolute_contribution','sum'),
        absolute_share=('absolute_share','sum'),likelihood_pull=('likelihood_pull','sum'),
        channels=('obs_index','size'))
    ranked['layer_dfs'] = pd.Series(dict(zip(labels,dfs)))
    st.caption('Absolute share is a share of |feature contributions|, not a percentage of information or of the final profile. Group DFS sums G[j,i] K[i,j] over displayed levels and group observations; correlated-observation group values can be signed.')
    st.dataframe(ranked.sort_values('absolute',ascending=False))
    table_download(ranked.reset_index(),'spectral_group_attribution')
    ir = table.loc[table.flag.eq(1)].sort_values('coordinate')
    fig = make_subplots(rows=2,cols=1,shared_xaxes=True,vertical_spacing=.12,
                        subplot_titles=('Signed contribution to selected feature','Observed − calculated / saved 1σ uncertainty'))
    fig.add_trace(go.Scattergl(x=ir.coordinate,y=ir.feature_contribution,mode='markers',name='Feature contribution',
        customdata=ir[['obs_index','residual','innovation']],hovertemplate='%{x:.3f} cm⁻¹<br>Contribution %{y:.5g}<br>Obs row %{customdata[0]}<br>Residual %{customdata[1]:.5g}<br>Innovation %{customdata[2]:.5g}<extra></extra>'),row=1,col=1)
    fig.add_trace(go.Scattergl(x=ir.coordinate,y=ir.residual.where(~ir.sentinel_excluded)/ir.uncertainty.where(ir.uncertainty>0),mode='markers',name='Residual / σ'),row=2,col=1)
    fig.update_layout(template='plotly_white',height=650,showlegend=False)
    fig.update_yaxes(title_text=unit,row=1,col=1);fig.update_yaxes(title_text='Residual / σ',row=2,col=1)
    fig.update_xaxes(title_text='Wavenumber (cm⁻¹)',row=2,col=1)
    chart(fig,'spectral_element_contributions')
    st.caption('Only obs_flag=1 is plotted on a wavenumber axis. Surface T/q and other auxiliary observations remain separate in the table and all matrix calculations. Residual/σ is not a fully whitened residual when observations are correlated.')
    table_download(table,'spectral_element_attribution')


def render_prior(a,w,table,chart,bottom,top,amplitude):
    raw,meta = a['raw'],a['meta']
    n,z = len(meta['z']),meta['z']
    st.latex(r'A=GK,\quad R=I-A,\quad x_{n+1}-x_n=G[y-F(x_n)]-R(x_n-x_a)')
    st.write('A describes local response to atmospheric departures; R describes response to a changed prior mean with the Jacobian held fixed. There is no single observation percentage for an absolute temperature or humidity profile.')
    for col,offset,label,unit in zip(st.columns(2),(0,n),('Temperature','Water vapor'),('°C','g/kg')):
        sl = slice(offset,offset+n)
        with col:
            chart(profiles(z,{'Observational residual step':a['obs_step'][sl],
                'Prior restoring step':a['prior_step'][sl],
                'Net proposed step':(a['proposed']-raw['Xn'])[sl]},label+' · what drives this step?',unit,bottom,top),
                'spectral_step_'+str(offset))
            chart(profiles(z,{'diag(A)':np.diag(a['A'])[sl],
                'Prior sensitivity (covariance-scaled)':a['prior_sensitivity'][sl],
                'Reported σ / prior σ':np.sqrt(np.maximum(np.diag(raw['Sop'])[sl],0))/np.where(a['sigma'][sl]>0,a['sigma'][sl],np.nan)},
                label+' · local constraint diagnostics','Dimensionless',bottom,top),'spectral_constraint_'+str(offset))
    st.caption('diag(A) is the local DFS contribution, not a pointwise observation fraction. Prior sensitivity = sqrt(diag[R Sa Rᵀ] / diag[Sa]); it measures response to prior-mean perturbations shaped by Sa and can exceed 1. Reported Sop includes damping; it is not generally B⁻¹.')
    st.latex(r'J^T J=S_a^{1/2}K^T S_m^{-1}K S_a^{1/2},\quad f_k=\frac{\lambda_k}{\lambda_k+\gamma}')
    fig = go.Figure()
    mode = np.arange(1,len(a['eigenvalues'])+1)
    fig.add_trace(go.Scatter(x=mode,y=a['information_fraction'],name='Observation response',mode='lines+markers'))
    fig.add_trace(go.Scatter(x=mode,y=1-a['information_fraction'],name='Prior retention',mode='lines+markers'))
    if not np.isclose(a['gamma'],1.):
        fig.add_trace(go.Scatter(x=mode,y=a['eigenvalues']/(a['eigenvalues']+1.),
            name='Observation response if γ = 1',line=dict(dash='dot'),mode='lines'))
    fig.update_layout(template='plotly_white',title='Prior-whitened modes · observation versus prior',
                      xaxis_title='Mode (strongest observation constraint first)',yaxis_title='Local response fraction',height=440)
    chart(fig,'spectral_modes')
    mismatch = abs(a['information_fraction'].sum()-np.trace(a['A']))
    if a['prior_rank'] < len(raw['Xa']) or mismatch>1e-3:
        st.warning('Prior is numerically rank-deficient or modal DFS does not match trace(A). Modal fractions describe the supported prior subspace only; do not interpret their sum as full-state DFS.')
    st.caption('Modes mix levels, variables, and auxiliary states. These fractions describe the local linearized, gamma-weighted problem. Early iterations with large gamma intentionally retain more prior influence.')
    chosen = int(st.number_input('Inspect whitened mode',min_value=1,max_value=len(mode),value=1,key='spectral_mode'))-1
    perturbation = a['sa_root']@a['modes'][:,chosen]
    response = a['A']@perturbation
    for col,offset,label,unit in zip(st.columns(2),(0,n),('Temperature','Water vapor'),('°C','g/kg')):
        with col: chart(profiles(z,{'Unit whitened atmospheric mode':perturbation[offset:offset+n],
            'Recovered response':response[offset:offset+n]},label+' · mode '+str(chosen+1),unit,bottom,top),
            'spectral_mode_profile_'+str(offset))
    table_download(pd.DataFrame({'mode':mode,'lambda':a['eigenvalues'],'observation_fraction':a['information_fraction'],
                                'prior_retention':1-a['information_fraction']}),'spectral_modes')
    st.markdown('**Do different observations favor opposite changes?**')
    st.latex(r's_i=(K\,\delta x)_i\,[S_m^{-1}(y-F(x_n))]_i,\quad s_a=-\gamma\,\delta x^T S_a^{-1}(x_n-x_a)')
    st.caption('Positive score favors the specified signed perturbation in a first-order decrease of half the cost; negative opposes it. This is a directional likelihood test, distinct from the Gain × innovation attribution. Cross-observation precision terms are retained.')
    direction = amplitude*w/max(np.max(np.abs(w)),1e-30)
    prior_pull = -a['gamma']*float(direction@raw['SaInv']@(raw['Xn']-raw['Xa']))
    st.dataframe(pd.DataFrame([dict(observation_support=float(table.likelihood_pull.sum()),
        prior_support=prior_pull,net_support=float(table.likelihood_pull.sum()+prior_pull))]),hide_index=True)
    pulls = table.groupby('group',sort=False).likelihood_pull.sum().reset_index()
    fig = px.bar(pulls,x='group',y='likelihood_pull',color='likelihood_pull',color_continuous_scale='RdBu_r',color_continuous_midpoint=0)
    fig.update_layout(template='plotly_white',title='Spectral/auxiliary support for the selected perturbation',xaxis_title='',yaxis_title='First-order support')
    chart(fig,'spectral_likelihood_pull')


def render_experiment(a,w,table,chart,bottom,top,amplitude,sounding):
    st.write('Test whether stronger/weaker prior constraints or withholding an observed spectral interval changes the local solution. These are frozen-Jacobian experiments, not rerun retrievals or validated accuracy improvements.')
    scale = st.select_slider('Prior covariance multiplier (all states)',options=[.1,.25,.5,1.,2.,4.,10.,25.,100.],value=1.,key='spectral_prior_scale')
    st.caption('A factor of 4 doubles prior standard deviations and divides prior precision by 4. Gamma, K, observed data, and observation covariance stay fixed.')
    omit = None
    if st.checkbox('Withhold an infrared interval',key='spectral_withhold'):
        ir = table.loc[table.flag.eq(1)]
        if not ir.empty:
            c,d = st.columns(2)
            low = c.number_input('Withhold from (cm⁻¹)',value=float(ir.coordinate.min()),key='spectral_omit_low')
            high = d.number_input('Withhold to (cm⁻¹)',value=min(float(ir.coordinate.min())+10.,float(ir.coordinate.max())),key='spectral_omit_high')
            omit = (table.flag.eq(1)&table.coordinate.between(low,high)).to_numpy()
            st.caption(f'{omit.sum()} measured infrared elements withheld. Auxiliary observations remain.')
    try:
        result = debug.local_experiment(a,scale,omit)
    except Exception as exc:
        st.error('Experiment unavailable: '+str(exc));return
    raw,meta = a['raw'],a['meta']
    z,n = meta['z'],len(meta['z'])
    direction = amplitude*w/max(np.max(np.abs(w)),1e-30)
    prior_pull = -a['gamma']*float(direction@raw['SaInv']@(raw['Xn']-raw['Xa']))
    st.dataframe(pd.DataFrame([dict(baseline_total_dfs=float(np.trace(a['A'])),experiment_total_dfs=result['dfs'],
        feature_change=float(w@(result['state']-a['proposed'])),likelihood_support=float(table.likelihood_pull.sum()),
        prior_support=prior_pull,net_support=float(table.likelihood_pull.sum()+prior_pull),
        retained_observations=len(result['keep']))]),hide_index=True)
    for col,offset,label,unit in zip(st.columns(2),(0,n),('Temperature','Water vapor'),('°C','g/kg')):
        curves={'Prior':raw['Xa'][offset:offset+n],
            'Baseline proposed':a['proposed'][offset:offset+n], 'Experiment proposed':result['state'][offset:offset+n],
            'Saved final':meta['Xop'][offset:offset+n]}
        if sounding is not None:
            curves['Observed sounding']=np.interp(z,sounding['z'],sounding['T' if offset==0 else 'q'],left=np.nan,right=np.nan)
        with col: chart(profiles(z,curves,label+' · local experiment',unit,bottom,top),'spectral_experiment_'+str(offset))
    if sounding is not None:
        rows=[]
        for variable,offset in [('T',0),('q',n)]:
            target=np.interp(z,sounding['z'],sounding[variable],left=np.nan,right=np.nan)
            base=a['proposed'][offset:offset+n]; experiment=result['state'][offset:offset+n]
            valid=(z>=bottom)&(z<=top)&np.isfinite(target)&np.isfinite(base)&np.isfinite(experiment)
            if valid.any():
                base_rmse=float(np.sqrt(np.mean((base[valid]-target[valid])**2)))
                experiment_rmse=float(np.sqrt(np.mean((experiment[valid]-target[valid])**2)))
                rows.append(dict(variable=variable,levels=int(valid.sum()),baseline_rmse=base_rmse,
                    experiment_rmse=experiment_rmse,rmse_improvement=base_rmse-experiment_rmse))
        if rows:
            st.write('Local-experiment accuracy against the unsmoothed radiosonde')
            st.dataframe(pd.DataFrame(rows),hide_index=True)
            st.caption('Positive improvement = lower RMSE after the experiment. For a pure withholding test, '
                       'leave prior covariance multiplier at 1. A nonlinear rerun is needed to confirm the result.')
    st.info('A weakly recovered mode can reflect limited spectral sensitivity, noise, or prior constraints. A larger response after weakening the prior is not evidence of useful atmospheric information by itself. Check spectral residual structure, the sounding, and nonlinear reruns; broad biases or bad forward values can also drive large responses.')
    st.caption('Withholding uses the marginal covariance of retained observations reconstructed from the full active SmInv, then recomputes the gain. Subtracting group DFS alone is not equivalent to withholding. No inference is made about wavenumbers not observed by this band.')
    table_download(pd.DataFrame({'state_index':np.arange(len(result['state'])),'prior':raw['Xa'],
        'baseline_proposed':a['proposed'],'experiment_proposed':result['state'],
        'baseline_kernel_diagonal':np.diag(a['A']),'experiment_kernel_diagonal':np.diag(result['A'])}),'spectral_experiment')


def render_cohort_accuracy(metrics,spectra,model,variable,grouping,chart):
    st.subheader('Spectral share versus radiosonde accuracy')
    missing = metrics.loc[metrics.accuracy_error.ne('')]
    if not missing.empty:
        with st.expander('Unavailable sounding comparisons'):
            st.dataframe(missing[['case_id','model','variable','accuracy_error']],hide_index=True)
    if 'saved_rmse' not in metrics:
        st.info('No valid sounding comparisons. Other cohort diagnostics remain available.')
        return
    fields = ['case_id','model','variable','saved_rmse','prior_rmse','saved_rmse_improvement',
              'proposed_rmse','accuracy_levels','accuracy_total_levels']
    paired = spectra.merge(metrics[fields],on=['case_id','model','variable'],validate='many_to_one')
    paired = paired.loc[paired.model.eq(model)&paired.variable.eq(variable)&paired.saved_rmse.notna()]
    if paired.empty:
        st.info('No sounding pairs for this band and variable.');return
    outcome = st.selectbox('Accuracy outcome',['saved_rmse','saved_rmse_improvement','proposed_rmse'],
        format_func=lambda x:{'saved_rmse':'Saved final RMSE (lower is better)',
        'saved_rmse_improvement':'Prior RMSE − saved final RMSE (positive is better)',
        'proposed_rmse':'Proposed-update RMSE (lower is better)'}[x],key='spectral_accuracy_outcome')
    spectral_group = st.selectbox('Inspect spectral bin / auxiliary group',list(dict.fromkeys(paired.spectral_group)),
        key='spectral_accuracy_group')
    chosen = paired.loc[paired.spectral_group.eq(spectral_group)].copy()
    fig = px.scatter(chosen,x='absolute_share',y=outcome,color=grouping,hover_name='Case',
        hover_data=['contribution','gamma'] if 'gamma' in chosen else ['contribution'],opacity=.75)
    fig.update_layout(template='plotly_white',title=f'{model} {variable} · {spectral_group}',
        xaxis_title='Absolute contribution share',yaxis_title=outcome.replace('_',' ')+' ('+('°C' if variable=='T' else 'g/kg')+')')
    chart(fig,'spectral_accuracy_scatter')
    rows=[]
    for (regime,group),g in paired.groupby([grouping,'spectral_group'],dropna=False):
        g=g.loc[np.isfinite(g.absolute_share)&np.isfinite(g[outcome])]
        r=g.absolute_share.corr(g[outcome]) if len(g)>=3 and g.absolute_share.nunique()>1 and g[outcome].nunique()>1 else np.nan
        rows.append(dict(regime=regime,spectral_group=group,cases=len(g),
            mean_share=g.absolute_share.mean(),mean_outcome=g[outcome].mean(),pearson_r=r,
            mean_allocated_mse_improvement=g.mse_improvement.mean() if 'mse_improvement' in g else np.nan))
    summary=pd.DataFrame(rows)
    st.dataframe(summary,hide_index=True);table_download(summary,'spectral_accuracy_associations')
    table_download(paired,'spectral_accuracy_case_pairs')
    st.caption('Correlation uses paired cases (minimum 3, nonconstant values). Negative r with final RMSE '
               'means larger share accompanies lower error; positive r with RMSE improvement means larger '
               'share accompanies greater improvement. Shares are compositional and depend on innovation, '
               'gamma, other channels, prior and atmospheric state: these associations do not establish causality. '
               'Allocated MSE improvement concerns the proposal, not the saved final state. All errors use unsmoothed sondes.')


def render_profile_correlations(pairs,valid,model,variable,width,chart):
    st.subheader('Spectral contribution versus final absolute-error improvement by height')
    st.latex(r'\Delta |e|(z)=|x_a(z)-s(z)|-|x_{\mathrm{final}}(z)-s(z)|')
    st.caption('Positive Δ|e| means the saved final retrieval is closer to the radiosonde than the prior. '
               'Each cell correlates one spectral-bin contribution at that height with Δ|e| across paired cases '
               'in the selected band. Collection, season, day/night, classification, PWV, gamma and QC selections apply.')
    if pairs.empty:
        st.info('No valid sounding/contribution pairs are available for the height correlation.');return
    selected = pairs.merge(valid,on=['case_id','model','variable'],how='inner',validate='many_to_one')
    selected = selected.loc[selected.model.eq(model)&selected.variable.eq(variable)]
    if selected.empty:
        st.info('No paired profiles for this band and variable.');return
    cols=st.columns(2)
    minimum=int(cols[0].number_input('Minimum paired cases per cell',min_value=3,value=3,step=1,key='spectral_corr_min'))
    magnitude=cols[1].checkbox('Use contribution magnitude instead of signed contribution',key='spectral_corr_magnitude')
    result=debug.profile_correlations(selected,minimum,magnitude)
    pivot=result.pivot(index='height_km',columns='spectral_group',values='pearson_r')
    counts=result.pivot(index='height_km',columns='spectral_group',values='cases').reindex(index=pivot.index,columns=pivot.columns)
    starts=result.groupby('spectral_group').bin_start.first().to_dict()
    spectral_map(pivot.to_numpy(),pivot.columns,pivot.index,starts,model,width,
        f'{model} {variable} · '+('magnitude' if magnitude else 'signed contribution')+' vs final absolute-error improvement',
        'Pearson r',chart,'spectral_height_correlation',counts=counts.to_numpy(),correlation=True)
    st.caption('Signed mode: positive r means more positive (warming/moistening) contributions accompany greater error improvement; '
               'negative r can indicate beneficial cooling/drying. Magnitude mode asks whether stronger contributions accompany improvement. '
               'Correlation is not a causal attribution. Contributions are Gain × innovation evaluated at the final-matched iteration '
               'and describe its proposed update, not an exact decomposition of the saved final state. '
               'Profiles and signed bin contributions are linearly interpolated to the chosen common AGL grid before errors are computed; '
               'no extrapolation or spectral gap filling. Radiosondes are unsmoothed. Grey also includes insufficient pairs or constant values.')
    st.caption(f'{int(result.pearson_r.notna().sum())} of {len(result)} sampled cells have defined correlations. '
               'Pair counts for grey cells are available in the table/export below.')
    with st.expander('Correlation values and paired-case counts'):
        st.dataframe(result,hide_index=True)
        table_download(result,'spectral_height_correlations')
        table_download(selected,'spectral_height_case_pairs')


def render_cohort(frame,inventory,models,chart,bottom,top,bin_width,source):
    st.subheader('How do spectral use and prior influence vary across cases?')
    bands = st.multiselect('Cohort bands',models,default=models[:1],key='spectral_cohort_bands')
    eligible = inventory.loc[inventory.status.eq('finished')&inventory.model.isin(bands)].copy()
    # Latest finished attempt per minute/band; failed attempts never replace a finished one.
    eligible = eligible.sort_values('updated_ns').drop_duplicates(['case_minute','model'],keep='last')
    jobs = frame[['case_id','case_minute','retrieval_time','sounding_file']].merge(eligible,on='case_minute',how='inner')
    st.caption(f'{len(frame)} filtered cases · {len(jobs)} available finished case–band attempts. Only iterations matching the archived final Xn and kernel enter comparisons. Missing/invalid attempts are reported, never substituted from another case.')
    if jobs.empty:
        return
    height_spacing = st.number_input('Correlation height spacing (m)',min_value=10.,value=50.,step=10.,key='spectral_corr_spacing')
    height_grid = np.round(np.arange(bottom,top+1e-9,height_spacing/1000.),8)
    sig = debug.cohort_signatures(jobs.attempt)
    sounding_signatures = []
    for name in jobs.sounding_file:
        try:
            path = data.sounding_path(name,Path(source['master']).parent,source.get('sonde_root',''))
            sounding_signatures.append(data.signature(path))
        except Exception:
            sounding_signatures.append((str(name),'missing'))
    key = (debug.ANALYSIS_VERSION,tuple(jobs.case_id),tuple(jobs.model),sig,bottom,top,bin_width,tuple(sounding_signatures),height_spacing)
    if st.button('Compute / refresh cohort diagnostics',key='spectral_build_cohort'):
        progress = st.progress(0.,text='Reading debug attempts…')
        def report(i,n):
            progress.progress(i/n,text=f'Analyzing debug attempt {i}/{n}')
        def sounding_loader(row):
            path = data.sounding_path(row['sounding_file'],Path(source['master']).parent,source.get('sonde_root',''))
            return data.load_sounding(data.signature(path))
        profile_rows=[]
        result = debug.summarize_cohort(jobs.to_dict('records'),bottom,top,bin_width,report,sounding_loader,
                                       profile_rows,height_grid)
        result = (*result,pd.DataFrame(profile_rows))
        st.session_state.spectral_cohort_result = (key,result)
        progress.empty()
    saved = st.session_state.get('spectral_cohort_result')
    if saved is None or saved[0] != key:
        st.info('Press Compute / refresh cohort diagnostics for the current selection. Matrix files are read only on request; changed files or settings invalidate previous results.')
        return
    metrics,spectra,issues,profile_pairs = saved[1]
    if not metrics.empty:
        accepted = metrics.drop_duplicates(['case_id','model'])
        sentinel_cases = int(accepted.zero_influence_sentinel_rows.gt(0).sum())
        with st.expander('Final-state iteration selection · audit'):
            audit=accepted[['case_id','model','iteration','latest_available_iteration','matching_iterations',
                            'final_state_relative_error','final_kernel_relative_error']]
            st.dataframe(audit,hide_index=True);table_download(audit,'spectral_final_iteration_audit')
            st.caption('Selected by matching Xn and Akern to archived Xop and Akernal, never by latest iteration. '
                       'Multiple matches use the closest numerical match; exact ties use the earliest iteration.')
        st.success(f'{len(accepted)} case–band attempts included, including {sentinel_cases} with safely zero-influence sentinel rows. {len(issues)} attempts excluded.')
    if not issues.empty:
        with st.expander(f'Excluded attempts ({len(issues)})',expanded=True):
            st.dataframe(issues,hide_index=True);table_download(issues,'spectral_cohort_exclusions')
    if metrics.empty:
        st.warning('No valid final-matched debug attempts.');return
    metadata = frame[['case_id','Case','Season','Day/night','Time of day (UTC)','pwv_mm','Classification']]
    metrics = metrics.merge(metadata,on='case_id',how='left',validate='many_to_one')
    spectra = spectra.merge(metadata,on='case_id',how='left',validate='many_to_one')
    st.caption('Each case/band contributes once. These are observational associations, not proof that season or PWV causes prior influence. Gamma, QC, prior identity, native grid, and debug availability can confound comparisons.')
    st.caption('Prior sensitivity is sqrt(diag[(I−A) Sa (I−A)ᵀ] / diag[Sa]), averaged over selected native levels. It is a response ratio, not a prior percentage. Layer DFS is a sum over the selected native levels, so inspect the level-count columns when grids differ.')
    if st.checkbox('Only near-unit damping (γ ≈ 1)',key='spectral_gamma_one'):
        metrics = metrics.loc[np.isclose(metrics.gamma,1.,rtol=.01)]
        st.caption('This filter excludes γ ≠ 1 even if sentinel handling is valid.')
    if st.checkbox('Only qc_flag = 0',key='spectral_cohort_qc'):
        if 'qc_flag' in metrics:
            metrics = metrics.loc[metrics.qc_flag.eq(0)]
        else:
            metrics = metrics.iloc[:0]
    valid = metrics[['case_id','model','variable']].drop_duplicates()
    spectra = spectra.merge(valid,on=['case_id','model','variable'],how='inner')
    if metrics.empty:
        st.info('No cases pass damping/QC selections.');return
    metric = st.selectbox('Compare diagnostic',['layer_dfs','prior_sensitivity','sigma_ratio','departure_prior_sigma','gamma']+[f for f in ['saved_rmse','prior_rmse','saved_rmse_improvement','proposed_mse_improvement'] if f in metrics],key='spectral_cohort_metric',
        format_func=lambda x:dict(layer_dfs='Layer DFS (trace contribution)',prior_sensitivity='Mean covariance-scaled prior sensitivity',sigma_ratio='Mean reported σ / prior σ',departure_prior_sigma='RMS proposed departure / prior σ',gamma='Gamma (damping / prior weight)').get(x,x.replace('_',' ')))
    grouping = st.selectbox('Stratify by',['Season','Day/night','Time of day (UTC)','PWV bin'],key='spectral_cohort_group')
    if grouping == 'PWV bin':
        width = st.number_input('PWV bin width (mm)',min_value=1.,value=10.,key='spectral_pwv_bin')
        for f in (metrics,spectra):
            f['PWV bin'] = f.pwv_mm.map(lambda p:f'{np.floor(p/width)*width:g}–{(np.floor(p/width)+1)*width:g} mm' if np.isfinite(p) else 'Missing PWV')
    fig = make_subplots(rows=1,cols=2,subplot_titles=('Temperature','Water vapor'))
    colors = px.colors.qualitative.Dark24
    for i,model in enumerate(bands):
        for j,v in enumerate(('T','q'),1):
            subset = metrics.loc[metrics.model.eq(model)&metrics.variable.eq(v)]
            fig.add_trace(go.Box(x=subset[grouping],y=subset[metric],name=model,legendgroup=model,
                showlegend=j==1,boxpoints='all',jitter=.3,pointpos=0,
                marker=dict(color=colors[i%len(colors)],size=5,opacity=.55),
                text=subset.Case,hovertemplate='%{text}<br>%{x}<br>%{y:.4g}<extra>%{fullData.name}</extra>'),row=1,col=j)
    fig.update_layout(template='plotly_white',boxmode='group',title=metric.replace('_',' ')+f' · {bottom:g}–{top:g} km',height=520)
    chart(fig,'spectral_cohort_comparison')
    if metrics.pwv_mm.notna().any():
        fig = px.scatter(metrics,x='pwv_mm',y=metric,color='model',symbol='Season',facet_col='variable',
            hover_name='Case',hover_data=['gamma','prior_id'],opacity=.7,color_discrete_sequence=colors)
        fig.update_layout(template='plotly_white',title='Observed PWV and selected constraint metric',xaxis_title='PWV (mm)',height=470)
        chart(fig,'spectral_cohort_pwv')
    summary = metrics.loc[np.isfinite(metrics[metric])].groupby(['model','variable',grouping],dropna=False).agg(cases=('case_id','nunique'),
        mean=(metric,'mean'),median=(metric,'median'),std=(metric,'std'),mean_gamma=('gamma','mean'),
        prior_variants=('prior_id','nunique'),min_levels=('native_levels','min'),max_levels=('native_levels','max')).reset_index()
    st.dataframe(summary,hide_index=True);table_download(metrics,'spectral_cohort_case_metrics')
    table_download(summary,'spectral_cohort_group_summary')
    st.markdown('**Which spectral intervals matter under each regime?**')
    choice = st.selectbox('Spectral comparison band',bands,key='spectral_cohort_spec_band')
    v = st.radio('Spectral comparison variable',['T','q'],horizontal=True,key='spectral_cohort_spec_variable')
    smetric = st.selectbox('Spectral metric',['absolute_share','layer_dfs','contribution']+(['mse_improvement'] if 'mse_improvement' in spectra else []),key='spectral_cohort_spec_metric')
    sf = spectra.loc[spectra.model.eq(choice)&spectra.variable.eq(v)].copy()
    sf = sf.loc[np.isfinite(sf[smetric])]
    if not sf.empty:
        grouped = sf.groupby([grouping,'spectral_group'],dropna=False).agg(value=(smetric,'mean'),cases=('case_id','nunique')).reset_index()
        pivot = grouped.pivot(index=grouping,columns='spectral_group',values='value')
        count = grouped.pivot(index=grouping,columns='spectral_group',values='cases').reindex(index=pivot.index,columns=pivot.columns)
        starts = sf.groupby('spectral_group').bin_start.first().to_dict()
        spectral_map(pivot.to_numpy(),pivot.columns,pivot.index,starts,choice,bin_width,
            f'{choice} {v} · case-weighted mean '+smetric,smetric,chart,'spectral_cohort_spectra',
            smetric!='absolute_share',count.to_numpy(),grouping)
        st.caption('Bins use exact included observations, without interpolation across spectral gaps. Auxiliary groups remain separate. Hover for contributing case counts; absent bins are missing, not zero. Absolute shares are normalized within each case before averaging and measure contributions to the selected layer mean, not information fractions.')
    render_profile_correlations(profile_pairs,valid,choice,v,bin_width,chart)
    render_cohort_accuracy(metrics,spectra,choice,v,grouping,chart)
    table_download(spectra,'spectral_cohort_spectral_metrics')


def render_spectral_lab(cases,index,models,source,config,tolerance,chart):
    st.header('Spectral contribution laboratory')
    st.caption('Explore saved debug iterations: spectral attribution, observation versus prior constraint, and local band/prior experiments. This page never runs or modifies a retrieval.')
    if cases.empty or not models:
        st.info('Select cases and bands.');return
    root = st.text_input('Debug archive directory',value=getattr(config,'RETRIEVAL_DEBUG_DIR',''),key='spectral_root')
    if st.button('Refresh debug inventory',key='spectral_refresh'):
        scan_archive.clear();load_analysis.clear();load_metadata.clear()
        st.session_state.pop('spectral_cohort_result',None)
    try:
        inventory,issues = scan_archive(root)
    except Exception as exc:
        inventory = pd.DataFrame(columns=['case_minute','model','attempt','work','status','updated_ns'])
        issues = [dict(error=str(exc))]
    if issues:
        with st.expander('Debug discovery issues',expanded=inventory.empty):st.dataframe(pd.DataFrame(issues))
    frame = metadata_controls(cases,source,config)
    if frame.empty:
        st.info('No cases pass the filters.');return
    a,b,c = st.columns(3)
    bottom = a.number_input('Analysis bottom (km AGL)',min_value=0.,value=0.,key='spectral_bottom')
    top = b.number_input('Analysis top (km AGL)',min_value=0.,value=2.,key='spectral_top')
    width = c.number_input('Spectral bin width (cm⁻¹)',min_value=.5,value=10.,key='spectral_bin_width')
    if top<=bottom:
        st.warning('Top must exceed bottom.');return
    st.caption('All calculations retain the full native retrieval state; height limits select diagnostics and crop plots. Native levels are not smoothed or regridded.')
    mode = st.radio('Lab view',['One retrieval / iteration','Across cases'],horizontal=True,key='spectral_lab_view')
    if mode=='Across cases':
        render_cohort(frame,inventory,models,chart,bottom,top,width,source);return
    model = st.selectbox('Band',models,key='spectral_band')
    selected = single_attempt(frame,inventory,index,model,tolerance)
    if selected is None:return
    a,work,step,row = selected
    raw,meta = a['raw'],a['meta']
    st.dataframe(pd.DataFrame([dict(meta['qc'],iteration=step,debug_gamma=a['gamma'],
        total_dfs=float(np.trace(a['A'])),inactive_observations=a['inactive'],prior_id=a['prior_id'],solver=meta['version'])]),hide_index=True)
    st.caption(a['gamma_source']+'. Saved QC/gamma describe the final output; debug gamma describes the selected iteration.')
    if a['sentinel_inactive']:
        st.info(f'{a["sentinel_inactive"]} sentinel rows have exactly zero Jacobian and Gain and no off-diagonal precision coupling. They contribute zero to the update and are excluded from residual plots and diagnostic costs; raw values remain in exports.')
    if '09ab443' not in meta['version']:
        st.warning('Different/unknown solver revision. Algebra is checked against the upstream equations; verify any local source modifications.')
    variable = st.radio('Feature variable',['T','q'],horizontal=True,key='spectral_feature_variable')
    contrast = st.checkbox('Use layer minus mean of its two flanking layers (inversion / dry-layer contrast)',key='spectral_contrast')
    flank = st.number_input('Flanking layer width (km)',min_value=.05,value=.5,key='spectral_flank') if contrast else .5
    amplitude = st.number_input('Signed perturbation amplitude (°C for T; g/kg for q)',value=1.,key='spectral_amplitude',
        help='Positive adds the feature; negative tests cooling/drying. Used for directional likelihood/prior support scores.')
    try:
        w = debug.feature_weights(meta['z'],len(raw['Xa']),variable,bottom,top,contrast,flank)
        table = debug.observation_table(a,w,width,amplitude)
    except Exception as exc:
        st.warning(str(exc));return
    st.caption('Feature is an arithmetic mean over selected native levels, optionally minus the equal-weight average of lower/upper flanking means. It is not a mass-weighted layer average.')
    sounding = None
    if st.checkbox('Load observed sounding for profiles and accuracy comparisons',value=True,key='spectral_sonde'):
        try:
            path = data.sounding_path(row.sounding_file,Path(source['master']).parent,source.get('sonde_root',''))
            sounding = data.load_sounding(data.signature(path))
        except Exception as exc:st.warning('Sounding unavailable: '+str(exc))
    tab = st.radio('Diagnostic',['Spectral attribution','Observations vs prior','Band / prior experiments','Iteration history','Matrices and provenance'],horizontal=True,key='spectral_diagnostic')
    if tab=='Spectral attribution':render_attribution(a,w,table,chart,bottom,top,variable,sounding,model,width)
    elif tab=='Observations vs prior':render_prior(a,w,table,chart,bottom,top,amplitude)
    elif tab=='Band / prior experiments':render_experiment(a,w,table,chart,bottom,top,amplitude,sounding)
    elif tab=='Iteration history':
        if st.button('Read all saved iterations',key='spectral_history'):
            rows,failures=[],[]
            with st.spinner('Checking iteration history…'):
                for it in debug.iterations(work):
                    try:
                        diag=debug.analyze(debug.read_iteration(debug.iteration_signature(work,it)),meta)
                        rr=diag['raw']; sigma=np.where(diag['sigma']>0,diag['sigma'],np.nan)
                        rows.append(dict(iteration=it,gamma=diag['gamma'],dfs=float(np.trace(diag['A'])),
                            step_prior_sigma=float(np.sqrt(np.nanmean(((diag['proposed']-rr['Xn'])/sigma)**2))),
                            observation_cost=float(diag['diagnostic_residual']@rr['SmInv']@diag['diagnostic_residual']),
                            unweighted_prior_cost=float((rr['Xn']-rr['Xa'])@rr['SaInv']@(rr['Xn']-rr['Xa'])),
                            matches_final=debug.final_match(rr,meta)))
                    except Exception as exc:failures.append(dict(iteration=it,error=str(exc)))
            if rows:
                history=pd.DataFrame(rows)
                fig=make_subplots(rows=2,cols=2,subplot_titles=('Gamma','Total DFS','Proposed step / prior σ (RMS)','Observation residual quadratic cost'))
                for field,r,c in [('gamma',1,1),('dfs',1,2),('step_prior_sigma',2,1),('observation_cost',2,2)]:
                    fig.add_trace(go.Scatter(x=history.iteration,y=history[field],mode='lines+markers',name=field),row=r,col=c)
                fig.update_layout(template='plotly_white',height=650,showlegend=False)
                fig.update_xaxes(title='Iteration');chart(fig,'spectral_history_chart')
                st.dataframe(history,hide_index=True);table_download(history,'spectral_iteration_history')
                st.caption('The last written iteration need not be the saved solution. Costs here use debug SmInv and the current Xn, not the output rmsa/rmsr definitions. Lower residual cost alone does not establish convergence or atmospheric accuracy.')
            if failures:st.dataframe(pd.DataFrame(failures),hide_index=True)
    else:
        st.write('Saved Akern is transposed to obtain output × input A. K is observation × state; Gain is state × observation. Y/Xa/Sa must match the companion output before attaching physical labels.')
        st.dataframe(pd.DataFrame([a['checks']]),hide_index=True)
        st.caption('Relative reconstruction errors are checked against 1e−4. B = γ SaInv + Kᵀ SmInv K; B Gain = Kᵀ SmInv. No pickle or vip.npy files are loaded.')
        options = {key:raw[key] for key in ('Kij','Gain','Sa','SaInv','SmInv','B','Sop')}
        options.update({'A = G K':a['A'],'Prior response I − A':a['prior_response']})
        for key,label in [('Sa','Prior correlation'),('Sop','Reported posterior correlation')]:
            sigma=np.sqrt(np.maximum(np.diag(raw[key]),0))
            denom=np.outer(sigma,sigma)
            options[label]=np.divide(raw[key],denom,out=np.full_like(raw[key],np.nan),where=denom>0)
        options['Prior-whitened observation information']=a['sa_root']@a['K'].T@raw['SmInv']@a['K']@a['sa_root']
        name = st.selectbox('Matrix',list(options),key='spectral_matrix_selector')
        values = options[name]
        stride = max(1,int(np.ceil(max(values.shape)/400)))
        unit='Dimensionless' if 'correlation' in name or 'whitened' in name else 'Mixed units'
        fig = heatmap(values[::stride,::stride],np.arange(values.shape[1])[::stride],np.arange(values.shape[0])[::stride],name,unit)
        fig.update_xaxes(title='Column index (zero-based)');fig.update_yaxes(title='Row index (zero-based)')
        chart(fig,'spectral_matrix')
        st.caption(f'Plot stride {stride}; full matrix shape {values.shape}. Raw magnitudes mix physical units and should not be used alone to rank spectral value.')
        table_download(pd.DataFrame(values),'spectral_matrix_values')
        n=len(meta['z'])
        state_table=pd.DataFrame({'state_index':np.arange(len(raw['Xa'])),
            'variable':['T']*n+['q']*n+['Auxiliary']*(len(raw['Xa'])-2*n),
            'height_km':np.r_[meta['z'],meta['z'],np.full(len(raw['Xa'])-2*n,np.nan)],
            'Xa':raw['Xa'],'Xn':raw['Xn'],'Xnp1':raw['Xnp1'],'saved_final':meta['Xop']})
        table_download(state_table,'spectral_state_mapping')
        table_download(table,'spectral_observation_mapping')
    settings=dict(case_id=str(row.case_id),model=model,iteration=int(step),work=str(work),
        bottom_km=bottom,top_km=top,variable=variable,contrast=contrast,flank_km=flank,
        spectral_bin_width=width,perturbation_amplitude=amplitude,gamma=a['gamma'],prior_id=a['prior_id'],solver=meta['version'])
    st.download_button('Download analysis settings',json.dumps(settings,indent=2),
        'spectral_lab_settings.json','application/json',key='spectral_settings')
