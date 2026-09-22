# Vertical information content in Ch1 / Ch2 retrieval comparisons

This is the first stage of the information-aware evaluation: visualize vertical
degrees of freedom for signal (DFS), alongside the existing sounding RMSE.
The existing RMSE formulas are not reweighted by this change.

## Run it

Run `python PLOT_STATS.py` as before. Near the top of that file:

```python
plot_information = True
information_max_height = 3.0
information_bin_width = 0.1       # km; plotting bins, not retrieval resolution
information_source = 'auto'      # auto, kernel, or cdfs
information_no_model = False
information_per_case = False
```

The diagnostics use the same retrieval files, first time record, retained cases,
and plotted bands already selected by the RMSE workflow. Information is read
before the legacy RMSE profile truncation, so a different information-plot height
can be selected without losing the original diagnostic grid.

To generate only information plots:

```bash
python PLOT_INFORMATION.py --bands 1 3 13 14 15 16 17 --max-height 3
python PLOT_INFORMATION.py --bands 1 17 --max-height 6 --per-case
python PLOT_INFORMATION.py --bands 1 17 --source cdfs
```

For notebooks:

```python
from compile_retrieval_data import Aggregate_Retrievals
from PLOT_INFORMATION import plot_information_profiles

bands = [1, 3, 13, 14, 15, 16, 17]
evaluation = Aggregate_Retrievals(3, bands, include_information=True)
result = plot_information_profiles(
    evaluation, ['Ch1'] + [f'Ch2_B{b}' for b in bands],
    max_height=3, bin_width=0.1, per_case=False,
)
result['summary']   # case/model/variable layer DFS and information depths
result['manifest']  # selected file/record, diagnostic source, exclusions
```

Dependencies are the existing scientific stack: NumPy, pandas, xarray,
Matplotlib, and a NetCDF backend such as netCDF4. Synthetic tests use unittest:

```bash
MPLBACKEND=Agg python -m unittest discover -s tests -v
```

## What the diagnostics mean

The averaging kernel A describes the local sensitivity of the retrieved state
to the true state. TROPoe orders its state as all temperature levels, followed by
all water-vapor mixing-ratio levels, then cloud/gas variables. For each of T and q,
we extract the diagonal of its state block:

    d_i = A_ii
    DFS_variable = sum_i d_i = trace(A_variable,variable)

These are DFS, not Shannon information in bits, a probability, or a direct
measure of accuracy. More DFS indicates more independent observational
constraints in the linearized retrieval; it does not guarantee smaller errors.
Cross-variable coupling and vertical smoothing require the full kernel to
interpret. Negative raw diagonal entries are preserved and flagged, not clipped.

The plots contain:

1. **DFS density versus height**, in DFS/km. The native-grid diagonal alone
   depends on level spacing; thicker cells can have larger d_i even with the
   same density of information. Density helps compare where the information is.
2. **Cumulative DFS from the surface**, showing how quickly independent
   information accumulates and how much is present in the displayed layer.
3. **Paired Ch2 minus Ch1 DFS density**, calculated per case before taking
   medians. Positive values indicate more Ch2 DFS at that height.
4. **Layer DFS boxplots**, both absolute and paired differences from Ch1.

Median curves and shaded 25th--75th percentiles describe case variability, not
confidence intervals. Median cumulative curves need not equal the integral of
median density curves: those summaries are taken separately across cases.

`z50_layer_km` and `z90_layer_km` are the heights containing 50% and 90% of the
DFS within the selected 0--H layer. They are conditional on that layer, not a
maximum sensing height. They are undefined for signed or zero-total layer DFS.
Compare several H values (e.g., 3 and 6 km) when assessing sensitivity above 3 km.

## Native grids and layer boundaries

We assign each native d_i to a height cell whose interior edges are the midpoints
between adjacent retrieval levels. The bottom/top edges are the first/last
retrieval heights. Inside each cell the display convention is constant density:

    rho_i = d_i / cell_thickness_i
    DFS_target_bin = sum_i rho_i * overlap(native_cell_i, target_bin)

This conserves total DFS, handles nonuniform and different native grids, and
does not interpolate raw A_ii values as if they were point concentrations.
No extrapolation is performed beyond native vertical coverage. A bin crossing
the 3-km boundary receives only the appropriate fraction of its native-cell DFS.
Thus plotted cumulative DFS is evaluated at cell/bin edges, and may differ
slightly from the native cumulative sum plotted at level centers. The fractional
cell allocation is a visualization convention, not newly resolved information.

The legacy RMSE code currently uses the nearest-height index plus two for
truncation, and equal weights per retrieved level. It can include a level above
3 km, and its profile mean is not a geometrically weighted layer integral.
This new diagnostic uses the exact specified height interval. Those existing
RMSE conventions should be reconciled before adding information-based weights.

## Diagnostic sources and availability

`source='auto'` prefers TROPoe's `Akernal` (the spelling in its output writer),
then falls back to `cdfs_temperature` and `cdfs_waterVapor`. For cumulative
profiles we recover local increments using:

    d_0 = cdfs_0
    d_i = cdfs_i - cdfs_(i-1)

**The fallback is not guaranteed to equal the raw averaging-kernel diagonal.**
In the upstream implementation inspected, nonpositive kernel diagonals can be
replaced by an earlier positive value during the cdfs/vres calculation. Every
profile's source is therefore recorded. A malformed/nonfinite raw kernel is
reported as invalid, rather than silently replaced by the fallback.

For a given case and variable, all requested models must have usable diagnostics
over the complete plotting layer, from the same diagnostic family. A case mixing
kernel and cumulative sources across models is excluded and logged. To compare
such legacy files consistently, explicitly use `--source cdfs` for all models,
or rerun retrievals with saved kernels. Across cases, an auto-mode run can contain
both families; the figure title reports their counts. Use `--source kernel` or
`--source cdfs` when a uniform source across the whole experiment is required.

`VIP()` now explicitly writes `output_akernal = 1` for future retrievals, saving
the full kernel and associated solution fields at additional output-file cost.
It can be disabled with `VIP(output_akernal=0)`; it does not alter the retrieval
observations or spectral bands. `VIP(output_akernal=2)` also requests the
no-model kernel. Existing NetCDF files are not rewritten.

With `--no-model` (or `information_no_model=True`), the reader requires
`Akernal_no_model` or `cdfs_*_no_model`; it will never substitute the
all-observation diagnostics. This removes the contribution of model inputs,
**not surface observations or other observing systems**.

DFS describes the whole retrieval configuration: spectral windows, noise
assumptions, prior, surface constraints, any other inputs, and atmospheric state.
The current VIP includes surface observations. Ch2--Ch1 DFS differences are
configuration comparisons, not a radiance-only attribution. Hold these other
settings fixed and compare identical cases when studying spectral choices.

## Pairing, QC, and output files

The existing sounding selection, exclusions, LWP filter, retrieval filename
matching, and first-record choice are inherited. This feature does not repair
the existing approximate time matching or apply a new convergence/QC filter.
The selected retrieval time and qc_flag (when available) are recorded so they can
be checked. The existing RMSE grid-alignment assumption also remains separate
from the new conservative information-grid handling.

For each variable, diagnostic plots use the intersection of valid cases across
all requested models. Missing diagnostics do not discard otherwise usable RMSE
profiles. T and q can have different diagnostic case counts, shown on figures.
Check those counts before comparing a diagnostic summary to the full RMSE sample.

Outputs go under `FIG_SUBDIR/Information_Content/<comparison>/`, where the
comparison name encodes models, height, bin width, source, and no-model setting:

| File | Contents |
|---|---|
| `T_information_profiles.png`, `q_information_profiles.png` | Median/IQR density, cumulative DFS, and paired density differences |
| `T_layer_dfs.png`, `q_layer_dfs.png` | Absolute and paired layer DFS distributions |
| `information_summary.csv` | Paired case/model/variable layer DFS, differences, z50/z90 |
| `information_manifest.csv` | Files, times, source, QC flags, paired inclusion and exclusion reason |
| `information_native_profiles.csv` | Full native level DFS and cumulative sum for retained cases |
| `information_binned_profiles.csv` | Common bins, DFS mass/density, cumulative DFS at each upper edge |
| `information_run.json` | Run settings, retained dates by variable, current figure list |
| `Cases/` | Optional per-case density and cumulative figures |

A rerun replaces this reporter's products for that comparison, including removing
old figures if no cases remain. If diagnostics are entirely unavailable, the
manifest and empty summary are still written and warnings explain the omission.

## Before information-weighted RMSE

A candidate metric is sqrt(sum_i w_i * error_i**2 / sum_i w_i), but the choice of
w_i defines the scientific question. Giving every retrieval its own DFS weights
can reward a band simply for having little sensitivity where its errors are large.
For fair Ch2-versus-Ch1 rankings, first evaluate **common weights on a common
grid and identical cases**, for example Ch1-derived weights or a fixed pooled
weight profile. Keep ordinary/geometrically weighted RMSE and layer DFS visible
alongside any information-weighted score. Signed/negative DFS is not suitable as
an RMSE weight without an explicit handling policy.

Another possible diagnostic compares a retrieval with an averaging-kernel-smoothed
sonde: x_smooth = x_prior + A (x_sonde - x_prior). That addresses representativeness
and smoothing, but each configuration then has a different target. It needs the
actual prior, full state mapping (including cross-variable terms), compatible
units, and complete vertical coverage. It is not implemented in this first stage.

## Primary references and implementation evidence

- Adler et al. (2024), *Improving solution availability and temporal consistency
  of an optimal-estimation physical retrieval for ground-based thermodynamic
  boundary layer profiling*: https://doi.org/10.5194/amt-17-6603-2024
- Upstream TROPoe output schema (`Akernal`, `cdfs_*`, state ordering):
  https://github.com/OAR-atmospheric-observations/TROPoe/blob/dcfc710889f24cbf3d243999cc878504d9ce8413/Output_Functions.py
- Upstream cumulative DFS implementation (`compute_vres_from_akern`):
  https://github.com/OAR-atmospheric-observations/TROPoe/blob/dcfc710889f24cbf3d243999cc878504d9ce8413/Other_functions.py
