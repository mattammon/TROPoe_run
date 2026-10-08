"""Case-matched CIMEL AOD and combined T/q retrieval-error diagnostics."""
from pathlib import Path
import re

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import xarray as xr

import dashboard_data as data
from cloud_screening import dataset_times, filename_time
from dashboard_plots import finish


def aod_files(root, stream, cases, half_window):
    days = set()
    for time in pd.to_datetime(cases.sounding_time, utc=True):
        days.update(day.date() for day in pd.date_range((time-pd.Timedelta(minutes=half_window)).normalize(),
                                                      (time+pd.Timedelta(minutes=half_window)).normalize()))
    paths = sorted(Path(root).expanduser().rglob(stream+'.*'), key=lambda p: (p.parent.name != 'ALL', str(p)))
    chosen = {}
    for path in paths:
        if not path.is_file() or path.suffix.lower() not in ('.nc', '.cdf'):
            continue
        try:
            if filename_time(path).date() in days:
                chosen.setdefault(path.name, path)
        except ValueError:
            continue
    return list(chosen.values())


@st.cache_data(show_spinner=False, max_entries=4096)
def available_fields(signature):
    """Inspect actual variable names; never substitute total optical depth or QC."""
    with xr.open_dataset(signature[0]) as ds:
        return sorted(name for name, var in ds.data_vars.items()
                      if re.fullmatch(r'(?:aod|aot)_?\d+(?:nm)?', name, re.I)
                      and var.ndim == 1 and np.issubdtype(var.dtype, np.number))


@st.cache_data(show_spinner=False, max_entries=4096)
def read_aod(signature, field, use_qc):
    with xr.open_dataset(signature[0]) as ds:
        if field not in ds:
            raise ValueError('Missing AOD field '+field)
        times = pd.to_datetime(dataset_times(ds), utc=True)
        values = np.asarray(ds[field].values, dtype=float).copy()
        if values.ndim != 1 or len(values) != len(times):
            raise ValueError('AOD field must have one value per timestamp')
        good = np.isfinite(values) & (values >= 0) & times.notna()
        qc_fields = [name for name in ('qc_'+field, 'qc_time') if name in ds]
        if use_qc:
            for name in qc_fields:
                qc = np.asarray(ds[name].values)
                if qc.shape != values.shape:
                    raise ValueError('Unexpected dimensions for '+name)
                good &= np.isfinite(qc) & (qc == 0)
        values[~good] = np.nan
        return pd.DataFrame({'time': times, 'aod': values, 'file': str(signature[0]),
                             'qc_fields': ', '.join(qc_fields) or 'none provided'})


def match_aod(cases, samples, half_window):
    """One arithmetic-mean AOD per sounding; no extrapolation across missing windows."""
    if not np.isfinite(half_window) or half_window < 0:
        raise ValueError('AOD half-window must be finite and nonnegative')
    values = pd.to_numeric(samples.aod, errors='coerce')
    valid = samples.loc[np.isfinite(values) & samples.time.notna()].sort_values('time', kind='stable').drop_duplicates('time')
    times = pd.DatetimeIndex(valid.time).asi8
    rows = []
    for case in cases.itertuples():
        target = pd.Timestamp(case.sounding_time)
        low, high = target.value-int(half_window*60e9), target.value+int(half_window*60e9)
        window = valid.iloc[np.searchsorted(times, low):np.searchsorted(times, high, side='right')]
        rows.append(dict(case_id=case.case_id, sounding_time=case.sounding_time,
                         aod=float(window.aod.mean()) if len(window) else np.nan,
                         aod_samples=len(window), aod_first=window.time.min(), aod_last=window.time.max(),
                         aod_files='; '.join(sorted(set(window.file)))))
    return pd.DataFrame(rows, columns=['case_id', 'sounding_time', 'aod', 'aod_samples', 'aod_first', 'aod_last', 'aod_files'])


def combined_errors(cases, models, profiles, observations, edges, paired=False):
    analyses = {v: data.build_analysis(cases, models, profiles, observations, v, edges, False) for v in ('T', 'q')}
    joint = set(analyses['T']['curves']) & set(analyses['q']['curves'])
    if paired:
        cohort = [c for c in cases.case_id if all((c, m) in joint for m in models)]
        joint = {key for key in joint if key[0] in cohort}
    else:
        cohort = [c for c in cases.case_id if any((c, m) in joint for m in models)]
    scales = {}
    for variable, analysis in analyses.items():
        # Count each sounding once so bands with more outputs do not alter weighting.
        observed = [analysis['curves'][(c, next(m for m in models if (c, m) in joint))]['observed'] for c in cohort]
        scales[variable] = float(np.std(np.concatenate(observed))) if observed else np.nan
    rows = []
    for case, model in sorted(joint):
        rmses = {v: float(np.sqrt(np.mean(a['curves'][(case, model)]['error']**2))) for v, a in analyses.items()}
        total = float(np.sqrt(np.mean([(rmses[v]/scales[v])**2 for v in ('T', 'q')]))) if all(np.isfinite(s) and s > 0 for s in scales.values()) else np.nan
        rows.append(dict(case_id=case, model=model, temperature_rmse=rmses['T'], mixing_ratio_rmse=rmses['q'], total_rmse=total))
    frame = pd.DataFrame(rows, columns=['case_id', 'model', 'temperature_rmse', 'mixing_ratio_rmse', 'total_rmse'])
    frame = frame.astype({name: float for name in ('temperature_rmse', 'mixing_ratio_rmse', 'total_rmse')})
    return frame, scales


def correlations(pairs, models):
    rows = []
    for model in models:
        frame = pairs.loc[pairs.model.eq(model) & np.isfinite(pairs.total_rmse) & np.isfinite(pairs.aod)]
        x, y = frame.total_rmse.to_numpy(), frame.aod.to_numpy()
        r = slope = intercept = np.nan
        status = 'Fewer than two matched cases'
        if len(x) >= 2:
            if np.ptp(x) > 0:
                slope = float(np.sum((x-x.mean())*(y-y.mean()))/np.sum((x-x.mean())**2))
                intercept = float(y.mean()-slope*x.mean())
                if np.ptp(y) > 0:
                    r = float(np.corrcoef(x, y)[0, 1])
                    status = 'OK'
                else:
                    status = 'Constant AOD; correlation undefined'
            else:
                status = 'Constant RMSE; regression/correlation undefined'
        rows.append({'Band': model, 'Matched cases': len(frame), 'Pearson r': r, 'R²': r*r,
                     'Slope (AOD / RMSE)': slope, 'Intercept': intercept, 'Status': status})
    return pd.DataFrame(rows)


def scatter_plot(pairs, model, label, stats):
    frame = pairs.loc[pairs.model.eq(model) & np.isfinite(pairs.total_rmse) & np.isfinite(pairs.aod)].copy()
    frame['Case'] = frame.sounding_time.map(data.case_label)
    fig = go.Figure(go.Scatter(x=frame.total_rmse, y=frame.aod, mode='markers', name=model,
        customdata=frame[['Case', 'temperature_rmse', 'mixing_ratio_rmse', 'aod_samples']].to_numpy(),
        hovertemplate='%{customdata[0]}<br>Combined RMSE: %{x:.4f}<br>AOD: %{y:.4f}<br>T RMSE: %{customdata[1]:.3f} °C<br>q RMSE: %{customdata[2]:.3f} g/kg<br>AOD samples: %{customdata[3]}<extra></extra>'))
    row = stats.set_index('Band').loc[model]
    if np.isfinite(row['Slope (AOD / RMSE)']):
        x = np.array([frame.total_rmse.min(), frame.total_rmse.max()])
        fig.add_trace(go.Scatter(x=x, y=row['Intercept']+row['Slope (AOD / RMSE)']*x,
                                mode='lines', name=f'OLS fit · r={row["Pearson r"]:.3f}'))
    return finish(fig, f'{model} · {len(frame)} matched cases', 'Combined normalized T/q RMSE (dimensionless)', label)


def render_aod(cases, index, models, loaded, default_root, stream, read_profile, read_observation, display_chart, download_table):
    st.subheader('Aerosol optical depth and retrieval error')
    st.caption('All clear-sky cases in the active classification. Each case contributes one AOD value; cases without nearby AOD stay missing.')
    if cases.empty:
        st.info('There are no clear-sky cases in this classification.')
        return
    if not stream:
        st.info('Set AOD_DATASTREAM in config.py to enable AOD diagnostics.')
        return
    root = st.text_input('AOD data directory', default_root)
    half_window = st.number_input('AOD matching half-window (minutes)', min_value=0., max_value=720., value=30., step=5.)
    use_qc = st.checkbox('Require zero AOD/time QC flags when provided', value=True)
    if st.button('Download missing AOD files for all clear-sky cases'):
        from get_sgp_data import SGP_DATA
        days = set()
        for time in pd.to_datetime(cases.sounding_time, utc=True):
            days.update(d.strftime('%Y-%m-%d') for d in pd.date_range((time-pd.Timedelta(minutes=half_window)).normalize(),
                                                                    (time+pd.Timedelta(minutes=half_window)).normalize()))
        downloader = SGP_DATA(min(days), max(days), directories={'aod': root})
        failed = []
        progress = st.progress(0., text='Downloading AOD inputs…')
        for n, day in enumerate(sorted(days), 1):
            try:
                records = downloader.dataset_download('aod', root, day, day)
                if not records or any(r['status'] == 'unavailable' for r in records):
                    failed.append({'Day': day, 'Error': 'No files or some files unavailable'})
            except Exception as exc:
                failed.append({'Day': day, 'Error': str(exc)})
            progress.progress(n/len(days), text=f'AOD day {n}/{len(days)}: {day}')
        progress.empty()
        if failed:
            st.warning('Some AOD days remain unavailable. Check ARM credentials and the details below.')
            st.dataframe(pd.DataFrame(failed), hide_index=True)
        else:
            st.success('AOD files downloaded or already present for all requested days.')
    paths = aod_files(root, stream, cases, half_window)
    if not paths:
        st.info('No AOD files found for these cases. Download them with the button above (ARM_USERNAME and ARM_TOKEN required).')
        return
    signatures = [data.signature(path) for path in paths]
    fields, problems = set(), []
    for sig in signatures:
        try:
            fields.update(available_fields(sig))
        except Exception as exc:
            problems.append({'file': sig[0], 'reason': str(exc)})
    if not fields:
        st.warning('No one-dimensional wavelength-specific AOD fields were found. Expected names include aod_500 and aod_870.')
        st.dataframe(pd.DataFrame(problems))
        return
    fields = sorted(fields)
    field = st.selectbox('AOD field / wavelength', fields, index=fields.index('aod_500') if 'aod_500' in fields else 0)
    frames = []
    for sig in signatures:
        try:
            frames.append(read_aod(sig, field, use_qc))
        except Exception as exc:
            problems.append({'file': sig[0], 'reason': str(exc)})
    samples = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=['time', 'aod', 'file', 'qc_fields'])
    matched_aod = match_aod(cases, samples, half_window)
    valid = matched_aod.loc[np.isfinite(matched_aod.aod)]
    st.caption(f'{len(valid):,}/{len(cases):,} clear-sky cases have {field} within ±{half_window:g} minutes of the sounding. '
               'AOD is the arithmetic mean of finite, nonnegative samples in that window. Duplicate timestamps count once.')
    if len(samples):
        st.caption('QC fields present: '+'; '.join(sorted(samples.qc_fields.unique())))
    bins = st.slider('Histogram bins', min_value=5, max_value=100, value=30)
    display_chart(finish(go.Figure(go.Histogram(x=valid.aod, nbinsx=bins, name='Clear-sky cases')),
                         'Clear-sky case AOD distribution', field+' (dimensionless)', 'Number of cases'), 'aod_histogram')
    download_table('Download case AOD values', matched_aod, 'case_aod.csv', 'aod_cases_csv')
    if problems:
        with st.expander('AOD file errors'):
            st.dataframe(pd.DataFrame(problems), hide_index=True)
    if valid.empty or not models:
        st.info('The RMSE comparison needs matched AOD and at least one selected retrieval band.')
        return
    selected = cases.loc[cases.case_id.isin(valid.case_id)]
    a, b, c = st.columns(3)
    bottom = a.number_input('Layer bottom (km AGL)', min_value=0., max_value=19.9, value=.1, step=.1)
    top = b.number_input('Layer top (km AGL)', min_value=.1, max_value=20., value=3., step=.1)
    spacing = c.selectbox('Vertical bin size (m)', [25, 50, 100, 200, 250, 500], index=2)
    if bottom >= top:
        st.warning('Layer top must exceed layer bottom.')
        return
    tolerance = st.number_input('Maximum retrieval time offset (seconds)', min_value=0., max_value=449., value=60.)
    paired = st.checkbox('Use the same AOD/RMSE cases for every selected band', value=False)
    edges = np.linspace(bottom, top, max(2, int(np.ceil((top-bottom)*1000/spacing)))+1)
    matches = data.match_cases(selected, index, models, tolerance)
    profiles, observations, load_errors = {}, {}, []
    matched = matches.loc[matches.file.ne('')]
    progress = st.progress(0., text='Loading AOD-matched retrievals…')
    for n, row in enumerate(matched.itertuples(), 1):
        try:
            profiles[(row.case_id, row.model)] = read_profile(data.signature(row.file), row.profile_index, row.matched_time, 'auto', False)
        except Exception as exc:
            load_errors.append({'case_id': row.case_id, 'model': row.model, 'reason': str(exc)})
        if n % 25 == 0 or n == len(matched):
            progress.progress(n/max(1, len(matched)), text=f'Retrieval {n}/{len(matched)}')
    progress.empty()
    for row in selected.loc[selected.case_id.isin(matched.case_id)].itertuples():
        try:
            path = data.sounding_path(row.sounding_file, Path(loaded['manifest']).parent, loaded['sonde_root'])
            observations[row.case_id] = read_observation(data.signature(path))
        except Exception as exc:
            load_errors.append({'case_id': row.case_id, 'model': 'Radiosonde', 'reason': str(exc)})
    metrics, scales = combined_errors(selected, models, profiles, observations, edges, paired)
    pairs = metrics.merge(matched_aod, on='case_id', how='left')
    table = correlations(pairs, models)
    st.caption('Combined normalized RMSE = sqrt(((RMSE_T / σT)² + (RMSE_q / σq)²) / 2), pooling all height-bin centers in the selected layer. '
               'σT and σq are observed population standard deviations over the comparison cohort, with each sounding counted once and the same scales for all bands. '
               f'σT = {scales["T"]:.4g} °C; σq = {scales["q"]:.4g} g/kg. Missing layer coverage is excluded; there is no extrapolation.')
    @st.fragment
    def show_scatter():
        # Changing only this band redraws the figure without reloading the cohort.
        band = st.selectbox('Band for AOD–RMSE scatter', models)
        display_chart(scatter_plot(pairs, band, field+' (dimensionless)', table), 'aod_rmse')
    show_scatter()
    st.caption('The line is ordinary least squares: AOD = intercept + slope × combined RMSE. Pearson r uses the plotted finite case pairs. '
               'N=2 can give |r|=1; constant values or fewer than two cases have undefined correlation.')
    st.dataframe(table, hide_index=True)
    download_table('Download AOD–RMSE correlations', table, 'aod_correlations.csv', 'aod_correlations_csv')
    download_table('Download AOD–RMSE case pairs', pairs, 'aod_rmse_pairs.csv', 'aod_rmse_pairs_csv')
    settings = pd.DataFrame([dict(aod_field=field, half_window_minutes=half_window, require_zero_qc=use_qc,
                                 layer_bottom_km=bottom, layer_top_km=top, bin_size_m=spacing, paired=paired,
                                 bands=','.join(models), temperature_scale=scales['T'], mixing_ratio_scale=scales['q'],
                                 retrieval_tolerance_seconds=tolerance)])
    download_table('Download AOD comparison settings', settings, 'aod_settings.csv', 'aod_settings_csv')
    if load_errors:
        with st.expander('Retrieval and sounding load errors'):
            st.dataframe(pd.DataFrame(load_errors), hide_index=True)
