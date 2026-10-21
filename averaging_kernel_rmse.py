"""TROPoe linear-state sonde comparison: Xa + A (sonde - Xa).

Schema: upstream Output_Functions.py; arb1/arb2 code 1 = T (degC),
2 = mixing ratio (g/kg). Auxiliary state departures are explicitly zero.
Always use the full-observation Akernal corresponding to the retrieved state.
"""
import numpy as np


def read_smoothing_state(sample, height):
    """Validate native TROPoe state layout; never infer a kernel from DFS."""
    a, xa = sample['Akernal'], sample['Xa']
    n = len(height)
    for field, allowed in [('temperature', ('degc', 'c', 'celsius')), ('waterVapor', ('g/kg', 'gkg-1'))]:
        unit = str(sample[field].attrs.get('units', '')).lower().replace(' ', '')
        if unit not in allowed:
            raise ValueError('AK smoothing requires native TROPoe degC and g/kg state units: '+field)
    matrix = np.asarray(a.values, float)
    prior = np.asarray(xa.values, float)
    if matrix.ndim != 2 or matrix.shape[0] != matrix.shape[1] or matrix.shape[0] < 2*n:
        raise ValueError('Akernal must be a square full state matrix')
    if prior.shape != (matrix.shape[0],) or xa.dims != (a.dims[0],):
        raise ValueError('Xa does not match the kernel input state dimension')
    for field, dim in [('arb1', a.dims[0]), ('arb2', a.dims[1])]:
        codes = sample[field]
        expected = np.r_[np.ones(n), np.full(n, 2)]
        if codes.dims != (dim,) or not np.array_equal(np.asarray(codes)[:2*n], expected):
            raise ValueError(field+': unsupported T/q state ordering')
    if not np.isfinite(matrix).all() or not np.isfinite(prior).all():
        raise ValueError('Nonfinite Akernal or Xa')
    return dict(kernel=matrix[:2*n, :2*n].copy(), prior=prior[:2*n].copy(),
                source='Akernal', auxiliary_policy='prior (zero departure)')


def smooth_sounding(profile, sounding, allow_prior_extension=False):
    """Smooth at full native depth BEFORE selecting a verification layer.

    No filling of interior missing data. Optional prior extension applies only
    outside observed height coverage. Returns T/q in degC and g/kg.
    """
    if 'smoothing' not in profile:
        raise ValueError(profile.get('errors', {}).get('smoothing', 'Missing Akernal/Xa smoothing state'))
    state = profile['smoothing']
    z = np.asarray(profile['z'], float)
    sz = np.asarray(sounding['z'], float)
    if len(sz) < 2 or not np.isfinite(sz).all() or np.any(np.diff(sz) <= 0):
        raise ValueError('Sonde heights must be finite and increasing')
    outside = (z < sz[0]) | (z > sz[-1])
    if outside.any() and not allow_prior_extension:
        raise ValueError('Sonde does not cover full retrieval depth; enable explicit prior extension or use a complete sonde')
    prior = state['prior']
    values = []
    for i, variable in enumerate(('T', 'q')):
        observed = np.interp(z, sz, sounding[variable], left=np.nan, right=np.nan)
        if allow_prior_extension:
            observed[outside] = prior[i*len(z):(i+1)*len(z)][outside]
        if not np.isfinite(observed).all():
            raise ValueError('Missing/nonfinite sonde '+variable+' within retrieval column')
        values.append(observed)
    smoothed = prior + state['kernel'] @ (np.concatenate(values)-prior)
    if not np.isfinite(smoothed).all():
        raise ValueError('Nonfinite smoothed sounding')
    return dict(z=z, T=smoothed[:len(z)], q=smoothed[len(z):],
                prior_extension_levels=int(outside.sum()), reference='ak_smoothed',
                auxiliary_policy=state['auxiliary_policy'])
