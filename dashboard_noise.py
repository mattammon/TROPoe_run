"""Case-weighted infrared noise spectra, with explicit instrument/effective sources."""
from pathlib import Path
import numpy as np
import pandas as pd
import xarray as xr
import plotly.graph_objects as go
import streamlit as st
import dashboard_data as data
from cloud_screening import dataset_times, solar_zenith

FLOOR_WN = np.array([500,522,546,575,600,631,747,1439,1770,1884,2217,3000])
FLOOR_NOISE = np.array([65.309,14.056,3.283,1.333,.813,.557,.304,.581,.822,.025,.023,.044])


def numeric(value):
    if isinstance(value, str):
        value = value.strip('[]').replace(',', ' ').split()
    return np.asarray(value, dtype=float).ravel()


@st.cache_data(show_spinner=False, max_entries=5000)
def read_retrieval(signature, record):
    with xr.open_dataset(signature[0]) as ds:
        def values(name):
            a = ds[name]
            return np.asarray(a.isel(time=record) if 'time' in a.dims else a).ravel()
        mask = values('obs_flag') == 1
        wn, noise = values('obs_dimension')[mask], values('obs_vector_uncertainty')[mask]
        valid = np.isfinite(wn) & np.isfinite(noise) & (noise > 0)
        wn, noise = wn[valid], noise[valid]
        order = np.argsort(wn)
        wn, noise = wn[order], noise[order]
        if not len(wn):
            raise ValueError('No positive finite IRS uncertainties')
        attrs = ds.attrs
        recorded = all('VIP_'+key in attrs for key in ('irs_min_noise_wnum', 'irs_min_noise_spec'))
        fw = numeric(attrs['VIP_irs_min_noise_wnum']) if recorded else FLOOR_WN
        fn = numeric(attrs['VIP_irs_min_noise_spec']) if recorded else FLOOR_NOISE
        if len(fw) != len(fn) or len(fw) < 2 or not np.all(np.diff(fw) > 0) or not np.all(np.isfinite(fn)):
            raise ValueError('Invalid recorded minimum-noise spectrum')
        floor = np.interp(wn, fw, fn, left=np.nan, right=np.nan)
        enabled = str(attrs.get('VIP_irs_min_noise_flag', 'unknown'))
        return wn, noise, floor, ('Recorded VIP' if recorded else 'Upstream reference (settings absent)'), enabled


@st.cache_data(show_spinner=False, max_entries=64)
def read_summary(signature, channel):
    with xr.open_dataset(signature[0]) as ds:
        names = [f'SkyNENCh{channel}', f'SkyNENch{channel}', f'ch{channel}_sky_nen']
        field = next((n for n in names if n in ds), None)
        if field is None:
            raise ValueError('No channel noise variable: '+', '.join(names))
        time = dataset_times(ds)
        td = ds['time'].dims[0] if 'time' in ds and ds.time.ndim == 1 else ds['time_offset'].dims[0]
        wn_names = [f'wnumsum{channel+4}', f'wnumsum{channel}', f'wnum{channel}']
        name = next((n for n in wn_names if n in ds), None)
        if name is None:
            raise ValueError('No summary wavenumber coordinate')
        wn = np.asarray(ds[name]).ravel()
        a = ds[field]
        sd = [d for d in a.dims if d != td]
        if len(sd) != 1:
            raise ValueError('Unexpected noise dimensions')
        noise = np.asarray(a.transpose(td, sd[0]), dtype=float)
        noise[~np.isfinite(noise) | (noise <= 0)] = np.nan
        order = np.argsort(wn)
        return pd.DatetimeIndex(pd.to_datetime(time, utc=True)), wn[order], noise[:, order]


def nearest_noise(summaries, target, wn, tolerance):
    best = None
    target = pd.Timestamp(target)
    for path, (times, grid, values) in summaries:
        delta = np.abs((times-target).total_seconds())
        finite = np.flatnonzero(np.isfinite(delta))
        if not len(finite):
            continue
        i = finite[np.argmin(delta[finite])]
        if delta[i] <= tolerance and (best is None or delta[i] < best[0]):
            # Preserve missing samples; never extrapolate outside instrument grid.
            best = (delta[i], np.interp(wn, grid, values[i], left=np.nan, right=np.nan), path)
    if best is None:
        raise ValueError('No summary noise sample within matching tolerance')
    return best[1], best[2], best[0]


def filter_metadata(frame, selections, ranges):
    mask = pd.Series(True, index=frame.index)
    for column, choices in selections.items():
        mask &= frame[column].isin(choices)
    for column, (low, high) in ranges.items():
        values = pd.to_numeric(frame[column], errors='coerce')
        mask &= np.isfinite(values) & values.between(low, high)
    return frame.loc[mask].copy()


def spectrum_table(records):
    # Exact spectral samples only: no interpolation across gaps or band windows.
    rows = []
    for case_id, label, wn, noise, floor in records:
        for w, n, f in zip(wn, noise, floor):
            if np.isfinite(n) and n > 0:
                rows.append((case_id, label, float(w), float(n), float(f)))
    frame = pd.DataFrame(rows, columns=['case_id','Case','wavenumber','noise','floor'])
    return frame.drop_duplicates(['case_id','wavenumber'])


def separated(x, y):
    if len(x) < 2:
        return x, y
    dx = np.diff(x)
    spacing = np.min(dx[dx > 0])
    gaps = np.flatnonzero(dx > 1.6*spacing)+1
    return np.insert(x.astype(float), gaps, np.nan), np.insert(y.astype(float), gaps, np.nan)


def noise_figure(table, model, source):
    fig = go.Figure()
    for _, group in table.groupby('case_id', sort=False):
        group = group.sort_values('wavenumber')
        x, y = separated(group.wavenumber.to_numpy(), group.noise.to_numpy())
        fig.add_trace(go.Scattergl(x=x, y=y, mode='lines', line=dict(color='rgba(40,100,180,0.25)', width=1),
            name=group.Case.iloc[0], showlegend=False, hovertemplate='%{x:.3f} cm⁻¹<br>%{y:.5f} RU<extra>%{fullData.name}</extra>'))
    mean = table.groupby('wavenumber', sort=True).agg(noise=('noise','mean'), count=('noise','count'))
    x, y = separated(mean.index.to_numpy(), mean.noise.to_numpy())
    fig.add_trace(go.Scatter(x=x, y=y, mode='lines', name='Mean noise', line=dict(color='#1655a0', width=3)))
    # Show each distinct floor, rather than averaging different configurations.
    seen = set()
    for _, group in table.groupby('case_id', sort=False):
        group = group.sort_values('wavenumber')
        signature = tuple(zip(group.wavenumber, group.floor))
        if signature in seen:
            continue
        seen.add(signature)
        x, y = separated(group.wavenumber.to_numpy(), group.floor.to_numpy())
        fig.add_trace(go.Scatter(x=x, y=y, mode='lines', name=f'Noise floor / reference {len(seen)}',
            line=dict(color='#c44e00', width=2, dash='dash')))
    fig.update_layout(template='plotly_white', title=f'{model} · {source} · {table.case_id.nunique()} cases',
        xaxis_title='Wavenumber (cm⁻¹)', yaxis_title='Noise / 1σ uncertainty (RU)', height=650,
        legend=dict(orientation='h'), uirevision='noise-'+model+'-'+source)
    return fig, mean.reset_index()


def render_noise(cases, index, models, source, config, tolerance, display_chart, download_table):
    st.subheader('Spectral noise')
    if cases.empty or not models or index.empty:
        st.info('Select a band and a collection with indexed retrievals.')
        return
    model = st.selectbox('Noise band', models, key='noise_band')
    mode = st.radio('Noise source', ['Instrument noise (AERI summary)', 'Effective retrieval uncertainty'], key='noise_source')
    st.caption('Instrument mode uses the nearest native summary sample to the matched retrieval time, before inflation/floor/averaging. '
               'Effective mode uses obs_vector_uncertainty saved by TROPoe. They are different quantities.')
    frame = data.case_metadata(cases)
    lon, lat = config.site_coordinates[config.SITE]
    zenith = solar_zenith(pd.DatetimeIndex(pd.to_datetime(frame.sounding_time, utc=True)), lat, lon)
    frame['Day/night'] = np.where(np.isfinite(zenith), np.where(zenith < 90, 'Day', 'Night'), 'Unknown')
    selections, ranges = {}, {}
    issues = []
    with st.expander('Filter cases (all active filters must match)', expanded=True):
        for column in ['Classification', 'Season', 'Day/night']:
            options = sorted(frame[column].dropna().unique())
            selections[column] = st.multiselect(column, options, default=options, key='noise_'+column)
        st.caption('Day means solar zenith < 90° at the sounding time and configured site. Night includes twilight.')
        if st.checkbox('Filter by observed sounding PWV', key='noise_pwv'):
            from sounding_pwv import catalog_pwv, pwv_cache_path
            key = 'noise_pwv_cache:'+repr((source['master'], source.get('master_hash'), source.get('sonde_root'), tuple(cases.case_id)))
            if key not in st.session_state or st.button('Refresh PWV', key='noise_refresh_pwv'):
                with st.spinner('Reading sounding PWV catalog…'):
                    st.session_state[key] = catalog_pwv(source['cases'], source['master'], source.get('sonde_root',''),
                        pwv_cache_path(source['master'], source['output']))
            pwv = st.session_state[key]
            frame = frame.drop(columns=['pwv_mm'], errors='ignore').merge(pwv[['case_id','pwv_mm']], on='case_id', how='left')
            a,b = st.columns(2)
            ranges['pwv_mm'] = (a.number_input('Minimum PWV (mm)', 0., value=0., key='noise_pwv_lo'),
                               b.number_input('Maximum PWV (mm)', 0., value=100., key='noise_pwv_hi'))
        if st.checkbox('Filter by AOD', key='noise_aod'):
            from dashboard_aod import aod_files, available_fields, read_aod, match_aod
            window = st.number_input('AOD half-window (minutes)', 0., 720., 30., key='noise_aod_window')
            paths = aod_files(config.AOD_DIR, config.AOD_DATASTREAM, cases, window)
            signatures, fields = [], set()
            for path in paths:
                try:
                    sig = data.signature(path)
                    fields.update(available_fields(sig))
                    signatures.append(sig)
                except Exception as exc:
                    issues.append(dict(file=str(path), reason=str(exc)))
            if not fields:
                st.warning('No AOD fields available. Download AOD data on the Aerosol / AOD page or disable this filter.')
                return
            fields = sorted(fields)
            field = st.selectbox('AOD wavelength', fields, index=fields.index('aod_500') if 'aod_500' in fields else 0, key='noise_aod_field')
            frames = []
            for sig in signatures:
                try:
                    frames.append(read_aod(sig, field, True))
                except Exception as exc:
                    issues.append(dict(file=sig[0], reason=str(exc)))
            samples = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=['time','aod','file'])
            aod = match_aod(cases, samples, window)
            frame = frame.merge(aod[['case_id','aod']], on='case_id', how='left')
            a,b = st.columns(2)
            ranges['aod'] = (a.number_input('Minimum AOD', 0., value=0., key='noise_aod_lo'),
                             b.number_input('Maximum AOD', 0., value=2., key='noise_aod_hi'))
            st.caption('AOD uses the mean within the sounding-time window and zero QC flags where provided.')
        if ranges:
            st.caption('Cases with missing PWV/AOD are excluded only when that filter is active.')
        if any(lo > hi for lo,hi in ranges.values()):
            st.warning('Minimum must not exceed maximum.')
            return
    selected = filter_metadata(frame, selections, ranges)
    if selected.empty:
        st.info('No cases match all selected filters.')
        return
    matches = data.match_cases(selected, index, [model], tolerance)
    matches = matches.loc[matches.file.ne('')]
    summaries = []
    if mode.startswith('Instrument'):
        root = st.text_input('AERI summary directory', str(Path(config.SUM_DIR)/config.MASTER_DATA_FOLDER), key='noise_sum_root')
        delta = st.number_input('Summary matching tolerance (seconds)', 0., 3600., 300., key='noise_sum_tolerance')
        days = set()
        for t in pd.to_datetime(matches.matched_time, utc=True):
            days.update(d.strftime('%Y%m%d') for d in pd.date_range((t-pd.Timedelta(seconds=delta)).normalize(), (t+pd.Timedelta(seconds=delta)).normalize()))
        channel = 1 if model == 'Ch1' else 2
        for path in sorted(Path(root).rglob('*')):
            if path.suffix.lower() in ('.nc','.cdf') and any(day in path.name for day in days):
                try:
                    summaries.append((str(path), read_summary(data.signature(path), channel)))
                except Exception as exc:
                    issues.append(dict(file=str(path), reason=str(exc)))
    records, provenance = [], []
    labels = selected.set_index('case_id').Case
    progress = st.progress(0., text='Reading noise spectra…')
    for i,row in enumerate(matches.itertuples(), 1):
        try:
            wn, noise, floor, floor_source, enabled = read_retrieval(data.signature(row.file), row.profile_index)
            noise_file, offset = row.file, 0.
            if mode.startswith('Instrument'):
                noise, noise_file, offset = nearest_noise(summaries, row.matched_time, wn, delta)
            if not np.any(np.isfinite(noise) & (noise > 0)):
                raise ValueError('No finite positive noise samples')
            records.append((row.case_id, labels[row.case_id], wn, noise, floor))
            provenance.append(dict(case_id=row.case_id, retrieval_file=row.file, profile_index=row.profile_index,
                noise_file=noise_file, summary_offset_seconds=offset, floor_source=floor_source, floor_enabled=enabled))
        except Exception as exc:
            issues.append(dict(file=row.file, reason=str(exc), case_id=row.case_id))
        progress.progress(i/len(matches))
    progress.empty()
    st.caption(f'{len(selected)} filtered cases; {len(matches)} matched retrievals; {len(records)} plotted spectra. '
               'Mean weights each case equally at each available spectral sample; no interpolation across band gaps.')
    if records:
        table = spectrum_table(records)
        fig, mean = noise_figure(table, model, mode)
        sources = {p['floor_source'] for p in provenance}
        if len(sources) == 1:
            for trace in fig.data:
                if trace.name.startswith('Noise floor / reference'):
                    trace.name = trace.name.replace('Noise floor / reference', next(iter(sources))+' floor')
        display_chart(fig, "noise_spectra")
        st.caption('Orange curves show recorded minimum-noise spectra, or a labeled upstream reference if metadata is absent. '
                   'A recorded floor may have been disabled: check the provenance table. The reference does not prove a floor was applied.')
        download_table('Download noise spectra', table, 'noise_spectra.csv', 'noise_spectra_csv')
        download_table('Download mean and sample counts', mean, 'mean_noise.csv', 'noise_mean_csv')
        with st.expander('Cases, floor settings, and input files'):
            st.dataframe(selected.merge(pd.DataFrame(provenance), on='case_id', how='inner'), hide_index=True)
    if issues:
        with st.expander('Unavailable noise spectra / input errors'):
            st.dataframe(pd.DataFrame(issues), hide_index=True)
