# TROPoe_run

Scripts for screening SGP soundings, running TROPoe retrievals, cataloging
outputs, and comparing profiles with radiosondes.

Run these scripts inside a TROPoe environment with Python, NumPy, pandas,
Matplotlib, xarray, and a NetCDF backend. `satellite.py` additionally needs
boto3, Cartopy, netCDF4, and requests. The TROPoe driver, prior file, and
instrument data are external to this repository.

1. Edit `config.py` for your data paths, group, and screening manifest.
2. Run `python setup.py` to create output directories.
3. Run `python get_sgp_data.py --help` for screening and download options.
4. Run `python catalog_retrievals.py --bands 2 6 7 10 18` to refresh the
   inventory before running `python GROUP_TROPoe.py`.
5. Rebuild the catalog after retrievals; run `python PLOT_STATS.py` for the
   sounding comparison plots.

See [documentation/CLOUD_SCREENING.md](documentation/CLOUD_SCREENING.md),
[documentation/RETRIEVAL_CATALOG.md](documentation/RETRIEVAL_CATALOG.md),
and [documentation/INFORMATION_CONTENT.md](documentation/INFORMATION_CONTENT.md)
and [documentation/PLOT_STATS_OUTPUT.md](documentation/PLOT_STATS_OUTPUT.md)
for detailed workflows. `GROUP_TROPoe.py` and `PLOT_STATS.py` set their band
lists near the top of each script.
