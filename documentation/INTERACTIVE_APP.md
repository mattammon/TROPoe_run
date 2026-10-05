# Interactive retrieval explorer

`TROPoe_APP.py` is a read-only Streamlit app for comparing TROPoe outputs with
radiosondes. It runs on the machine that can read your retrievals. Open the
interface in a browser; no retrieval files need to be uploaded to a hosting
service. The app does not launch retrievals or rewrite screening classifications.

## Install and launch

Use Python 3.9 or newer. Prefer a dedicated environment if your TROPoe driver
requires older scientific packages:

```bash
python -m venv .venv-dashboard
source .venv-dashboard/bin/activate
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

## Connect your data

The app starts in **Synthetic demo** mode. All demo profiles, cloud diagnostics,
and resulting statistics are generated; they are not measured retrievals.

1. Select **Retrieval files** in the sidebar.
2. Set the screening manifest CSV and retrieval directory. Defaults come from
   `config.py`: `CLOUD_SCREEN_MANIFEST` and `RETRIEVAL_DIR/GROUP_NAME`.
3. Optionally supply the `profiles.csv` produced by `catalog_retrievals.py`.
   This avoids reopening every output to build an index. Use the profile catalog,
   not `cases.csv` or `files.csv`.
4. Optionally set a sounding search directory if the manifest's sounding paths
   have moved. Exact paths are tried first, then paths relative to the manifest,
   then a recursive basename search. Ambiguous matches are rejected.
5. Click **Load / refresh data**. All paths refer to the machine running the app.

The manifest requires unique `case_id`, `retrieval_time`, and `sounding_file`
columns. `sounding_time` defaults to retrieval time if absent. Missing category,
ASI-state, and radiance-state columns are labeled `unknown`; numeric diagnostic
columns are optional. The manifest is the case inventory. Retrievals with no
manifest case do not appear in the comparison.

Without a catalog, the app recursively scans `.nc` and `.cdf` outputs named
`tropoeOutput_Ch1.*` or `tropoeOutput_Ch2_B<number>.*`. Use one experiment/group
per retrieval directory so different configurations with the same band names do
not get mixed. The catalog option uses only entries underneath that directory.

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
Click **Load / refresh data** to find new files. If using a catalog, rebuild that
catalog first. A stale catalog pointing to a changed record time produces an
explicit load error rather than reading a different record silently.

## Filter and compare

- Select any available bands; Ch1 is optional.
- Choose an inclusive **UTC sounding date range**.
- Filter by final cloud category, ASI classification, and radiance classification.
- Optionally cap mean total cloud cover, mean near-zenith cloud cover, mean
  985 cm⁻¹ radiance, or its standard deviation, using core/context diagnostics.
  The radiance units are those in the screening manifest/source dataset.
- Missing cloud metrics are retained by default. Clear **Include missing cloud
  metrics** to reject them when a numeric limit is active. A missing column is
  reported explicitly.
- Click **Apply filters** to apply the sidebar selections together.
- Select temperature, water vapor mixing ratio, or dew point; change the vertical
  layer and requested bin size above the charts.

Cloud-metric controls filter the existing manifest; they do not rerun the ASI
classifier. In particular, near-zenith **cloud percentage** is not solar zenith
angle. An empty category/band selection selects nothing, not everything.

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

## Scientific conventions and differences from PLOT_STATS

The app offers the main `PLOT_STATS.py` comparison families, but does not call its
all-bands-required aggregation routine. It loads each selected band independently
and interpolates from the original sounding grid for each comparison.

- Heights are km AGL. Retrieval `height` is assumed AGL. Sounding `alt` is converted
  to AGL relative to its first launch altitude. Only successively increasing
  sounding levels are retained, excluding descent and repeated levels.
- Temperature/dew point are °C and water vapor is mixing ratio in g/kg. Common
  K/°C, kg/kg/g/kg, and Pa/hPa units are converted. Missing retrieval units default
  to the repository's conventions. Unsupported units are reported.
- Sounding mixing ratio and dew point use the same vapor-pressure formulas as
  `utils.py`. Invalid RH (outside 0–100%) does not supply valid moisture values.
- The selected layer is divided into equal bins no wider than the requested bin
  size, with at least two bins. T, q, and Td are linearly interpolated to bin
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
family, and interactions with both demo and file-backed Streamlit sources.
