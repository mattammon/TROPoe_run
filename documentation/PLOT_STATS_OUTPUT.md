# `PLOT_STATS.py` output guide

Run `python PLOT_STATS.py` from the script directory after setting the paths,
group, and screening manifest in `config.py`. Outputs go under `FIG_SUBDIR`,
which is built from `FIG_DIR/SITE/GROUP_NAME`. With the current config that is
`/data/FIGS/temp/sgp/clear_sky_days`; change `config.py` to use another location.

The script compares each selected sounding with a Channel 1 retrieval and all
Channel 2 bands in `Ch2_bands_toEval`. A case is omitted from the main RMSE
analysis if any required retrieval is missing, unreadable, or rejected by the
optional Channel 1 LWP filter. The console reports each successful or failed
case; `No complete retrieval/sounding cases` means none could be analyzed.
`Ch2_bands_toPlot` determines which bands appear in figures and should be a
subset of `Ch2_bands_toEval`. By default, the evaluation and plot height limits
are 2 km and the optional information, Taylor, and DFS/RMSE products are on.

## Main RMSE figures

| File under `FIG_SUBDIR` | Meaning |
| --- | --- |
| `T_RMSE_checkerboard.png`, `Td_RMSE_checkerboard.png`, `q_RMSE_checkerboard.png` | Rows are sounding cases plus a final median row. The first column shows absolute Channel 1 RMSE in gray. Each Channel 2 column shows its RMSE **minus** Channel 1 RMSE for that case; negative values (blue) favor Channel 2 and positive values (red) favor Channel 1. Numbers in the median row rank Channel 2 bands by their median difference, lowest first. The two color bars have different meanings and scales. |
| `RMSE_Boxplots_Distributions.png` | Case distributions of absolute temperature and water-vapor RMSE for Channel 1 and each plotted band. The dashed horizontal line is the Channel 1 median; outliers are hidden in the boxplots. |
| `Profile_Plots/Vertical_Profiles_<YYYYMMDDHHMM>.png` | Temperature and dew-point profiles for a case: Channel 1, plotted Channel 2 bands, and the sounding (black dashed). One file is written per successful case. |
| `T_Vertical_RMSE_checkerboard.png`, `Td_Vertical_RMSE_checkerboard.png`, `q_Vertical_RMSE_checkerboard.png` | Absolute RMSE at each height index, pooled across cases, for each retrieval. The vertical labels come from the first case's Channel 1 grid. |

Here `T` and `Td` are in °C and `q` is in g/kg. The main case RMSE is
`sqrt(mean((retrieval - sounding)^2))` over available sounding values at the
retained retrieval levels. The sounding values are first interpolated onto the
case's Channel 1 grid. These charts do **not** integrate error by geometric
layer thickness. `max_height_eval` controls truncation; the code keeps the
nearest level to that height plus up to two following levels, so its effective
top can be slightly above the nominal limit. The vertical RMSE checkerboards
and per-case profile plots assume comparable height grids across retrievals;
inspect the actual profiles if the grids differ.

## Taylor diagrams (`Taylor/`)

With `plot_taylor=True`, the script writes `Taylor_pooled.png`,
`Taylor_pooled_statistics.csv`, and `Taylor_pooled_exclusions.csv` by default.
The figure has separate T and q panels. Each point shows correlation by angle
and retrieval standard deviation divided by sounding standard deviation by
radius. The sounding reference is at correlation 1 and radius 1. Dashed curves
are normalized **centered** RMSE, which omits mean bias. The statistics CSV also
contains bias and full RMSE. Samples are pooled at case-height points on a
common grid (`taylor_grid_step`, default 0.1 km), and each variable uses only
finite samples shared by all requested models. `n_samples` counts case-height
points; `n_cases` counts cases contributing at least one point. The exclusions
CSV records cases with no shared valid samples. If `taylor_anomalies=True`,
the filenames use `Taylor_height_anomalies` and values have their respective
across-case mean profile removed at each height. See
[TAYLOR_DIAGRAMS.md](TAYLOR_DIAGRAMS.md) for interpretation.

## Degrees of freedom for signal (`Information_Content/`)

With `plot_information=True`, products are inside a subdirectory named for
the models, layer top, bin width, diagnostic source, and model-input setting.
This prevents different settings from overwriting each other. Each variable
(T and q) has `<variable>_information_profiles.png` showing the median and
interquartile range of DFS density, cumulative DFS, and paired Channel 2 minus
Channel 1 density. `<variable>_layer_dfs.png` shows absolute layer DFS and
paired differences as boxplots. A larger DFS indicates more independent
information from the configured inputs; it does not establish a smaller error.

| File in the tagged information directory | Contents |
| --- | --- |
| `information_manifest.csv` | Case/model/variable source, file, QC metadata, `paired` flag, and reasons for missing or invalid diagnostics. |
| `information_summary.csv` | Per-case layer DFS, difference from Channel 1, and heights containing 50% and 90% of that layer's DFS. |
| `information_native_profiles.csv` | Native-height DFS and cumulative DFS for retained cases; only written when rows exist. |
| `information_binned_profiles.csv` | DFS in common height bins, density per km, and cumulative DFS; only written when rows exist. |
| `information_run.json` | Models, bin edges, included cases by variable, source settings, and figure paths. |
| `Cases/<case>_<variable>_information.png` | Individual profiles when `information_per_case=True` (off by default). |

Information figures require complete layer coverage and a consistent diagnostic
family across all requested models for each case and variable. Consequently,
their case counts can be smaller than the main RMSE sample. The colored band
shows case spread (interquartile range), not a confidence interval. See
[INFORMATION_CONTENT.md](INFORMATION_CONTENT.md) for the DFS definitions,
source fallbacks, and layer remapping.

## DFS versus RMSE (`DFS_vs_RMSE/`)

With `plot_dfs_rmse_enabled=True`, `DFS_vs_RMSE.png` has T and q panels.
Each large marker represents one model: the horizontal coordinate is mean
accumulated DFS in 0–`max_height_eval` km; the vertical coordinate is pooled
layer RMSE. Channel 1 is a black star. `dfs_rmse_show_cases=True` adds faint
individual case points. The default grid step is 0.1 km.

`DFS_vs_RMSE_cases.csv` holds each retained case/model/variable's DFS, MSE,
RMSE, and diagnostic source. `DFS_vs_RMSE_summary.csv` holds the plotted
coordinates, count, and source names. `DFS_vs_RMSE_exclusions.csv` records
case/variable omissions and reasons. Each variable uses the same valid cases
for every model. Pooled RMSE is the square root of the **mean case layer MSE**;
each case is equally weighted, and within a case, squared error is weighted
by grid-cell thickness. This differs from the native-level RMSE in the main
figures. Compare the two panels separately because T and q have different
units and potentially different retained cases. See
[INFORMATION_CONTENT.md](INFORMATION_CONTENT.md#accumulated-dfs-versus-rmse)
for details.

If a plot is absent, check its enable flag near the top of `PLOT_STATS.py`,
the case messages in the console, and the corresponding exclusions or manifest
CSV. A previous run can leave files from other settings in the output tree;
use the current configuration and CSV counts when interpreting figures.
