# Catalog and retrieval-input maintenance

On the dashboard opening page, choose a saved classification or manual case
collection and expand **Delete selected catalog**. Confirm its name and press
the delete button. This removes that catalog directory, including its saved
classification or collection membership, settings, band selection, and group
summary. Shared retrieval files and the global manual-review history remain.
If the active global retrieval to-do references the deleted catalog, it is
removed too; open another selection to regenerate it.

In the dashboard sidebar, **Refresh ARM data catalog** previews the number of
raw files eligible for deletion. Confirm the preview and press the button to
delete them. It recomputes the collection inventory at deletion time. Files
are retained for the union of cases across **all saved manual case
collections**, including days within `RETRIEVAL_INPUT_PADDING_MINUTES` of
each rounded retrieval time. A daily file is retained if *any* collection
needs that day. Without saved manual collections, every recognized raw
retrieval-input day is eligible. Invalid/unreadable collections abort the
cleanup rather than silently dropping their cases.

Only recognized AERI Ch1/Ch2, AERI summary/engineering, and surface-met NetCDF
files in their configured stream directories are candidates. This includes
legacy group folders and `ALL/` aliases. Soundings, ASI, AOD, satellite
imagery, retrieval outputs, unknown files, and the master manifest remain.
The cleanup is permanent; a future retrieval may download deleted ARM inputs
again.

`GROUP_TROPoe.py` now validates and downloads required ARM stream-days just
before executing each missing case/band, in both the queued and legacy paths.
Checks span the configured time padding and are reused across bands within a
process. ARM credentials (`ARM_USERNAME`, `ARM_TOKEN`) and network access are
required for catalog queries. Missing Ch1/Ch2, summary, engineering, or
surface inputs fail that retrieval before TROPoe starts; missing AOD is
reported but does not block retrievals because it is diagnostic only. The
queued execution report records each failed pair. Already complete retrievals
are still skipped without downloading inputs.
