"""Vertical degrees of freedom for signal (DFS) for TROPoe profiles.

Prefer diag(Akernal); cdfs_* increments are a labelled fallback. See
INFORMATION_CONTENT.md for conventions, upstream references, and limitations.
This module does not change RMSE or assign information-based error weights.
"""

import numpy as np


FIELDS = {'T': 'temperature', 'q': 'waterVapor'}


def _at_time(da, time_index):
    return da.isel(time=time_index) if 'time' in da.dims else da


def _profile(da, time_index, height_dim):
    da = _at_time(da, time_index)
    if da.dims != (height_dim,):
        raise ValueError(f'{da.name}: expected one height dimension, got {da.dims}')
    return np.asarray(da.values, dtype=float)


def height_km(ds):
    da = ds['height']
    if da.ndim != 1:
        raise ValueError('height must be one-dimensional')
    units = str(da.attrs.get('units', 'km')).strip().lower()
    z = np.asarray(da.values, dtype=float)
    if units in ('m', 'meter', 'meters', 'metre', 'metres'):
        z = z / 1000
    elif units not in ('km', 'kilometer', 'kilometers', 'kilometre', 'kilometres'):
        raise ValueError(f'Unsupported height units: {units}')
    if len(z) < 2 or not np.all(np.isfinite(z)) or np.any(np.diff(z) <= 0):
        raise ValueError('height must have at least two finite, strictly increasing levels')
    if z[0] < 0:
        raise ValueError('Expected nonnegative height AGL')
    return z


def read_information(ds, time_index=0, source='auto', no_model=False):
    """Read full-column diagnostics before the legacy RMSE height truncation.

    source='auto' prefers Akernal, then cdfs_temperature/cdfs_waterVapor.
    A present but malformed kernel is reported, not silently replaced by cdfs.
    no_model=True explicitly requests the *_no_model diagnostics; no substitution
    with the all-observation fields is allowed. Missing/invalid diagnostics are
    returned as errors per variable so RMSE-only files remain usable.
    """
    if source not in ('auto', 'kernel', 'cdfs'):
        raise ValueError('source must be auto, kernel, or cdfs')
    result = {'variables': {}, 'errors': {}, 'time_index': time_index,
              'no_model': no_model, 'time': '', 'qc_flag': np.nan}
    for name in ('time', 'qc_flag'):
        if name in ds:
            value = _at_time(ds[name], time_index).values
            if np.size(value) == 1:
                result[name] = str(np.asarray(value).reshape(-1)[0])
    try:
        z = height_km(ds)
    except (KeyError, ValueError) as exc:
        result['errors'] = dict.fromkeys(FIELDS, str(exc))
        return result
    result['height_km'] = z
    suffix = '_no_model' if no_model else ''
    # Akernal is the spelling in TROPoe's output writer.
    kernel_name = 'Akernal' + suffix
    use_kernel = source == 'kernel' or (source == 'auto' and kernel_name in ds)
    diagonal = None
    if use_kernel:
        try:
            kernel = np.asarray(_at_time(ds[kernel_name], time_index).values, dtype=float)
            if kernel.ndim != 2 or kernel.shape[0] != kernel.shape[1] or kernel.shape[0] < 2*len(z):
                raise ValueError(f'{kernel_name}: expected square state matrix with at least 2*Nheight rows')
            # TROPoe state order: T[0:N], q[N:2N], then cloud/gas scalars.
            diagonal = np.diag(kernel)
        except (KeyError, ValueError, IndexError) as exc:
            result['errors'] = dict.fromkeys(FIELDS, str(exc))
            return result
    for i, (variable, field) in enumerate(FIELDS.items()):
        try:
            if use_kernel:
                local = diagonal[i*len(z):(i+1)*len(z)].copy()
                source_name = kernel_name
            else:
                source_name = f'cdfs_{field}{suffix}'
                cumulative = _profile(ds[source_name], time_index, ds.height.dims[0])
                local = np.diff(cumulative, prepend=0.0)
            if len(local) != len(z) or not np.all(np.isfinite(local)):
                raise ValueError(f'{source_name}: missing/nonfinite DFS values or wrong profile length')
            result['variables'][variable] = {
                'dfs_level': local, 'cumulative_dfs': np.cumsum(local),
                'source': source_name, 'has_negative_dfs': bool(np.any(local < 0)),
            }
        except (KeyError, ValueError, IndexError) as exc:
            result['errors'][variable] = str(exc)
    return result


def native_edges(height):
    """Midpoint cells bounded by first/last retrieval levels (no extrapolation)."""
    z = np.asarray(height, dtype=float)
    if z.ndim != 1 or len(z) < 2 or not np.all(np.isfinite(z)) or np.any(np.diff(z) <= 0):
        raise ValueError('Expected finite, strictly increasing height levels')
    return np.r_[z[0], (z[:-1] + z[1:])/2, z[-1]]


def remap_dfs(height, dfs_level, edges):
    """Conserve DFS when distributing native cells onto common height bins.

    Assume constant DFS density inside each native midpoint cell. No clipping
    of negative values, no point interpolation of diag(A), and no extrapolation.
    Bins outside native vertical coverage are NaN. Units: edges in km, DFS
    unitless, density in km^-1. This is a display discretization, not a new AK.
    """
    native = native_edges(height)
    values = np.asarray(dfs_level, dtype=float)
    edges = np.asarray(edges, dtype=float)
    if edges.ndim != 1 or len(edges) < 2 or not np.all(np.isfinite(edges)) or np.any(np.diff(edges) <= 0):
        raise ValueError('Bin edges must be finite and strictly increasing')
    if values.shape != (len(native)-1,) or not np.all(np.isfinite(values)):
        raise ValueError('DFS must be a finite value per native level')
    overlap = np.maximum(0, np.minimum(edges[1:, None], native[None, 1:])
                         - np.maximum(edges[:-1, None], native[None, :-1]))
    mass = overlap @ (values / np.diff(native))
    covered = (edges[:-1] >= native[0]-1e-9) & (edges[1:] <= native[-1]+1e-9)
    mass[~covered] = np.nan
    return {'dfs_bin': mass, 'density': mass / np.diff(edges),
            'cumulative': np.r_[0., np.cumsum(mass)]}


def information_depth(height, dfs_level, top_km, fraction):
    """Height containing fraction of 0--top DFS under the native-cell convention.

    Undefined (NaN) for signed, zero-total, or incomplete profiles. Calculated
    on native cells so changing display bin width cannot change this statistic.
    """
    if not 0 < fraction <= 1 or top_km <= 0:
        raise ValueError('Require fraction in (0, 1] and positive top_km')
    native = native_edges(height)
    edges = np.unique(np.r_[0., native[(native > 0) & (native < top_km)], top_km])
    mass = remap_dfs(height, dfs_level, edges)['dfs_bin']
    if not np.all(np.isfinite(mass)) or np.any(mass < 0) or mass.sum() <= 0:
        return np.nan
    cumulative = np.cumsum(mass)
    target = fraction * cumulative[-1]
    i = int(np.searchsorted(cumulative, target))
    before = cumulative[i-1] if i else 0.
    return edges[i] + (target-before)/mass[i] * (edges[i+1]-edges[i])
