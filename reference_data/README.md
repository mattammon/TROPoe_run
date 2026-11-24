# Oxford EODG reference zenith optical thickness

`oxford_zenith_optical_depth.csv` contains dimensionless H2O and CO2 zenith-sky
optical thickness, with wavenumber in cm⁻¹. Retrieved 2026-11-24 from the
[Oxford EODG Atmospheric Infrared Spectrum Atlas](https://eodg.atm.ox.ac.uk/ATLAS/).
The reference model is RFM with HITRAN 2012 line data and US Standard Atmosphere
absorber profiles, as documented by the Atlas. Credit: Earth Observation Data
Group, Department of Physics, University of Oxford; Atlas web pages by Oliver
King, supervised by Anu Dudhia.

Source display datasets (all six files):

- `https://eodg.atm.ox.ac.uk/ATLAS/data_files/opt/100/0/h2o.js`
- `https://eodg.atm.ox.ac.uk/ATLAS/data_files/opt/100/1/h2o.js`
- `https://eodg.atm.ox.ac.uk/ATLAS/data_files/opt/100/2/h2o.js`
- `https://eodg.atm.ox.ac.uk/ATLAS/data_files/opt/100/0/co2.js`
- `https://eodg.atm.ox.ac.uk/ATLAS/data_files/opt/100/1/co2.js`
- `https://eodg.atm.ox.ac.uk/ATLAS/data_files/opt/100/2/co2.js`

Only the named molecular series was extracted, selecting 499–3001 cm⁻¹ to
cover both channel boundaries. Numeric pairs were preserved as published, joined
on wavenumber, sorted, and written to CSV (2,502 rows). The `100` display
compression level has approximately 1 cm⁻¹ sampling; it should not be interpreted
as original line-by-line resolution or an instrument convolution. No interpolation
or rescaling of optical thickness was performed. Nonpositive values are omitted
only when plotting on the logarithmic axis. These reference curves do not vary
with the selected case, PWV, season, or band.
