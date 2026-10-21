"""Scrollable completion grid for the active clear-sky classification."""
import numpy as np
import pandas as pd
import streamlit as st

from retrieval_todo import completion_matrix
from catalog_retrievals import time_values, time_bounds


def qc_matrix(cases, index, models, tolerance, errors=None):
    """One QC per case/band: usable first, then nearest time/file/record."""
    from case_collections import selected_cases
    clear = selected_cases(cases)
    result = pd.DataFrame(np.nan, index=pd.Index(clear.case_id, name='case_id'), columns=models)
    records = index.copy()
    if errors is not None and {'time', 'profile_index', 'channel', 'band'}.issubset(errors):
        extra = errors.loc[errors.time.notna() & errors.profile_index.notna()].copy()
        extra['model'] = ['Ch1' if int(c) == 1 else 'Ch2_B'+str(int(b))
                          for c, b in zip(extra.channel, extra.band)]
        records = pd.concat([records, extra], ignore_index=True)
    if records.empty or 'qc_flag' not in records:
        return result
    records['time'] = pd.to_datetime(records.time, utc=True, errors='coerce')
    records = records.loc[records.time.notna()].drop_duplicates(['file', 'profile_index'])
    records['qc_flag'] = pd.to_numeric(records.qc_flag, errors='coerce')
    targets = time_values(clear.retrieval_time)
    for model in models:
        subset = records.loc[records.model.eq(model)].sort_values('time').copy()
        if subset.empty:
            continue
        times = time_values(subset.time)
        start, stop = time_bounds(targets, times, tolerance)
        for case, target, lo, hi in zip(clear.case_id, targets, start, stop):
            if hi <= lo:
                continue
            matches = subset.iloc[lo:hi].copy()
            matches['unusable'] = ~matches.status.eq('usable')
            matches['distance'] = np.abs(times[lo:hi]-target)
            chosen = matches.sort_values(['unusable', 'distance', 'file', 'profile_index']).iloc[0]
            result.loc[case, model] = chosen.qc_flag
    return result


def qc_grid(matrix, flags):
    grid = pd.DataFrame('Missing / incomplete', index=matrix.index, columns=matrix.columns)
    grid[matrix] = 'Complete · QC unknown/other'
    grid[matrix & flags.eq(0)] = 'Complete · QC 0'
    grid[matrix & flags.eq(3)] = 'Complete · QC 3'
    grid[flags.eq(2)] = 'Not converged · QC 2'
    return grid


def qc_style(value):
    color, text = {
        'Complete · QC 0': ('#20854e', 'white'),
        'Complete · QC 3': ('#facc15', '#422006'),
        'Not converged · QC 2': ('#dc2626', 'white'),
        'Complete · QC unknown/other': ('#bfdbfe', '#1e3a8a'),
    }.get(value, ('#e5e7eb', '#4b5563'))
    return f'background-color: {color}; color: {text}'


def completion_summary(matrix, flags=None):
    per_band = pd.DataFrame({'Band': matrix.columns, 'Completed retrievals': matrix.sum(axis=0).astype(int).to_numpy()})
    if flags is not None:
        per_band['QC 2 · not converged'] = flags.eq(2).sum().astype(int).to_numpy()
        per_band['QC 3 · spectral RMS too large'] = flags.eq(3).sum().astype(int).to_numpy()
    per_band['Clear-sky cases'] = len(matrix)
    per_band['Completion (%)'] = (per_band['Completed retrievals'] / len(matrix) * 100).round(1) if len(matrix) else 0.
    if matrix.shape[1] == 0:
        return per_band, 0, 0
    return per_band, int(matrix.all(axis=1).sum()), int((~matrix.any(axis=1)).sum())


def render_catalog(cases, index, models, labels, tolerance, index_errors, all_models=None, selection_key=None):
    st.subheader('Clear-sky retrieval completion')
    st.caption(f'Each row is a selected sounding; each column is a selected band. '
               f'Records are matched within ±{tolerance:g} seconds of the target retrieval time. '
               'Green: complete, QC 0. Yellow: complete, QC 3 (spectral RMS too large). '
               'Red: QC 2 (not converged). Gray: missing/incomplete. Blue: complete with unknown/other QC. Scroll to see all cases.')
    st.caption('The group catalog/summary.json reports all saved bands for the active group. '
               'Band toggles below change the displayed all-selected/none-selected counts; they do not change the retrieval execution plan.')
    if selection_key:
        st.write('Bands included in completion statistics and dashboard comparisons')
        columns = st.columns(6)
        def toggle_band(model, key):
            selected = set(st.session_state[selection_key])
            if st.session_state[key]:
                selected.add(model)
            else:
                selected.discard(model)
            st.session_state[selection_key] = [m for m in all_models if m in selected]
        for n, model in enumerate(all_models):
            key = 'catalog_band_'+selection_key+model
            st.session_state[key] = model in models
            columns[n % len(columns)].checkbox(model, key=key, on_change=toggle_band, args=(model, key))
    matrix = completion_matrix(cases, index, models, tolerance)
    flags = qc_matrix(cases, index, models, tolerance, index_errors)
    summary, all_complete, none_complete = completion_summary(matrix, flags)
    st.caption('QC counts refer to one matched record per case and band. Duplicate outputs prefer a usable record, then the nearest time. '
               'Completion remains a structural check; a red cell can contain an incomplete output and still count toward QC 2.')
    if 'qc_flag' not in index:
        st.warning('This saved inventory does not contain QC flags. Click Refresh retrieval catalog and to-do once to collect them; subsequent loads reuse the saved flags.')
    a, b, c = st.columns(3)
    a.metric('Clear-sky cases', f'{len(matrix):,}')
    b.metric('Complete in all selected bands', f'{all_complete:,}')
    c.metric('No retrieval in selected bands', f'{none_complete:,}')
    st.subheader('Completed retrievals by band')
    st.dataframe(summary, hide_index=True, width='stretch')
    if not models:
        st.info('Select at least one band in the sidebar to see retrieval completion.')
        return
    if matrix.empty:
        st.info('There are no selected cases in this group.')
        return
    grid = qc_grid(matrix, flags)
    grid.insert(0, 'Case (UTC)', [labels.get(case, str(case)) for case in matrix.index])
    # Streamlit virtualizes the styled table; raise Pandas' rendering limit so
    # larger catalogs retain backgrounds for every row, not just the first chunk.
    styled = grid.style.map(qc_style, subset=models)
    with pd.option_context('styler.render.max_elements', max(262144, grid.size + 1)):
        st.dataframe(styled, height=650, width='stretch', hide_index=True)
    with st.expander('Export completion and scan details'):
        export = matrix.reset_index()
        export.insert(1, 'Case (UTC)', grid['Case (UTC)'].to_numpy())
        st.download_button('Download completion grid', export.to_csv(index=False), 'retrieval_completion.csv', 'text/csv')
        qc_export = flags.reset_index()
        st.download_button('Download QC flag grid', qc_export.to_csv(index=False), 'retrieval_qc_flags.csv', 'text/csv')
        st.download_button('Download band summary', summary.to_csv(index=False), 'retrieval_completion_summary.csv', 'text/csv')
        if not index_errors.empty:
            st.write('Retrieval indexing errors')
            st.dataframe(index_errors, width='stretch')
