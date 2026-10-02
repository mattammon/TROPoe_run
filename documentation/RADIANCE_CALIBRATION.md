# Plot 985 cm⁻¹ radiance distributions

Run from the repository, using the same Python environment as the retrieval workflow:

```bash
python PLOT_RADIANCE_CALIBRATION.py 2024-01-01 2024-12-31 \
    --manifest /data/cloud_screening/sgp/<run>/manifest.csv
```

Use the actual manifest path printed by `get_sgp_data.py`. Both dates are inclusive and use UTC. The default is the **context** window: one hour centered on each sounding under the default screening policy. One point represents one sounding case; it is not one individual AERI spectrum.

If `--manifest` is omitted, the script uses `CLOUD_SCREEN_MANIFEST` from `config.py`. If that is also unset, it runs the screening workflow **offline** over locally available soundings and radiances, then plots the resulting manifest:

```bash
python PLOT_RADIANCE_CALIBRATION.py 2024-01-01 2024-12-31
```

It never downloads data. An offline inventory may be incomplete if the annual download is still running. A supplied manifest must be from a completed screening run and must cover the dates you want to analyze; the plotting script does not fill missing dates or update that manifest. To re-read newly downloaded data, omit `--manifest` and leave `CLOUD_SCREEN_MANIFEST = None`.

## Read the scatter plot

- **Horizontal axis:** mean QC-screened 985 cm⁻¹ radiance.
- **Vertical axis:** temporal sample standard deviation (`ddof=1`) of the same radiances.
- **Blue:** ASI clear evidence; **orange:** ASI not-clear evidence; **gray:** ASI uncertain.
- **Filled circles:** adequate radiance coverage for the plotted window.
- **Crosses:** statistics are available, but coverage fails the screening policy. Inspect these rather than use them to set thresholds.

Both axes use mW/(m² sr cm⁻¹), or RU. ASI labels come from `asi_state`, not the final cloud category, to avoid using a radiance-derived label to calibrate radiance thresholds. These are policy-based ASI labels, not verified cloud truth. Gray cases can include nighttime, insufficient ASI coverage, or ambiguous cloud conditions. Cases with no finite mean or standard deviation cannot be plotted; their count appears on the figure and they remain in the exported table.

Look for a concentration of ASI-clear circles at low mean and low standard deviation, and examine where ASI-cloudy circles overlap that distribution. The overlap tells us whether a rectangular mean/std screen can separate these populations. Do not assume every high-mean or low-variability case has the same cloud state. Review candidate limits across seasons and moisture regimes, with separate held-out dates, before adopting them. ASI provides no reliable nighttime validation under this policy.

## Compare candidate limits

Supply trial values in RU to draw a vertical mean limit and a horizontal standard-deviation limit. For example, using shell variables containing your candidate values:

```bash
python PLOT_RADIANCE_CALIBRATION.py 2024-01-01 2024-12-31 \
    --manifest /data/cloud_screening/sgp/<run>/manifest.csv \
    --mean-max "$MEAN_LIMIT" --std-max "$STD_LIMIT"
```

Cases in the lower-left region meet both candidate limits. The console and summary report eligible/passing counts for each ASI label, excluding insufficient radiance coverage. This is a **single-window diagnostic**, not the full screening decision: the classifier normally requires both context and core coverage and applies additional evidence/conflict rules. Candidate plotting does not change `policy.json` or any classification. No thresholds are fitted automatically.

Use `--window core` to examine the shorter retrieval-centered window separately. Read the durations in the title and saved policy; defaults are 60-minute context and 10-minute core.

## Outputs

By default, files go to `config.FIG_SUBDIR/radiance_calibration`; change this with `--output-dir /path/to/figures`:

- `985cm_<start>_<end>_<window>.png`: scatter figure.
- `985cm_<start>_<end>_<window>_cases.csv`: every in-range manifest row, including missing-data cases, plus plotting/coverage labels and optional candidate-pass values.
- `985cm_<start>_<end>_<window>_summary.json`: manifest provenance, screening policy, counts, and candidate limits/results.

A rerun for the same date range/window/output directory replaces these plot products. Use separate output directories to retain different candidate experiments. No raw data or screening manifests are changed.

Plotting an existing manifest requires numpy, pandas, and matplotlib; offline screening additionally requires xarray and a NetCDF backend. No graphical display is needed. Test with `python -m unittest discover -s tests -p 'test_radiance_calibration.py'`.
