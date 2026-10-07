# Interactive retrieval explorer

`TROPoe_APP.py` is a Streamlit app for comparing TROPoe outputs with
radiosondes. It runs on the machine that can read your retrievals. Open the
interface in a browser; no retrieval files need to be uploaded to a hosting
service. The app saves cloud classification snapshots and audited manual reviews. It does not launch retrievals or change retrieval files.

## Install and launch

Use Python 3.9 or newer and a dedicated environment, including inside a TROPoe
Docker container. Do not install the dashboard into the driver's existing
Conda/base environment or with `pip --user`: older compiled scientific packages
can conflict with the dashboard's NumPy/pandas dependencies. A default `venv`
isolates both system and user-site packages (do not add `--system-site-packages`):

```bash
python -m venv "$HOME/.venvs/tropoe-dashboard"
. "$HOME/.venvs/tropoe-dashboard/bin/activate"
python -m pip install -r requirements-dashboard.txt
python -m streamlit run TROPoe_APP.py --server.address 127.0.0.1 --server.port 8501
```

Run from the repository directory. On that same machine, open
<http://localhost:8501>. Stop the server with Ctrl-C.

For a remote workstation or an HPC node reachable through SSH, run the app there
and create a tunnel **from your laptop**:

```bash
ssh -N -L 8501:127.0.0.1:8501 USER@HOST_RUNNING_THE_APP
```

If your compute node requires a login/jump host:

```bash
ssh -J USER@LOGIN_HOST -N -L 8501:127.0.0.1:8501 USER@COMPUTE_NODE
```

Then open <http://localhost:8501> on your laptop. Replace the uppercase
placeholders with your cluster addresses. Use your cluster's normal interactive
allocation procedure to run the app on a compute node; the tunnel must reach the
node actually running Streamlit. Keep the app bound to `127.0.0.1` for this setup.

## Docker and dependency troubleshooting

Inside a container, use the same isolated environment and bind Streamlit to
`0.0.0.0`:

```bash
. "$HOME/.venvs/tropoe-dashboard/bin/activate"
python -m streamlit run /data/script_repo/TROPoe_APP.py \
  --server.address 0.0.0.0 --server.port 8501
```

Publish the port when creating the container with
`-p 127.0.0.1:8501:8501`, preserve your existing data mounts, and SSH-tunnel to
the **Docker host**. For example, from your laptop:

```bash
ssh -N -L 8501:127.0.0.1:8501 USER@DOCKER_HOST
```

Open <http://localhost:8501> on your laptop. The displayed server address
`0.0.0.0` describes its listening interfaces; it is not the browser destination.
Store/rebuild the virtual environment with the container; if its directory is
not mounted, recreating the container removes that environment.

### NumPy / xarray import failures

Errors such as `_ARRAY_API not found`, `np.unicode_ was removed`, or
"compiled using NumPy 1.x" indicate incompatible packages loaded together.
For example, installing NumPy 2 in the user site while retaining xarray 2023.6,
old numexpr/bottleneck, and SciPy 1.6.2 from the image causes these failures.
Streamlit can print its URL before the app imports fail.

Stop Streamlit with Ctrl-C and create/activate the isolated environment above,
then install the requirements there. On Python 3.9 the requirements now constrain
NumPy to 1.x. This is **not** sufficient to make installation into an old driver
environment safe: SciPy 1.6.2 requires NumPy below 1.23, whereas the dashboard
requires at least 1.24. Keep the environments separate.

Verify the dashboard environment before restarting:

```bash
python -m pip check
python -c "import sys, numpy, pandas, xarray, netCDF4; print(sys.executable); print(numpy.__version__, pandas.__version__, xarray.__version__)"
```

The executable should be under `$HOME/.venvs/tropoe-dashboard/bin`. A
"Defaulting to user installation" message means the intended environment is not
being used; stop and activate it before installing.

Creating the new environment does not remove packages previously installed in
`~/.local`. Those can still shadow the original driver's packages outside the
virtual environment. To inspect the image's original stack without the user
overlay, use its Python explicitly, for example:

```bash
PYTHONNOUSERSITE=1 /opt/miniconda/bin/python -c "import numpy, scipy; print(numpy.__version__, scipy.__version__)"
```

This is a diagnostic, not a full driver validation. Do not bulk-uninstall packages
or upgrade the driver's SciPy merely to get the dashboard running.

## Connect your data

The app starts with **cloud classification setup**, without synthetic data.

1. Set **Master manifest CSV** in the sidebar. Defaults come from
   `CLOUD_MASTER_MANIFEST`, falling back to `CLOUD_SCREEN_MANIFEST`. A legacy
   classified CSV is imported once into an unclassified sibling named
   `master_manifest_<hash>.csv`; the original is preserved. Future data collection
   writes unclassified masters directly. Diagnostic columns are retained.
2. Set the retrieval directory (`RETRIEVAL_DIR/GROUP_NAME` by default) and optional
   sounding search directory. The dashboard checks live retrieval files for the
   current clear-sky cases.
3. Set **Satellite PNG directory** (`SAT_IMAGERY_DIR`) and the durable classification
   directory (`CLOUD_CLASSIFICATION_DIR`). Keep the latter on a writable persistent
   Docker volume and reuse it across periods so manual decisions carry forward.
4. Click **Load / refresh master data**, choose thresholds and inspect the preview.
5. Click **Apply classification and open dashboard**. Saving must succeed before
   the dashboard opens. Retrieval scanning/loading occurs after classification.

The master requires unique `case_id`, `retrieval_time`, and `sounding_file` columns;
`sounding_time` defaults to retrieval time if absent. Original case IDs remain join
keys. Numeric diagnostics may be missing; missing evidence is handled explicitly.
All master cases are classified, whether or not a retrieval or satellite image exists.

### Classification rules and saved files

Choose core or context diagnostics, ASI and/or 985 cm⁻¹ radiance, and **either** or
**both** when both instruments are enabled. ASI uses **window-mean** near-zenith
and total cloud percentages. Radiance uses its window mean and standard deviation.
Each instrument passes when both finite metrics are **at or below** its maxima.
A finite metric above its limit fails that instrument; otherwise missing required
metrics give uncertain evidence. Coverage and uncertainty diagnostics do not gate
these rules. Historical masters contain summaries, so this does not reconstruct
the previous ASI rule where any single raw sample could establish clear sky.

- **Either:** any passing instrument establishes clear sky; all enabled instruments
  failing gives not clear sky; other combinations are uncertain.
- **Both:** every enabled instrument must pass; any failing instrument gives not
  clear sky; other combinations are uncertain.
- **Manual review:** a saved override always wins, including over missing data.

Changing thresholds updates a preview. **Apply** creates a unique directory under
`CLOUD_CLASSIFICATION_DIR/runs/` containing:

| File | Contents |
| --- | --- |
| `classification.csv` | Exactly `case_id,category`, one row for every master case. |
| `settings.json` | Thresholds/rule, master path and SHA-256, UTC creation time, category counts, manual-review revision. |
| `manual_overrides.json` | The manual decisions used by this snapshot. |

Directory names describe the classification rules. For example,
`core_ASI-z0-t10_RAD-m7-s0.3_either` means core-window classification with ASI
near-zenith maximum 0%, total maximum 10%, radiance mean maximum 7 and standard
deviation maximum 0.3, using the either rule. Disabled instruments are labeled
`ASI-off` or `RAD-off`. Repeated selections get `__2`, `__3`, etc., without
replacing earlier results. Names have no timestamps; settings.json retains the
UTC creation time and full provenance.

The master is not duplicated per selection. Prior snapshots are preserved.

Generated on-disk CSVs use mode **777** (read/write/execute for all users).
Classification, retrieval catalog, and retrieval to-do directories, including the
classification `runs` directory, use
**777** as well. Any user can rename, move, replace, or delete their catalog contents.
Other output folders (including plots and raw-data screening) and newly created
ancestor directories receive read/traverse access (755), without new directory
write permissions.
New classification JSON metadata uses **644**; manual-review database permissions
are unchanged. Permissions are explicit even with a restrictive container umask.
This applies to classification/master CSVs, retrieval catalogs, to-do/execution
CSVs, and plotting CSV exports. Browser downloads use the browser machine's rules.

To repair previously generated catalogs, run once as the file-owning user/container:

```bash
python fix_catalog_permissions.py
```

Defaults cover the configured classification, retrieval catalog, and to-do
directories. For another directory use
`python fix_catalog_permissions.py --root /path/to/catalogs`. The command reports
permission failures, does not follow directory symlinks, and preserves names and
contents. It grants 777 to CSV-containing directories and parent directories of
classification runs inside the selected tree; unrelated directories only gain
read/traverse access. Existing timestamp-named runs retain their names so stored paths continue
to work; descriptive naming applies to new saves.
`manual_reviews.sqlite3` in the shared classification directory keeps every review,
removal, timestamp, note, reviewer, and image path. Back it up along with the runs
and master. Removing an override records another event and restores automatic
classification for subsequent snapshots. Decisions are keyed by original case ID;
changing a case ID creates a different case.

Use **Review images / change classification thresholds** to create another run.
Comparison filters only change plotted cohorts; they do not change classifications.
For legacy selection (when `RETRIEVAL_TODO_MANIFEST = None`), set `CLOUD_CLASSIFICATION_MANIFEST` in
`config.py` to its `runs/.../classification.csv`. `GROUP_TROPoe` joins that snapshot
to its master and selects `CLOUD_SCREEN_CATEGORY`; cataloging accepts the same
compact path with `--manifest`. Keep `settings.json` alongside the CSV. A changed
master is rejected: reload it and apply a new classification. Legacy combined
manifests remain supported. An unclassified master alone cannot select clear cases.

After applying classification, retrieval comparisons load only **clear-sky cases**,
including persistent manual overrides. The radiance scatter and satellite review
retain all master cases so cases can still be inspected and reclassified.

The app recursively discovers `.nc`/`.cdf` outputs named `tropoeOutput_Ch1.*` or
`tropoeOutput_Ch2_B<number>.*`. It reads timestamps for discovery, and reads T/q
profiles only within the allowed matching range of clear-case retrieval times.
It checks live files instead of trusting an older profile catalog. Use one
experiment/group per retrieval directory to keep band configurations consistent.
No retrieval profiles are loaded when the clear-sky cohort is empty.

### Retrieval to-do manifest and execution

Each applied classification writes the current queue to
`config.RETRIEVAL_TODO_MANIFEST`, default:

`CLOUD_CLASSIFICATION_DIR/GROUP_NAME/retrieval_todo.csv`

The queue includes **one row per missing clear-case/channel/band pair**. It uses
all clear cases in the saved classification, independent of dashboard date or band
filters. By default it expects Ch1 and all 18 Ch2 bands; edit
`RETRIEVAL_TODO_BANDS` to change the expected Ch2 list. A case with no outputs gets
19 rows. A case missing only B6 gets one row. An empty queue still has column headers
and replaces the previous queue, including when no cases are classified clear.

Columns include case ID, sounding and retrieval UTC times, sounding path, channel,
band/model, reason, saved classification path, retrieval directory, and matching
tolerance. Completion requires a readable profile with **finite T and q at every
level and finite increasing heights**, matched to the actual NetCDF timestamp.
Partial, unreadable, or absent outputs remain pending. This checks structural
completion, not scientific convergence or retrieved-LWP quality. The completion
tolerance is `RETRIEVAL_TODO_TOLERANCE_SECONDS` (default 60 seconds); plot matching
controls do not change that queue policy.

Run `python GROUP_TROPoe.py` in the usual retrieval environment. It automatically
reads this configured queue, validates its cases against the saved classification
and its target directory against `RETRIEVAL_DIR/GROUP_NAME`, and executes only the
listed pairs. It uses the sounding date/time as input to `SINGLE_TROPoe` and verifies
that the expected target agrees with the driver's quarter-hour rounding. It checks
live completion before every job, including outputs completed since queue creation;
filenames alone are not evidence of completion. Only new/changed outputs are read
again during execution. Failed jobs are logged and subsequent pairs continue.
A success exit from the driver must also produce a usable matching output to be
reported complete.

The input queue remains a record of the planned work. A separate
`retrieval_todo_last_run.csv` records `already_complete`, `completed`, `failed`, or
`still_missing_or_incomplete` after each pair. Rerunning the same queue skips work
now complete. In the app, **Refresh retrieval inventory and to-do** rebuilds the
queue from current files without reclassifying cases; the sidebar shows counts,
the saved path, and a CSV download. A new classification or manual correction
rebuilds it automatically. The most recently applied selection owns the configured
queue path. A missing configured queue raises an error; an empty queue does nothing.
Set `RETRIEVAL_TODO_MANIFEST = None` only to explicitly restore legacy GROUP execution.

### Timestamp matching and refresh

The app matches each case's `retrieval_time` to timestamps **inside the NetCDF**,
including individual records of files with multiple times. Filename rounding is
not used for matching. The default tolerance is 60 seconds, adjustable below
450 seconds to avoid overlapping adjacent 15-minute windows.

When several records match, the nearest wins, followed by file path and record
index for deterministic ties. The case catalog exposes the number of candidates,
chosen file, record index, actual time, and offset. Duplicate matches merit
inspection; the app cannot infer which experiment you intended.

Native profiles are cached by absolute file path, modification time, size, record,
and diagnostic-source selection. Existing-file changes are noticed on rerun.
Click **Refresh retrieval inventory and to-do** to find new files and update missing
bands. An existing cached profile whose timestamp changes produces an explicit
load error rather than reading a different record silently.

## Filter and compare

- Select any available bands; Ch1 is optional.
- Choose an inclusive **UTC sounding date range**.
- Retrieval comparisons start from clear-sky cases; optionally filter further by
  ASI classification and radiance classification.
- Click **Apply filters** to apply the sidebar selections together.
- Select temperature or water vapor mixing ratio; change the vertical
  layer and requested bin size above the charts.

Cloud classifications come from the saved snapshot. Near-zenith **cloud percentage**
is not solar zenith angle. An empty category/band selection selects nothing.

**Compare the same cases across selected bands** is enabled by default.
Accuracy plots use cases with valid radiosonde comparisons for every selected
band. DFS plots independently use cases with valid information diagnostics for
every selected band. DFS–RMSE uses the intersection of those cohorts. Disable
this option to inspect all available cases per band; sample populations can then
differ. Counts and exclusions are available below every plot.

## Plot views

| View | Interactive comparisons |
| --- | --- |
| Vertical profiles | Choose an individual case; overlay sounding and selected bands on their native grids. |
| RMSE comparisons | Case distributions with individual points, time scatter, case/band heatmap, or heatmap differences from a selected baseline. |
| Vertical errors | Case-height retrieval-minus-sounding errors, or RMSE at each height across cases for a selected band. |
| Taylor diagram | Correlation, normalized standard deviation, centered RMSE contours, and a downloadable table with full RMSE and bias. Negative correlations are supported. |
| Information content | Median cumulative DFS or DFS density with interquartile ranges; distributions of DFS integrated over the selected layer. |
| DFS vs RMSE | Individual matched cases and band/source means; error bars describe case spread, not confidence intervals. |
| 985 radiance scatter | Mean versus standard deviation, annotated filter limits, core/context windows, category toggles, and dated hover labels. |
| Cloud diagnostics | Choose numeric manifest diagnostics for either axis; color by final category and symbol by ASI classification. |
| Case catalog | Inspect the filtered manifest and the actual retrieval record matched to each case/band. |

Use Plotly's legend to hide/show traces, hover for values, drag to zoom, and
double-click to reset axes. Hiding a trace is a display operation; change the
sidebar band selection to recompute a paired cohort.

Download filtered manifests, matched records, per-case metrics, DFS statistics,
Taylor statistics, exclusion details, and analysis settings from the relevant
view or the **Sample counts, exclusions, and downloads** section. The PNG camera
button exports a figure. **Export this figure → Prepare standalone HTML** creates
an interactive offline figure, including the Plotly library. Exports describe the
current selection; exports do not modify the original manifest.

### 985 radiance scatter, satellite review, and case labels

Both the setup screen and dashboard scatter show all master cases with finite
985 mean/std coordinates, independent of the comparison cohort. Threshold lines
and shading show the radiance criterion. Missing-coordinate cases are counted and
remain available in the case selector. ASI or manual decisions can establish clear
sky outside the radiance rectangle when the applicable rule permits it.

Group points by classification, instrument classification, season, month, year,
or six-hour UTC block. Click legend entries to toggle groups; double-click isolates
one. Hover shows a readable UTC date and diagnostics. Click a point to open its
satellite image in the adjacent panel, or use **Inspect case / satellite image**.
The default image directory is `SAT_IMAGERY_DIR`; searches are recursive,
so either the parent or the group directory can be supplied. PNG filenames must
begin `YYYYMMDDhhmm`, for example `202503051920_GOES-16_VIS.png`.

`satellite.py` generates these prefixes from **Ch1 retrieval filenames**, which
can differ from sounding launch times and manifest retrieval times. The viewer
tries the exact sounding minute, then the exact manifest retrieval minute. If
neither exists, it finds the nearest filename time to the retrieval minute (or
sounding minute if retrieval time is missing), within **Satellite filename time
tolerance (minutes)**, default 15. Set zero for exact matching only. Equally close
times and multiple images at the selected time are offered in the image selector.
Nearby matches show a warning and signed offset; verify the time before reviewing.
The filename represents the requested image time; the actual GOES scan time is
shown in the image title.

The panel reports the resolved search directory, both case times, the number of
indexed PNGs, and the match basis. Missing directories and access errors are
reported separately. The inventory is cached for up to 60 seconds; **Refresh
satellite files** rescans immediately. After changing the directory in the sidebar,
click **Load / refresh master data** to apply it. Paths must be visible inside the
app's container. Missing images never block classification or manual review.

When you click a scatter point (or change the case selector) and no image matches
the lookup rules, the app automatically runs `satellite.py` for that case's
**sounding UTC date, hour, and minute**, not its rounded retrieval time. Existing
exact or accepted nearby matches are reused. Generated PNGs go directly into the
selected satellite directory (default `SAT_IMAGERY_DIR`), without `GROUP_NAME`.
The image inventory refreshes and the result appears beside the plot immediately.
The initial default case does not trigger downloads until selected; it also has a
**Generate satellite image** button.

Generation runs in a separate headless Python process, with a 180-second timeout.
A spinner indicates work; **Satellite generation output** contains logs/errors.
Failed requests are not repeated on ordinary reruns or threshold changes in the
same session; use **Retry satellite generation** after resolving the error. The
process needs network access to GOES and the dependencies used by `satellite.py`
(including boto3, Cartopy, Matplotlib, netCDF4, requests, and its `utils.py` imports).
`requirements-dashboard.txt` now installs these dependencies. If your dashboard
environment was created before this change, activate it and rerun
`python -m pip install -r requirements-dashboard.txt`, then restart Streamlit.
It uses the dashboard's Python by default. If the satellite script already works
in another environment, set `TROPOE_SATELLITE_PYTHON` to that Python executable
before launching Streamlit. The existing day/night and GOES selection behavior
is retained. Images are written atomically to avoid displaying partial PNGs.

Single-time command-line use is also supported:

```bash
python satellite.py 20250305 19 13 --output-dir /data/satellite/sgp
```

Select **Manual classification**, optionally enter a review note/name, and click
**Save persistent manual override**. On setup this updates the preview; on the
dashboard it also creates a new snapshot immediately with the current thresholds.
**Remove override / use thresholds** records the removal. Other open app sessions
pick up new reviews when they next apply a classification; historical snapshots
remain unchanged. Cases are labeled, for example, **14 May 2024 · 18:59 UTC**, while
original IDs remain internal keys and are retained in downloadable tables.

## Scientific conventions and differences from PLOT_STATS

The app offers the main `PLOT_STATS.py` comparison families, but does not call its
all-bands-required aggregation routine. It loads each selected band independently
and interpolates from the original sounding grid for each comparison.

- Heights are km AGL. Retrieval `height` is assumed AGL. Sounding `alt` is converted
  to AGL relative to its first launch altitude. Only successively increasing
  sounding levels are retained, excluding descent and repeated levels.
- Temperature is °C and water vapor is mixing ratio in g/kg. Common
  K/°C, kg/kg/g/kg, and Pa/hPa units are converted. Missing retrieval units default
  to the repository's conventions. Unsupported units are reported.
- Sounding mixing ratio and dew point use the same vapor-pressure formulas as
  `utils.py`. Invalid RH (outside 0–100%) does not supply valid moisture values.
- The selected layer is divided into equal bins no wider than the requested bin
  size, with at least two bins. T and q are linearly interpolated to bin
  centers. No extrapolation or interpolation across a nonfinite endpoint is used.
- Per-case RMSE is `sqrt(mean((retrieved - observed)**2))` on those equally spaced
  centers. The entire selected layer must be finite for that case/variable/band.
  This approximates an equal-height-weighted layer statistic and may differ from
  the legacy script's native-level averages or height truncation. Changing the
  layer or bin size can change metrics.
- Taylor statistics pool the common-grid samples from included cases, with
  population standard deviations. Correlation/std ratio are undefined for zero
  observed variance; those points are omitted and the table retains NaNs. Pooled
  Taylor RMSE is not the arithmetic mean of per-case RMSE. Vertical gradients can
  dominate the pooled correlation.
- DFS uses the existing `information_content.py` implementation: prefer
  `diag(Akernal)` in `auto`, with explicitly labeled `cdfs_*` fallback only when
  the kernel is absent. A malformed present kernel is not replaced. You can
  request `kernel`, `cdfs`, or `*_no_model` diagnostics explicitly.
- DFS is conservatively remapped by native midpoint-cell overlap, not interpolated
  as an ordinary profile. Cumulative curves start at the **selected layer bottom**.
  Full layer coverage is required; missing DFS does not invalidate otherwise
  usable RMSE. Negative DFS values are retained. Different diagnostic sources
  remain separate labeled series. Dew point has no DFS view.
- An available/complete profile is not a scientific QC or convergence verdict.
  The app does not automatically apply `config.bad_dts`, retrieved-LWP, or QC-flag
  filters from legacy scripts. Select the desired manifest cohort explicitly.

No real retrieval output was available during initial development. The app is
verified with synthetic multi-record NetCDF fixtures and Streamlit interaction
tests. Unexpected upstream variable layouts/units are reported as exclusions;
review the first real-data load before interpreting statistics.

## Tests

```bash
python -m unittest discover -s tests -p test_dashboard.py -v
```

Tests cover actual-time matching despite rounded filenames, multi-record reads,
unit conversion, inclusive date ranges, missing cloud metrics, paired cohorts,
nonfinite profiles/no extrapolation, missing soundings with valid DFS, every plot
family, and the file-backed setup, Apply transition, dashboard views, and persistent reviews.
Run `python -m unittest discover -s tests -p test_classification.py -v` for rule,
audit, snapshot, satellite matching, and master-integrity checks.


## Vertical-error comparison page

The page displays temperature and water-vapor vertical RMSE curves side by side,
with one line per selected band. Sidebar band checkboxes control visibility only;
the common case cohort and ranking remain unchanged when a line is hidden. Use
the main Bands selection to change the compared cohort. This page always uses
cases with complete T **and** q profiles in every selected band for its aggregate
curves/table, regardless of the general paired-comparison checkbox.

The table pools squared errors across all common cases and equal-height bin
centers before taking the square root. It gives temperature RMSE (°C), mixing
ratio RMSE (g/kg), and a dimensionless combined score:

`combined = sqrt(((RMSE_T / std_observed_T)**2 + (RMSE_q / std_observed_q)**2) / 2)`

Observed population standard deviations are computed over the same pooled
radiosonde samples and shared by every band. This gives each variable equal
weight in standardized units; raw °C and g/kg errors are not added. The bar chart
orders bands from lowest to highest combined score. No score is assigned when
either observed standard deviation is zero or the common cohort is empty.
Changing the layer/cohort changes the normalization, so compare scores within a
single selection. Missing bands retain rows with unavailable values.

Below, a band selector controls both case-height heatmaps, and a case selector
controls the adjacent line profiles. Each variable has three panels: signed
selected-band error; each visible band's absolute error for the selected case;
and signed selected-band error minus signed Ch1 error. At one case/height,
absolute error equals pointwise RMSE. The difference heatmap uses matched cases
and a shared height grid; positive values indicate a more positive error, not
necessarily a larger error magnitude. Missing Ch1 values are blank. Ch1 is
loaded as the reference even if not selected as a comparison band. These panels
use available cases, with their Ch1 match counts shown separately from the joint
aggregate cohort. A dotted line locates the selected case on the heatmaps.

Dew point is no longer offered as a dashboard variable. CSV downloads include
the pooled summary, per-case T/q metrics, and exclusions.






