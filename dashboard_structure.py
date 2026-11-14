"""Single-record exploration of native TROPoe state-space diagnostics."""
from pathlib import Path
import numpy as np
import pandas as pd
import xarray as xr
import plotly.graph_objects as go
import streamlit as st


@st.cache_data(show_spinner=False, max_entries=128)
def read_state(signature, record):
    with xr.open_dataset(signature[0]) as ds:
        sample = ds.isel(time=int(record), drop=True)
        z = np.asarray(ds.height, float)
        if str(ds.height.attrs.get('units', '')).lower() != 'km':
            raise ValueError('Expected native TROPoe height in km AGL')
        if z.ndim != 1 or not np.isfinite(z).all() or np.any(np.diff(z) <= 0):
            raise ValueError('Height must be finite and increasing')
        n = len(z)
        fields = {name: np.asarray(sample[name], float) for name in ('Xa','Xop','Akernal','Sa','Sop')}
        m = fields['Xa'].size
        if fields['Xa'].shape != (m,) or fields['Xop'].shape != (m,) or m < 2*n:
            raise ValueError('Unsupported state-vector layout')
        expected = np.r_[np.ones(n), np.full(n,2)]
        for name in ('arb1','arb2'):
            if not np.array_equal(np.asarray(sample[name])[:2*n], expected):
                raise ValueError('Unsupported T/q ordering in '+name)
        for name in ('Akernal','Sa','Sop'):
            if fields[name].shape != (m,m):
                raise ValueError('State dimensions disagree: '+name)
        if not all(np.isfinite(v).all() for v in fields.values()):
            raise ValueError('Nonfinite state or matrix values')
        for field, units in [('temperature',('degc','c','celsius')),('waterVapor',('g/kg','gkg-1'))]:
            if str(sample[field].attrs.get('units','')).lower().replace(' ','') not in units:
                raise ValueError('Expected native degC and g/kg state units')
        fields.update(z=z, version=str(ds.attrs.get('algorithm_code_version','unknown')),
                      qc={k: float(sample[k].values) for k in ('gamma','qc_flag','rmsa','rmsr','n_iter') if k in sample})
        fields['spectra'] = {k: np.asarray(sample[k],float).ravel() for k in
            ('obs_vector','forward_calc','obs_vector_uncertainty','obs_dimension','obs_flag') if k in sample}
        return fields


def covariance_correlation(cov):
    diagonal = np.diag(cov)
    denom = np.sqrt(np.outer(np.maximum(diagonal,0),np.maximum(diagonal,0)))
    return np.divide(cov,denom,out=np.full_like(cov,np.nan),where=denom>0)


def sonde_state(state, sounding, extend=False):
    z, xa = state['z'], state['Xa']
    n = len(z)
    sz = np.asarray(sounding['z'],float)
    if len(sz)<2 or not np.isfinite(sz).all() or np.any(np.diff(sz)<=0):
        raise ValueError('Invalid sounding heights')
    outside = (z<sz[0]) | (z>sz[-1])
    if outside.any() and not extend:
        raise ValueError('Sounding does not cover the full retrieval depth. Enable explicit prior extension to continue.')
    result = xa.copy()  # Unobserved cloud/gas departures are zero.
    for j,v in enumerate(('T','q')):
        values = np.interp(z,sz,sounding[v],left=np.nan,right=np.nan)
        if extend:
            values[outside] = xa[j*n:(j+1)*n][outside]
        if not np.isfinite(values).all():
            raise ValueError('Missing '+v+' inside the sounding column; interior gaps are not filled')
        result[j*n:(j+1)*n] = values
    return result, int(outside.sum())


def response(a, z, variable, center, width, amplitude, kind='Atmospheric feature'):
    delta = np.zeros(a.shape[0])
    n = len(z)
    offset = 0 if variable == 'T' else n
    delta[offset:offset+n] = amplitude*np.exp(-.5*((z-center)/width)**2)
    return delta, (a if kind == 'Atmospheric feature' else np.eye(len(a))-a) @ delta


def profile_plot(z, curves, title, unit, limits):
    fig = go.Figure()
    colors = ['#222222','#888888','#0072B2','#D55E00','#009E73','#CC79A7']
    for i,(name,values) in enumerate(curves.items()):
        fig.add_trace(go.Scatter(x=values,y=z,name=name,mode='lines',
            line=dict(color=colors[i%len(colors)],width=2,dash='dash' if 'Prior' in name else 'solid')))
    fig.update_layout(template='plotly_white',title=title,height=500,xaxis_title=unit,
                      yaxis_title='Height (km AGL)',legend=dict(orientation='h',y=-.2))
    fig.update_yaxes(range=list(limits))
    return fig


def render_structure(cases, index, models, source, tolerance, chart):
    import dashboard_data as data
    st.header('Vertical structure laboratory')
    st.caption('Explore one saved solution and its local sensitivity. No retrievals or classifications are changed.')
    if cases.empty or not models:
        st.info('Select a collection and at least one band.'); return
    labels = dict(zip(cases.case_id,cases.sounding_time.map(data.case_label)))
    left,right = st.columns(2)
    case = left.selectbox('Case',list(labels),format_func=labels.get,key='structure_case')
    model = right.selectbox('Band',models,key='structure_band')
    matched = data.match_cases(cases.loc[cases.case_id.eq(case)], index, [model], tolerance)
    matched = matched.loc[matched.file.ne('')]
    if matched.empty:
        st.info('No matched retrieval for this case and band.'); return
    hit = matched.iloc[0]
    try:
        state = read_state(data.signature(hit.file),int(hit.profile_index))
    except Exception as exc:
        st.error('Cannot load full diagnostic state: '+str(exc)); return
    z,xa,x = state['z'],state['Xa'],state['Xop']
    n = len(z)
    orientation = st.selectbox('Saved averaging-kernel convention',
        ['TROPoe upstream: transpose saved Akernal','Already output × input: use as stored'],key='structure_orientation')
    a = state['Akernal'].T if orientation.startswith('TROPoe') else state['Akernal']
    st.caption('Rows below are retrieved/output levels; columns are true/input levels. Upstream 09ab443 computes '
               'Akern=(G K).T and writes that matrix unchanged. Confirm this convention for modified solvers. '
               'Changing orientation is diagnostic, not a fit-tuning control.')
    if '09ab443' not in state['version']:
        st.warning('This file has a different or unknown solver revision; verify its kernel-writing convention.')
    st.dataframe(pd.DataFrame([dict(state['qc'], kernel_trace=float(np.trace(a)), solver=state['version'])]),hide_index=True)
    bottom,top = st.columns(2)
    lo = bottom.number_input('Display bottom (km AGL)',0.,float(z[-1]),0.,key='structure_lo')
    hi = top.number_input('Display top (km AGL)',0.,float(z[-1]),min(2.,float(z[-1])),key='structure_hi')
    if lo>=hi:
        st.warning('Display top must exceed bottom.'); return
    st.caption('Display limits only crop figures. Matrix products always use the full native state and vertical grid.')
    tabs = st.tabs(['Profiles and contributions','Kernel explorer','Covariance and uncertainty','Perturbation experiment','Spectral clues / provenance'])
    with tabs[0]:
        st.latex(r'x_{s,A}=x_a+A(x_s-x_a)')
        st.write('If the smoothed sounding exhibits the same displacement as the retrieval, the displacement is '
                 'consistent with the saved vertical sensitivity. A remaining difference is not a unique diagnosis: '
                 'nonlinearity, auxiliary states, radiance/model biases and sampling differences can contribute.')
        extend = st.checkbox('Use prior outside observed sounding height coverage',value=False,key='structure_extend')
        sounding = smoothed = truth = None
        try:
            row = cases.loc[cases.case_id.eq(case)].iloc[0]
            path = data.sounding_path(row.sounding_file,Path(source['master']).parent,source.get('sonde_root',''))
            sounding = data.load_sounding(data.signature(path))
            truth, extended = sonde_state(state,sounding,extend)
            smoothed = xa+a@(truth-xa)
            st.caption(f'{extended} native levels extended with prior. Unobserved cloud/gas state elements are held at prior; '
                       'temperature–humidity cross terms are retained. This is a linear diagnostic, not simulated truth.')
        except Exception as exc:
            st.warning('Smoothed sounding unavailable: '+str(exc))
        gradients = st.checkbox('Show vertical gradients instead of profiles',key='structure_gradient')
        for column,j,v,unit in zip(st.columns(2),(0,1),('Temperature','Water vapor'),('°C','g/kg')):
            sl = slice(j*n,(j+1)*n)
            curves = {'Prior':xa[sl],'Retrieved':x[sl]}
            if sounding is not None:
                curves['Observed'] = np.interp(z,sounding['z'],sounding['T' if j==0 else 'q'],left=np.nan,right=np.nan)
            if smoothed is not None: curves['AK-smoothed observed'] = smoothed[sl]
            if gradients: curves = {k:np.gradient(val,z) for k,val in curves.items()}
            with column:
                chart(profile_plot(z,curves,v,unit+('/km' if gradients else ''),(lo,hi)),'structure_profiles_'+str(j))
        if truth is not None:
            st.markdown('**What contributes to the smoothed sounding’s departure from the prior?**')
            for column,j,unit in zip(st.columns(2),(0,1),('°C','g/kg')):
                sl = slice(j*n,(j+1)*n)
                tpart = a[sl,:n]@(truth[:n]-xa[:n])
                qpart = a[sl,n:2*n]@(truth[n:2*n]-xa[n:2*n])
                curves = {'Retrieved − prior':x[sl]-xa[sl], 'T departure contribution':tpart,
                          'q departure contribution':qpart,'Sum (linear sonde response)':tpart+qpart}
                with column: chart(profile_plot(z,curves,'State contributions',unit,(lo,hi)),'structure_parts_'+str(j))
    with tabs[1]:
        output = st.radio('Output variable',['T','q'],horizontal=True,key='structure_output')
        input_var = st.radio('Input variable',['T','q'],horizontal=True,key='structure_input')
        oi,ii = (0 if output=='T' else n),(0 if input_var=='T' else n)
        block = a[oi:oi+n,ii:ii+n]
        bound = max(float(np.max(np.abs(block))),1e-12)
        fig = go.Figure(go.Heatmap(x=z,y=z,z=block,colorscale='RdBu_r',zmin=-bound,zmax=bound,
            colorbar=dict(title=f'{output}/{input_var}'),hovertemplate='Input %{x:.3f} km<br>Output %{y:.3f} km<br>%{z:.4f}<extra></extra>'))
        fig.update_layout(title=f'A: {input_var} input → {output} output',xaxis_title='Input height (km AGL)',yaxis_title='Output height (km AGL)')
        fig.update_xaxes(range=[lo,hi]);fig.update_yaxes(range=[lo,hi])
        chart(fig,'structure_kernel')
        level = st.select_slider('Native level to inspect',options=list(range(n)),format_func=lambda k:f'{z[k]:.3f} km AGL',key='structure_level')
        c1,c2 = st.columns(2)
        with c1: chart(profile_plot(z,{'Kernel row':block[level,:]},f'Sensitivity of output at {z[level]:.3f} km',f'{output}/{input_var}',(lo,hi)),'structure_row')
        with c2: chart(profile_plot(z,{'Kernel column':block[:,level]},f'Response to input at {z[level]:.3f} km',f'{output}/{input_var}',(lo,hi)),'structure_column')
        peak = int(np.argmax(np.abs(block[level,:])))
        st.caption(f'Largest absolute row sensitivity occurs at {z[peak]:.3f} km (offset {z[peak]-z[level]:+.3f} km). '
                   'A peak offset is not a measured inversion displacement. Kernels may be negative and are not probability distributions. '
                   'Cross-variable blocks have output/input units; same-variable blocks are dimensionless.')
    with tabs[2]:
        which = st.selectbox('Covariance',['Sa','Sop'],format_func=lambda s:'Prior covariance (Sa)' if s=='Sa' else 'Reported solution covariance (Sop)')
        corr = st.checkbox('Normalize to correlation',value=True,key='structure_cov_corr')
        block_name = st.selectbox('Covariance block',['T–T','q–q','T–q','Full state'])
        cov = covariance_correlation(state[which]) if corr else state[which]
        if block_name == 'Full state':
            xx=yy=np.arange(len(xa));values=cov;axis='State index (T, q, then auxiliary states)'
        else:
            r0 = n if block_name=='q–q' else 0
            c0 = 0 if block_name=='T–T' else n
            values=cov[r0:r0+n,c0:c0+n];xx=yy=z;axis='Height (km AGL)'
        bound=1. if corr else max(float(np.nanmax(np.abs(values))),1e-12)
        fig=go.Figure(go.Heatmap(x=xx,y=yy,z=values,colorscale='RdBu_r',zmin=-bound,zmax=bound,hoverongaps=False))
        fig.update_layout(title=which+' · '+block_name+(' correlation' if corr else ' covariance (native product units)'),xaxis_title=axis,yaxis_title=axis)
        if block_name!='Full state':fig.update_xaxes(range=[lo,hi]);fig.update_yaxes(range=[lo,hi])
        chart(fig,'structure_cov')
        for column,j,unit in zip(st.columns(2),(0,1),('°C','g/kg')):
            sl=slice(j*n,(j+1)*n)
            curves={name:np.sqrt(np.where(np.diag(state[field])[sl]>=0,np.diag(state[field])[sl],np.nan)) for name,field in [('Prior 1σ','Sa'),('Reported solution 1σ','Sop')]}
            with column:chart(profile_plot(z,curves,'Uncertainty',unit,(lo,hi)),'structure_sigma_'+str(j))
        st.caption('Prior off-diagonal correlations describe permitted co-variation, not vertical resolution. '
                   'Smaller reported uncertainty does not establish accuracy. Full-state raw covariance mixes units. '
                   'Sop is shown as saved; no γ=1 posterior identity is assumed.')
    with tabs[3]:
        st.write('Move a localized feature through the column and inspect its predicted response in BOTH variables.')
        kind=st.radio('Experiment',['Atmospheric feature','Prior-mean feature (fixed A)'],key='structure_kind')
        variable=st.radio('Perturbed variable',['T','q'],horizontal=True,key='structure_variable')
        center=st.slider('Feature center (km AGL)',float(z[0]),float(z[-1]),min(1.,float(z[-1])),step=.05)
        width=st.slider('Gaussian width σ (km)',.05,3.,.2,step=.05)
        amplitude=st.number_input('Amplitude ('+('°C' if variable=='T' else 'g/kg')+')',value=1.,step=.1)
        delta,out=response(a,z,variable,center,width,amplitude,kind)
        st.latex(r'\delta\hat{x}=A\,\delta x' if kind=='Atmospheric feature' else r'\delta\hat{x}\approx(I-A)\,\delta x_a')
        for column,j,unit in zip(st.columns(2),(0,1),('°C','g/kg')):
            sl=slice(j*n,(j+1)*n)
            with column:chart(profile_plot(z,{'Input perturbation':delta[sl],'Predicted response':out[sl]},('Temperature' if j==0 else 'Water vapor')+' response',unit,(lo,hi)),'structure_experiment_'+str(j))
        st.warning('This uses a fixed final kernel. It does not rerun LBLRTM, update the Jacobian, or recompute A. '
                   'The prior-mean experiment is a local linear approximation; changing prior covariance or conditioning '
                   'the prior by season requires a new retrieval. Large perturbations may violate the local approximation.')
        experiment=pd.DataFrame({'height_km_agl':z,'input_T':delta[:n],'input_q':delta[n:2*n],
                                 'response_T':out[:n],'response_q':out[n:2*n]})
        st.download_button('Download experiment',experiment.to_csv(index=False),'structure_experiment.csv','text/csv')
    with tabs[4]:
        st.code(str(hit.file),language='text');st.caption(f'Record {hit.profile_index} · matched time {hit.matched_time} · {state["version"]}')
        spec=state['spectra']
        if len(spec)==5:
            y,f,s=spec['obs_vector'],spec['forward_calc'],spec['obs_vector_uncertainty']
            valid=(spec['obs_flag']==1)&np.isfinite(y)&np.isfinite(f)&np.isfinite(s)&(s>0)&(y>-900)&(f>-900)&(f!=-777)
            st.caption(f'{int(((spec["obs_flag"]==1)&(f==-777)).sum())} IRS forward values flagged −777; excluded from this residual plot.')
            fig=go.Figure(go.Scatter(x=spec['obs_dimension'][valid],y=((y-f)/s)[valid],mode='markers',marker=dict(size=4)))
            fig.update_layout(title='IRS normalized residual (observed − calculated) / uncertainty',xaxis_title='Wavenumber (cm⁻¹)',yaxis_title='Residual / 1σ')
            chart(fig,'structure_residual')
        st.write('This NetCDF stores the final state and matrices, not the full iteration history or a unique decomposition '
                 'of retrieval error. Jacobian K and gain G are not reconstructed from A, Sa and Sop. Use debug outputs '
                 'to trace individual iterations or radiance-to-state adjustments.')
        st.markdown('[Verified upstream kernel computation](https://github.com/OAR-atmospheric-observations/TROPoe/blob/09ab443/TROPoe.py#L1934-L1941) · '
                    '[NetCDF writer](https://github.com/OAR-atmospheric-observations/TROPoe/blob/09ab443/Output_Functions.py#L1196-L1197)')
