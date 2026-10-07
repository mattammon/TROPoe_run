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


def render_catalog(cases, index, models, labels, tolerance, index_errors):
    st.subheader('Clear-sky retrieval completion')
    st.caption(f'Each row is a clear-sky sounding; each column is a selected band. '
               f'A green cell means a usable retrieval record occurs within ±{tolerance:g} seconds of the target retrieval time. '
               'Gray means missing or incomplete. Scroll the grid to see all cases.')
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
    # The native dataframe scrolls/virtualizes large catalogs; Styler would
    # eagerly render a cell per case-band pair and hit its element limit.
    grid[models] = grid[models].replace({True: '🟩', False: '⬜'})
    st.dataframe(grid, height=650, width='stretch', hide_index=True)
    with st.expander('Export completion and scan details'):
        export = matrix.reset_index()
        export.insert(1, 'Case (UTC)', grid['Case (UTC)'].to_numpy())
        st.download_button('Download completion grid', export.to_csv(index=False), 'retrieval_completion.csv', 'text/csv')
        st.download_button('Download band summary', summary.to_csv(index=False), 'retrieval_completion_summary.csv', 'text/csv')
        if not index_errors.empty:
            st.write('Retrieval indexing errors')
            st.dataframe(index_errors, width='stretch')
