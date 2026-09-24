# SGP sounding cloud screening

`get_sgp_data.py` now inventories soundings and assigns **clear_sky**, **not_clear_sky**, or **uncertain** without deleting any source files. A cloud label describes the observed conditions under a recorded screening policy; it is not a guarantee that cloud or aerosol scattering is negligible in every Channel-2 band.

## Run

Dependencies: numpy, pandas, xarray, and a NetCDF backend such as netCDF4. Python 3.10+ is recommended; the screening code uses `Optional[float]` annotations so older Python environments do not fail when importing `ScreenPolicy`. Use package versions compatible with your Python interpreter. Directory settings remain in `config.py`. All dates and timestamps are UTC; both date endpoints are inclusive.

```bash
# Download screening inputs and retrieval inputs for the selected clear cases.
# Set ARM_USERNAME and ARM_TOKEN in your environment first.
python get_sgp_data.py 2024-01-01 2024-12-31

# Reclassify files already on disk, with no authentication or network calls.
python get_sgp_data.py 2024-01-01 2024-12-31 --offline

# Download screening inputs only (sondes, ASI, Channel-1 radiances).
python get_sgp_data.py 2024-01-01 2024-12-31 --retrieval-data none

# Optional: obtain retrieval inputs for every case, including uncertain cases.
python get_sgp_data.py 2024-01-01 2024-12-31 --retrieval-data all

# Inspect/edit a complete policy template, then run with it.
python get_sgp_data.py --write-default-policy my_cloud_policy.json
python get_sgp_data.py 2024-01-01 2024-12-31 --policy my_cloud_policy.json
```

Credentials previously embedded in this script have been removed. The new client uses HTTPS certificate verification and temporary downloads, validates NetCDF readability before moving files into place, and does not log credentials. Existing unreadable files are reported and retained; repair those separately before rerunning. `SINGLE_TROPoe.py` retains its `SGP_DATA(...).single_data_download()` interface, but now requires the environment credentials and reports incomplete downloads instead of silently continuing.

Online runs enumerate the **ARM Live Data catalog plus local soundings**. Catalog-listed soundings that cannot be downloaded still receive an uncertain manifest row. Failure to query the sounding catalog aborts the run; an empty successful catalog is recorded. ARM Live Data availability is not a complete historical archive inventory. Offline runs cover **locally available soundings only**, including retained legacy group folders. Soundings already deleted by the old script can only be recovered by downloading them again.

## Classification

Two windows are examined: an hour centered on the sounding filename timestamp, and a 10-minute core window centered on the scheduled retrieval time. The scheduled time follows the existing runner's minute-resolution input and nearest-quarter-hour rounding. Seconds are retained for the sounding and context window. Files from adjacent days are considered across midnight. The core window is a configurable screening approximation, not a measurement of the actual TROPoe averaging interval; adjust it if the retrieval configuration changes.

| Evidence | Clear | Not clear | Uncertain |
|---|---|---|---|
| ASI | All usable samples throughout the context have near-zenith cloud cover 0% and total cloud cover ≤10%; core and context both meet coverage requirements | At least two distinct usable core samples have near-zenith cover ≥5% or total cover ≥20% | Missing or poor-quality data, inadequate coverage, nighttime/twilight, intermediate cloud amount, or clouds only outside the core |
| 985 cm⁻¹ radiance | Both windows meet calibrated mean and standard-deviation limits, and an optional 95th-percentile limit | With adequate coverage in both windows, core mean or standard deviation crosses a separately calibrated cloud limit | No calibration, intermediate values, missing data, or insufficient coverage |

The ASI cloud-fraction and uncertainty thresholds are **initial configurable policy choices**, not validated universal limits. `clear_sky` means passing this operational near-zenith screen; the default permits up to 10% total sky cloud cover. ASI uses samples with solar zenith angle ≤80°, zero configured QC flags, valid 0–100% cloud fractions, and acceptable uncertainty when uncertainty fields are supplied. Nighttime ASI cannot establish clear sky or cloud presence. Missing required QC fields invalidate those observations. Missing *optional* uncertainty fields are explicitly recorded as `not_available`.

Coverage requires at least three valid, distinct samples, ≥80% occupancy of one-minute time bins, and no gap longer than three minutes, including the window edges. These defaults assume rapid observations: change bin width and gap thresholds to match the verified product cadence. Dense bursts cannot compensate for missing sections of the hour. Identical duplicate timestamps count once; conflicting duplicate observations make the case uncertain.

The default `clear_rule="asi"` lets usable ASI establish clear sky while recording radiance statistics for calibration. `clear_rule="radiance"` permits radiance-only decisions, including at night; `clear_rule="both"` requires agreement that both sources are clear. If any instrument detects clouds and neither claims clear, the case is not clear. Clear/cloudy disagreement produces **uncertain**, regardless of the selected rule. An unreadable/missing sounding or a filename/first-observation time mismatch greater than five minutes also forces uncertain.

### Radiance calibration and field mapping

No numeric radiance cloud thresholds are supplied by default. Set `radiance_clear_mean_max` and `radiance_clear_std_max` together to enable radiance clear evidence. Optionally set `radiance_clear_p95_max`. Independently calibrated `radiance_cloud_mean_min` and/or `radiance_cloud_std_min` must exceed their corresponding clear limits; crossing a clear threshold alone does not imply cloud. Radiance limits and reported values use **mW/(m² sr cm⁻¹)** (radiance units, RU); standard deviation uses `ddof=1`.

The reader selects the nearest element to 985 cm⁻¹ within 0.5 cm⁻¹, reports the actual element, and reads only that spectral slice. It accepts `wnum`, `wnum1`, or `wavenumber` and defaults to `mean_rad`. Recognized W-based spectral radiance is converted to mW. Unsupported units, missing coordinates, and schema errors are recorded rather than guessed. Available radiance QC fields (`qc_mean_rad`, `missingDataFlag`, `qc_flag`, `qc_time`) must be zero; at least one must exist by default. An available hatch-open flag must equal one. External engineering-file hatch flags are not yet joined into this classification.

ASI field defaults follow the existing repository's `near_zenith_percent_cloud` and `percent_cloud`. The corresponding default QC names are `qc_near_zenith_percent_cloud` and `qc_percent_cloud`; these can be overridden in the policy. Uncertainty names can be configured explicitly or detected as `<field>_uncertainty`, `uncertainty_<field>`, or `unc_<field>`. Before production use, inspect a representative NetCDF header and the recorded field names: synthetic fixtures have tested these adapters, but actual SGP files were not available in this development environment. Do not disable QC simply to increase the clear-case count.

Calibrate radiance limits using independently reviewed cases (ASI during daylight, and preferably lidar/ceilometer/radar evidence). Examine the manifest mean/std distributions by season, moisture, and day/night; validate on withheld dates. A warm, humid clear atmosphere can have substantial window radiance, while uniform thin clouds can have low temporal variability. A universal mean/std threshold can therefore distort the environmental sample. Keep uncertain cases available for review and sensitivity analyses.

## Outputs and source organization

Each run creates a new, uniquely named directory under `/data/cloud_screening/sgp/`, or the parent supplied with `--output-dir`. Reruns never replace earlier classifications.

| Output | Contents |
|---|---|
| `manifest.csv` | One row per in-range sounding: UTC times, label/reason, instrument decisions, core/hour metrics and coverage, policy hash, errors, and dataset paths |
| `cases.json` | Full per-case evidence, window boundaries, actual wavenumbers, QC/uncertainty field names, source-file references, and errors |
| `policy.json` | Complete effective policy, including every default |
| `downloads.json` | Catalog queries, file availability, download outcomes, and failures |
| `metadata.json` | Completion marker, date range, inventory scope, category counts, code revision, policy hash, and inventory errors |
| `clear_sky/`, `not_clear_sky/`, `uncertain/` | Symlinks to available original sounding files |

Raw downloads, including all soundings, live in each stream's existing `ALL` directory. Legacy group files are indexed without being moved; `ALL` takes precedence for the same basename. Daily radiances, ASI, engineering, summary, and surface data are shared by many soundings and are **referenced, not copied into each category**. Dataset lists identify nearby available files; they do not certify that all retrieval inputs have valid temporal coverage. `cases.json` separately records files contributing to each screening window. Unparseable filenames are listed in metadata because a date-range assignment cannot be made safely. If a run stops before writing `metadata.json`, its output is incomplete.

## Use the cohort in retrievals and evaluation

Set these near the top of `config.py`, using the printed manifest path:

```python
CLOUD_SCREEN_MANIFEST = '/data/cloud_screening/sgp/<run>/manifest.csv'
CLOUD_SCREEN_CATEGORY = 'clear_sky'
```

`GROUP_TROPoe.py` and `compile_retrieval_data.py` read the same selected sounding list. `GROUP_NAME` still controls retrieval output directories and figure labels. A missing/bad manifest raises an error rather than falling back to a folder. To review other populations, change `CLOUD_SCREEN_CATEGORY` and use a suitable `GROUP_NAME` to keep analysis outputs distinguishable.

With a manifest configured, `APPLY_RETRIEVAL_LWP_FILTER` defaults to False: cloud classification is independent of Ch1 retrieval success or its retrieved liquid water path. You may explicitly enable that existing secondary filter for a sensitivity study. With no manifest, legacy group-folder selection and the old group-name-based LWP behavior are retained. Existing `bad_dts` exclusions and retrieval availability checks still apply during compilation; thus the evaluated cohort may be smaller than the manifest cohort. This change does not revise the existing profile matching or RMSE calculations.

The old `group_data_download()` call now returns the new manifest path. It no longer populates/deletes a legacy group folder; callers must use the returned manifest. Nondefault legacy cloud-range arguments are rejected with an instruction to use `ScreenPolicy`.

## Verification and remaining limits

Run `python -m unittest discover -s tests -v`. Tests cover three-state decisions, conflicts, sparse coverage, nighttime/QC handling, spectral selection and unit conversion, UTC rollover, missing/corrupt soundings, catalog failures, manifest selection, and preservation of inputs across reruns, alongside the information-content tests.

No live ARM download or scientific threshold validation was performed for this change. This first implementation does not ingest lidar, ceilometer, radar, microwave LWP, or aerosol products. Those are useful next independent checks, especially for thin cirrus, nighttime cases, and Channel-2 solar scattering. Keep the policy and date cohort fixed across Ch1/Ch2 band comparisons, and report both the category counts and subsequent retrieval failures.

Reference: [Silber et al. (2026), ASISKYCOVER algorithm](https://doi.org/10.5194/amt-19-5457-2026), including near-zenith estimates, uncertainty characterization, and limitations at large solar zenith angles. The numerical screening policy here is a project choice rather than a threshold prescription from that article.

### Console diagnostics and saved logs

`get_sgp_data.py` emits timestamped INFO output by default: active policy,
catalog requests and file counts, existing-file validation, downloads, local
inventories, observation reads and cadence, QC/uncertainty/solar-angle rejection
counts, each case's two coverage windows, classifications, and output location.
Downloads report bytes every 15 seconds when chunks arrive. Network requests
announce their timeout before waiting; a stalled request may remain quiet until
its timeout. ARM credentials and request URLs are not logged.

```bash
python get_sgp_data.py 2024-01-01 2024-01-31 --log-file logs/screening.log
python get_sgp_data.py 2024-01-01 2024-01-31 --offline --log-level DEBUG --log-file logs/screening-debug.log
```

Logs stream immediately to stderr and optionally append to `--log-file`.
DEBUG adds cache reuse and local reader/validation tracebacks. Use
`--log-level WARNING` for reduced output. Imported functions use standard Python
logging; callers can enable it with `logging.basicConfig(level=logging.INFO)`.

Each manifest also includes `{asi,radiance}_{core,context}_adequacy_failures`,
listing failed sample-count, coverage, maximum-gap, or duplicate checks.
Per-file rejection counts overlap: one sample may fail several checks.
Classification rules and thresholds are unchanged. Missing required QC fields
and unrecognized uncertainty fields are explicitly reported; logging does not
correct field mappings or calibrate thresholds.

### ASISKYCOVER defaults (no override file needed)

The reader automatically recognizes `near_zenith_uncertainty_total` and
`uncertainty_total` as percentages and applies `asi_max_uncertainty` (currently
10%). ASI QC flags are optional by default: absent flags are supported when the
corresponding uncertainty field exists. Existing QC flags still veto nonzero
values. If either cloud fraction has neither a recognized QC flag nor an
uncertainty field, the observations are rejected with an explicit warning.
Missing uncertainty is no longer silently treated as affirmative quality evidence.
Assigning an uncertainty field to an `_qc` setting raises a configuration error.

Run `python get_sgp_data.py START END --offline` to reclassify downloaded files
with these defaults. Do not pass an old `--policy` file unless you intend to
override them. The 10% uncertainty cutoff remains a configurable research choice,
not a calibrated guarantee of clear sky. Nighttime/solar-angle checks still apply;
radiance thresholds still require calibration.
