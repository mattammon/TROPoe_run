# Taylor diagrams in PLOT_STATS

Run `PLOT_STATS.py` normally. With `plot_taylor = True`, it creates:

- `FIG_SUBDIR/Taylor/Taylor_pooled.png`: separate T and q panels.
- `Taylor_pooled_statistics.csv`: correlation, standard deviations, normalized
  standard deviation, centered RMSE, normalized centered RMSE, bias, full RMSE,
  paired sample counts, and contributing case counts.
- `Taylor_pooled_exclusions.csv`: case-variable combinations that could not be
  placed on a common grid (with the reason).

Settings near the top of `PLOT_STATS.py`:

```python
plot_taylor = True
taylor_variables = ('T', 'q')
taylor_grid_step = 0.1
taylor_anomalies = False
```

Add `Td` to `taylor_variables` to include dewpoint.
The upper boundary follows `max_height_eval`, including your current 2-km setting.

## Interpretation

The black star is the sounding reference, at correlation 1 and standard-deviation
ratio 1. Angle is arccos(correlation); radius is retrieved standard deviation
divided by sounding standard deviation. Dashed contours give centered RMSE
normalized by the sounding standard deviation. Closer to the star means smaller
centered error. Negative correlations expand the diagram to a semicircle.
A constant retrieval has undefined correlation and is drawn at the origin;
its correlation entry in the CSV is blank. Zero reference variance prevents
normalization; the panel displays an explanatory message.

Taylor distance excludes mean bias. A retrieval with a constant offset can sit
on the reference star despite substantial full RMSE. Compare the exported bias
and RMSE and existing RMSE plots as well.

## Pairing and sampling

Profiles are interpolated to a uniform height grid in km with no extrapolation.
Internal missing data are retained rather than bridged. Each variable uses the
same finite case-height points for all selected models. Pooled samples have equal
weight; cases with more common valid heights contribute more points. A 100-m
verification grid is not a statement of 100-m retrieval resolution.

The aggregator has already interpolated sounding values to the Ch1 grid. The
Taylor helper therefore associates those values with the case's Ch1 heights,
not the original sounding height vector retained in `observed_snd['hgt']`.
Other retrievals use their own heights. Original time matching and case selection
are inherited from `Aggregate_Retrievals`; this addition does not fix those rules
or alter the existing RMSE calculations.

By default, all paired values are pooled. Broad lapse rates, moisture gradients,
and environmental differences contribute to the correlation. To remove the mean
vertical profile of each dataset, set `taylor_anomalies = True`; each height must
then have at least two paired cases. Output names use `height_anomalies`.
All statistics in that mode, including bias and full RMSE, describe the anomalies;
use the default pooled output for absolute-profile bias. Neither mode alone
establishes inversion-resolving skill or observational information content.
