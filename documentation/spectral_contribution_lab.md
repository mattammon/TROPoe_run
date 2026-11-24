# Spectral contribution laboratory

Choose **Spectral contribution lab** in the dashboard's Plot selector. The page
uses the active saved case collection and globally enabled bands. It reads
debug data without running, editing, or deleting retrievals.

## Input and matching

The default archive is `RETRIEVAL_DEBUG_DIR` from `config.py`. Run
`GROUP_TROPoe.py --debug` to retain new debug attempts. Completed retrievals
remain skipped; deliberately rerun one with, for example:

```bash
python SINGLE_TROPoe.py 202211120529 --channel 2 --band 25 --debug --clobber
```

Expected archive layout:

```text
<root>/<requested YYYYMMDDHHMM>/<Ch1 or Ch2_Bn>/<unique attempt>/
    run.json
    work/debug_output.<field>.iter_<n>.cdf
    output/tropoeOutput_<band>.<date>.<time>.nc
```

Discovery only checks the known archive depth, avoiding a recursive scan of
LBLRTM working files. Press **Refresh debug inventory** after new attempts.
Analysis caches include file modification times and sizes. Older debug files
can be opened with **Use an explicit debug directory / companion output**.
Supply the output NetCDF from that same retrieval and its time-record index.
Failed attempts without a compatible companion cannot be assigned physical
height/wavenumber labels automatically. Object `vip.npy` and pickle files are
never deserialized.

The code checks T/q state layout and units and requires the debug Y, Xa and Sa
to match the companion output. Surface observations are identified by
`obs_flag`, not mistaken for 0 cm⁻¹ infrared measurements. Unknown auxiliary
flags retain their own labels. Matrices must be finite and their algebra must
close. Active -777, -999 or -9999 observation/forward sentinel candidates block
quantitative attribution; raw Y/FXn remain inspectable.

Exception: opaque/sentinel rows are allowed when their Jacobian row and Gain
column are exactly zero and their observation precision has no off-diagonal
coupling. A positive diagonal precision alone does not imply influence on the
state. Such rows retain zero update contributions; their raw values are
exported with `sentinel_excluded=True` and excluded from normalized-residual
plots, directional support, and diagnostic residual costs. Nonzero Gain/K or
precision coupling still blocks attribution. This does not modify a retrieval.

Covariance/precision symmetry is checked on diagonal-scaled differences
`abs(M[i,j] − M[j,i]) / sqrt(abs(M[i,i] * M[j,j]))`, with a numerical floor
for zero diagonals. Differences up to `1e-5` on this dimensionless scale are
accepted and averaged as `(M + M.T)/2` for symmetric analyses. This tolerates
roundoff in near-zero cross terms without allowing a large auxiliary variance
to hide substantial asymmetry in the T/q blocks. Shape, nonfinite, substantial
asymmetry, and positive-semidefiniteness failures remain separate checks.

Upstream conventions were checked against TROPoe `09ab443`:

- Kij: observation × state; Gain: state × observation.
- Saved Akern: `(Gain @ Kij).T`; displayed A: output × input.
- Constant matrices Y, Xa, Sa, SaInv and SmInv fall back to iteration 0.
- Some versions' `write_variable` do not write scalar gfac. Gamma is then
  inferred from `B − K.T @ SmInv @ K = gamma * SaInv` and checked algebraically.
- Debug Xnp1 is a **proposed** state, saved before subsequent bounds or other
  solver adjustments. It need not equal the final output Xop.
- A final-matched iteration must match both **Xn** and the saved averaging
  kernel. The latest iteration is not assumed to be the accepted solution.

The single-attempt view can examine intermediate iterations. Cohort results
use only final-matched iterations from the latest finished attempt per
case/band. Exclusions are listed; another attempt is never silently substituted.

Across-case cache keys include the diagnostic implementation version as well
as input-file signatures. After a diagnostic fix, recompute with **Compute /
refresh cohort diagnostics** rather than retaining old exclusion results.
The included-attempt banner reports how many accepted attempts contain safely
zero-influence sentinel rows. The optional gamma≈1 filter still excludes
otherwise valid attempts with larger damping (for example gamma=3).

## Spectral attribution: what produced a feature?

Select T or q and an analysis layer (default 0–2 km). The feature is the
arithmetic mean of the native levels in that layer. Optionally subtract the
equal-weight average of lower and upper flanking-layer means. The latter is
useful for isolating an inversion or dry/moist layer from a broad profile shift.
This is not a pressure- or mass-weighted mean.

For the selected iteration:

$$d=y-F(x_n)+K(x_n-x_a),\qquad x_{n+1}-x_a=Gd.$$

The signed contribution of observation i to state element j is
`C[j,i] = G[j,i] * d[i]`. For feature weights w, each observation contributes
`(w.T @ G)[i] * d[i]`. Summing all contributions reconstructs the proposed
departure from the prior. The page shows:

- Prior, current, proposed and saved-final T/q profiles; optional sounding.
- Spectral-bin × height signed contribution heatmap.
- Ranked signed and absolute feature contributions, with auxiliary sources
  such as surface T/q listed separately.
- Per-element feature contributions and residual / saved observation sigma.
- Cancellation: `1 − abs(sum(c)) / sum(abs(c))` (undefined if all terms vanish).

**Absolute share is a share of contribution magnitudes, not a fraction of
information, accuracy, or the absolute final profile.** Large contributions
can cancel. A flat contribution spectrum may reflect a small residual rather
than an uninformative channel. Raw gain and Jacobian magnitudes mix units and
must not be compared directly across T, q and auxiliary states.

## Observations versus prior

There is no single universal "percentage of the retrieved profile from the
observations." The lab presents complementary diagnostics:

1. **Current iteration's step:**
   `xnp1 − xn = G @ (Y − FXn) − (I − A) @ (xn − xa)`.
   The first term is the observation-residual step; the second is the prior
   restoring step. These are exact for the saved local update equation.
2. **A = G K**, its diagonal, and its trace (DFS). A describes the local
   response to atmospheric departures. A diagonal element is not a per-level
   observation percentage; off-diagonal and T/q cross terms matter.
3. **Prior sensitivity:**
   `sqrt(diag[(I−A) Sa (I−A).T] / diag[Sa])`. This measures sensitivity to prior
   mean perturbations with covariance Sa relative to prior standard deviation.
   It can exceed 1; it is not constrained to be a fraction.
4. **Reported posterior sigma / prior sigma.** Upstream reported Sop is
   `B_inv @ (gamma**2 * SaInv + K.T @ SmInv @ K) @ B_inv`, generally not B_inv
   when gamma differs from 1.
5. **Prior-whitened modes.** Eigenvalues lambda of
   `Sa_sqrt @ K.T @ SmInv @ K @ Sa_sqrt` give local observation response
   `lambda / (lambda + gamma)` and complementary prior retention. The lab also
   shows the atmospheric shape and recovered response of each mode. Modes mix
   variables and heights. A warning appears for numerical rank deficiency or
   disagreement with full-state DFS; do not then treat the modal sum as total
   information. A dotted gamma=1 reference distinguishes damping from the
   original prior constraint when gamma is not 1.

If the same prior is used year-round, its *relative influence can still vary*
because K, observation uncertainty, opacity, or gamma change. Compare these
quantities before attributing a seasonal pattern to a climatological prior.

## Contradictory spectral pulls

The signed amplitude sets an explicit atmospheric perturbation delta_x: positive
adds the selected feature; negative cools/dries it. Its spectral change is
v = K delta_x. Per-observation likelihood support is

$$s_i=v_i[S_m^{-1}(y-F(x_n))]_i.$$

Positive values favor the perturbation; negative values oppose it, in the
first-order decrease of **half** the quadratic cost. Prior support is
`−gamma * delta_x.T @ SaInv @ (xn − xa)`. The full precision multiplication
preserves cross-observation covariance. Opposing groups diagnose tension;
they do not uniquely identify an erroneous channel. These directional scores
are different from Gain × innovation attribution.

## Band and prior experiments

- **Prior covariance multiplier:** scales all states' Sa while holding its
  mean, gamma, K and observation covariance fixed. Four times the covariance
  means twice the standard deviation and one quarter the precision.
- **Withhold an infrared interval:** removes only selected measured IR rows,
  retains auxiliary observations, and recomputes the gain. The code first
  reconstructs the full active observation covariance, then uses the marginal
  covariance of retained observations. It does not simply slice SmInv, which
  would incorrectly condition on the withheld data when errors are correlated.
  Singular active precision prevents this experiment rather than silently
  inventing a covariance.

Compare the new proposed profiles, feature changes and DFS with the baseline
proposed update and the optional observed sounding. These are **frozen-linear
experiments**. They do not recompute radiative transfer/Jacobians, enforce
nonlinear physical bounds, or prove that a weaker prior improves accuracy.
The page cannot assess unmeasured spectral intervals. Confirm promising
channel removals or prior changes with actual nonlinear retrieval reruns and
independent cases, not only the cases used to choose them.

## Iterations, matrices and provenance

Read all saved iterations on demand to compare gamma, DFS, proposed step size
in prior-sigma units, and residual quadratic cost. The table marks iterations
matching the accepted solution. A smaller spectral residual alone does not
establish convergence or profile accuracy.

Inspect K, Gain, Sa, SaInv, SmInv, B, Sop, A, I−A, prior/posterior correlations,
and whitened observation information. Large matrices are subsampled only for
display (the stride is stated); exported matrices and calculations remain full
resolution. Download state/observation mappings and JSON analysis settings.

## Across-case comparisons

Season, solar day/night, classification, and observed-PWV filters combine by
intersection. Press **Compute / refresh observed sounding PWV** to use the
existing PWV catalog/integration code. Partial-column or missing PWV is not
silently substituted. Without the PWV filter it remains in the population and
can be displayed as a missing-PWV group.

In **Across cases**, choose bands, then explicitly compute diagnostics. No
all-case matrix loading occurs just by opening the page. File signatures and
analysis settings invalidate stale results. Each valid case/band contributes
once. Stratify by season, day/night, UTC time bin, or PWV bin; compare:

- Layer DFS, covariance-scaled prior sensitivity, uncertainty ratios,
  proposed departures in prior-sigma units, and gamma.
- Case scatter versus observed PWV and grouped distributions for T/q.
- Case-weighted spectral-bin attribution or layer DFS by regime, with
  contributing case counts on hover. Spectral gaps remain missing.

Group summaries include sample size, mean/median/spread, mean gamma, number of
distinct prior fingerprints, and native-level counts. Optional gamma≈1 and
QC=0 filters help identify damping or quality confounding. Fingerprints hash
the exact saved Xa and Sa arrays; they indicate differences, not their cause.

A useful band-selection workflow is to find intervals that add stable layer
DFS across regimes, check whether they support the observed feature rather
than cancel or track systematic residuals, and test withholding them locally.
For suspected lost information, inspect whitened modes, prior restoring steps,
and sensitivity to weaker prior covariance. A strong response after weakening
the prior can also amplify noise, spectroscopy errors, or forward-model biases.
These diagnostics guide experiments; they do not by themselves justify less
regularization or selecting the band with the largest DFS.
