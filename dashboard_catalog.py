"""Scrollable completion grid for the active clear-sky classification."""
import pandas as pd
import streamlit as st

from retrieval_todo import completion_matrix


def completion_summary(matrix):
    per_band = pd.DataFrame({'Band': matrix.columns, 'Completed retrievals': matrix.sum(axis=0).astype(int).to_numpy()})
    per_band['Clear-sky cases'] = len(matrix)
    per_band['Completion (%)'] = (per_band['Completed retrievals'] / len(matrix) * 100).round(1) if len(matrix) else 0.
    if matrix.shape[1] == 0:
        return per_band, 0, 0
    return per_band, int(matrix.all(axis=1).sum()), int((~matrix.any(axis=1)).sum())


def render_catalog(cases, index, models, labels, tolerance, index_errors, all_models=None, selection_key=None):
    st.subheader('Clear-sky retrieval completion')
    st.caption(f'Each row is a clear-sky sounding; each column is a selected band. '
               f'A green cell means a usable retrieval record occurs within ±{tolerance:g} seconds of the target retrieval time. '
               'Gray means missing or incomplete. Scroll the grid to see all cases.')
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
    summary, all_complete, none_complete = completion_summary(matrix)
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
        st.info('There are no clear-sky cases in this classification.')
        return
    grid = matrix.copy()
    grid.insert(0, 'Case (UTC)', [labels.get(case, str(case)) for case in matrix.index])
    # Streamlit virtualizes the styled table; raise Pandas' rendering limit so
    # larger catalogs retain backgrounds for every row, not just the first chunk.
    styled = grid.style.map(lambda value: 'background-color: #20854e; color: white' if value
                            else 'background-color: #e5e7eb; color: #4b5563', subset=models)
    styled = styled.format(lambda value: 'Complete' if value else 'Missing', subset=models)
    with pd.option_context('styler.render.max_elements', max(262144, grid.size + 1)):
        st.dataframe(styled, height=650, width='stretch', hide_index=True)
    with st.expander('Export completion and scan details'):
        export = matrix.reset_index()
        export.insert(1, 'Case (UTC)', grid['Case (UTC)'].to_numpy())
        st.download_button('Download completion grid', export.to_csv(index=False), 'retrieval_completion.csv', 'text/csv')
        st.download_button('Download band summary', summary.to_csv(index=False), 'retrieval_completion_summary.csv', 'text/csv')
        if not index_errors.empty:
            st.write('Retrieval indexing errors')
            st.dataframe(index_errors, width='stretch')
