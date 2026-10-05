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


## Interactive comparison app

Explore bands, UTC date ranges, cloud classifications, ASI/radiance limits, and
height layers without editing plotting scripts. Install the app in an isolated
environment, including when running inside the existing TROPoe Docker image:

```bash
python -m venv "$HOME/.venvs/tropoe-dashboard"
. "$HOME/.venvs/tropoe-dashboard/bin/activate"
python -m pip install -r requirements-dashboard.txt
python -m streamlit run TROPoe_APP.py --server.address 127.0.0.1
```

The app includes a labeled synthetic demo and loads your existing screening
manifest, retrievals, and radiosondes. Views include profiles, RMSE comparisons,
Taylor diagrams, DFS profiles, and DFS versus RMSE, with CSV/interactive HTML
exports. See [the app guide](documentation/INTERACTIVE_APP.md) for setup, HPC SSH
tunneling, matching rules, and scientific conventions.
