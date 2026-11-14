# Vertical structure laboratory

Choose **Vertical structure lab** in the dashboard, then a case and band. Only that
matched retrieval is loaded; this page does not scan all retrieval profiles or run
a retrieval. The selected collection and band controls define the available cases.

## A useful investigation sequence

1. Compare prior, observed, retrieved, and AK-smoothed observed profiles. Switch to
   gradients to locate inversions and moisture transitions. Display limits crop the
   view only; smoothing always acts on the full native state/depth.
2. Inspect an averaging-kernel row near a displaced feature: which true heights
   influence that retrieved level? Inspect the corresponding column to see where a
   perturbation at one true level appears in the retrieved profile. Inspect both
   same-variable and cross-variable blocks.
3. Compare prior and solution covariance/correlation and their diagonal 1-sigma
   profiles. Strong prior correlations can permit coherent changes across heights;
   they are not measurements of vertical resolution or proof of the cause of an error.
4. Move a Gaussian temperature or humidity feature in height and change its width
   and amplitude. Both variable responses are shown. Compare A delta-x with the
   fixed-A prior-mean experiment (I-A) delta-Xa.
5. Inspect normalized spectral residuals and saved gamma/QC. Forward values flagged
   -777 are excluded from this diagnostic; the page does not alter saved RMS or QC.

## Conventions and limits

The uploaded 1.0-32-g09ab443 file uses 55 heights and 123 state elements. Upstream
TROPoe.py computes Akern=(G K).T and Output_Functions.py saves that matrix unchanged.
This page therefore defaults to transposing stored Akernal to obtain **output rows,
input columns**. It offers an explicit as-stored option for modified solver output
and warns on other revisions. Orientation is not inferred from DFS, diagonals, or
which orientation produces the better fit. Check the provenance links on the page.

Sonde smoothing uses Xa + A(x_s-Xa), retaining T/q cross terms. Auxiliary cloud/gas
departures are zero because they are not measured by the sonde. By default the
observed sounding must cover the entire retrieval column. Explicit prior extension
fills only outside sounding coverage, reports the number of affected levels, and
does not fill internal missing values. It is not an observed upper-air profile.

Experiments are local linear sensitivity calculations with the saved final kernel.
They do not update radiative transfer, the Jacobian, gamma, or prior covariance.
Changing priors in a real retrieval requires rerunning the solver. A displaced
AK-smoothed feature is consistent with the saved sensitivity, not proof that the
prior alone caused the displacement. Remaining differences can involve forward
model bias, nonlinearity, auxiliary states and representativeness.

Sa and Sop are displayed as saved. No unregularized posterior identity is imposed
on Sop. Normalized covariance is undefined for zero-variance states. Full-state raw
covariance mixes units. A kernel's negative entries are retained, and neither its
rows nor diagonal are probabilities. The full trace includes auxiliary states.

The saved NetCDF does not provide K, G or iteration history; this page does not
invent them. Use TROPoe debug output for iteration-level attribution. A synthetic
Gaussian is an experiment, not a new best estimate of atmospheric truth.
