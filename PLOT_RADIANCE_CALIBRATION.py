"""Plot 985 cm-1 mean versus temporal standard deviation for sounding cases.

Use an existing cloud-screen manifest, or screen locally available data offline.
No ARM downloads or fitted/automatically accepted thresholds are performed.
"""
import argparse
from datetime import datetime
import json
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D


COLORS = {'clear_sky': '#0072B2', 'not_clear_sky': '#D55E00', 'uncertain': '#777777'}
LABELS = {'clear_sky': 'ASI clear', 'not_clear_sky': 'ASI not clear', 'uncertain': 'ASI uncertain'}


def date_bound(value):
    text = str(value)
    for fmt in ('%Y-%m-%d', '%Y%m%d'):
        try:
            return pd.Timestamp(datetime.strptime(text, fmt), tz='UTC')
        except ValueError:
            pass
    raise ValueError('Dates must be YYYY-MM-DD or YYYYMMDD')


def boolean_values(series):
    return series.astype(str).str.lower().isin(('true', '1', '1.0'))


def load_cases(manifest, start, end, window='context'):
    """Retain all in-range rows, explicitly flagging those that cannot be plotted."""
    start, end = date_bound(start), date_bound(end)
    if end < start:
        raise ValueError('End date precedes start date')
    if window not in ('context', 'core'):
        raise ValueError('window must be context or core')
    manifest = Path(manifest)
    policy_file = manifest.parent/'policy.json'
    policy = json.loads(policy_file.read_text()) if policy_file.exists() else {}
    if float(policy.get('wavenumber', 985)) != 985:
        raise ValueError('This plot requires a manifest screened at 985 cm-1')
    df = pd.read_csv(manifest)
    prefix = 'radiance_'+window+'_'
    required = {'sounding_time', 'asi_state', prefix+'radiance_mean', prefix+'radiance_std', prefix+'adequate'}
    if df.empty and 'sounding_time' in df:
        # The screening writer intentionally emits minimal columns for an empty inventory.
        for column in required-set(df):
            df[column] = pd.Series(dtype=object)
    missing = required-set(df)
    if missing:
        raise ValueError('Missing manifest columns: '+', '.join(sorted(missing)))
    times = pd.to_datetime(df.sounding_time, utc=True, errors='raise')
    if times.isna().any():
        raise ValueError('Manifest contains missing sounding timestamps')
    df = df.loc[(times >= start) & (times < end+pd.Timedelta(days=1))].copy()
    if 'case_id' in df and df.case_id.duplicated().any():
        raise ValueError('Duplicate case IDs in manifest; use one screening run')
    df['radiance_mean'] = pd.to_numeric(df[prefix+'radiance_mean'], errors='coerce')
    df['radiance_std'] = pd.to_numeric(df[prefix+'radiance_std'], errors='coerce')
    df['plot_available'] = np.isfinite(df.radiance_mean) & np.isfinite(df.radiance_std) & (df.radiance_std >= 0)
    df['coverage_adequate'] = boolean_values(df[prefix+'adequate'])
    df['asi_label'] = df.asi_state.where(df.asi_state.isin(COLORS), 'uncertain')
    df['plot_status'] = np.where(~df.plot_available, 'missing_mean_or_std',
                                np.where(df.coverage_adequate, 'adequate_coverage', 'insufficient_coverage'))
    return df, policy


def plot_calibration(manifest, start, end, output_dir, window='context', mean_max=None, std_max=None):
    """Return output paths; candidate limits are visual diagnostics, not policy edits."""
    for name, value in [('mean_max', mean_max), ('std_max', std_max)]:
        if value is not None and (not np.isfinite(value) or value < 0):
            raise ValueError(name+' must be finite and nonnegative')
    cases, policy = load_cases(manifest, start, end, window)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    tag = f'985cm_{date_bound(start):%Y%m%d}_{date_bound(end):%Y%m%d}_{window}'
    paths = {kind: out/(tag+suffix) for kind, suffix in
             [('figure', '.png'), ('cases', '_cases.csv'), ('summary', '_summary.json')]}
    fig, ax = plt.subplots(figsize=(9, 6.5))
    plotted = cases[cases.plot_available]
    for state, color in COLORS.items():
        group = plotted[plotted.asi_label == state]
        good = group[group.coverage_adequate]
        poor = group[~group.coverage_adequate]
        ax.scatter(good.radiance_mean, good.radiance_std, s=28, color=color, alpha=.65, edgecolors='none')
        ax.scatter(poor.radiance_mean, poor.radiance_std, s=30, color=color, marker='x', alpha=.45, linewidths=.9)
    if mean_max is not None:
        ax.axvline(mean_max, color='#333333', linestyle='--', linewidth=1.2)
    if std_max is not None:
        ax.axhline(std_max, color='#333333', linestyle=':', linewidth=1.2)
    if plotted.empty:
        ax.text(.5, .5, 'No cases with finite mean and standard deviation', ha='center', transform=ax.transAxes)
    handles = [Line2D([], [], marker='o', linestyle='', color=color,
                      label=f'{LABELS[state]} (n={int((plotted.asi_label == state).sum())})')
               for state, color in COLORS.items()]
    handles += [Line2D([], [], marker='o', linestyle='', color='black', label='Adequate radiance coverage'),
                Line2D([], [], marker='x', linestyle='', color='black', label='Insufficient radiance coverage')]
    ax.legend(handles=handles, fontsize=9, loc='best')
    ax.set_xlabel('Mean 985 cm$^{-1}$ radiance [mW m$^{-2}$ sr$^{-1}$ (cm$^{-1}$)$^{-1}$]')
    ax.set_ylabel('Radiance standard deviation [same units]')
    minutes = policy.get(window+'_minutes')
    window_title = f'{minutes:g}-minute {window}' if minutes is not None else window+' window'
    ax.set_title(f'985 cm$^{{-1}}$ radiance: {window_title}\n{date_bound(start):%Y-%m-%d} to {date_bound(end):%Y-%m-%d} (UTC)')
    ax.set_ylim(0,5)
    ax.set_xlim(-5,40)
    ax.grid(alpha=.2)
    omitted = int((~cases.plot_available).sum())
    note = f'{len(cases)} cases in range; {len(plotted)} plotted; {omitted} missing mean/std. Colors use ASI evidence only.'
    fig.text(.5, .025, note, ha='center', fontsize=9)
    fig.tight_layout(rect=(0, .055, 1, 1))
    fig.savefig(paths['figure'], dpi=200)
    plt.close(fig)
    summary = {'manifest': str(Path(manifest).resolve()), 'start_inclusive': str(start), 'end_inclusive': str(end),
               'window': window, 'policy': policy, 'cases_in_range': len(cases), 'plotted': len(plotted),
               'missing_mean_or_std': omitted,
               'adequate_coverage_plotted': int(plotted.coverage_adequate.sum()),
               'insufficient_coverage_plotted': int((~plotted.coverage_adequate).sum()),
               'color_source': 'asi_state (independent of radiance classification)',
               'candidate_mean_max': mean_max, 'candidate_std_max': std_max}
    if mean_max is not None and std_max is not None:
        # Exclude inadequate observations from candidate calibration counts.
        eligible = cases.plot_available & cases.coverage_adequate
        passes = (cases.radiance_mean <= mean_max) & (cases.radiance_std <= std_max)
        cases['candidate_pass'] = pd.Series(pd.NA, index=cases.index, dtype='boolean')
        cases.loc[eligible, 'candidate_pass'] = passes[eligible]
        summary['candidate_counts_by_asi'] = {
            state: {'eligible': int((eligible & (cases.asi_label == state)).sum()),
                    'passes': int((eligible & passes & (cases.asi_label == state)).sum())}
            for state in COLORS}
    cases.to_csv(paths['cases'], index=False)
    paths['summary'].write_text(json.dumps(summary, indent=2, allow_nan=False)+'\n')
    print(note, flush=True)
    if not policy:
        print('No policy.json found beside manifest; window duration and original spectral selection cannot be verified.', flush=True)
    for kind, path in paths.items():
        print(f'{kind}: {path.resolve()}', flush=True)
    if 'candidate_counts_by_asi' in summary:
        print('Candidate limits (adequate coverage only): '+json.dumps(summary['candidate_counts_by_asi']), flush=True)
    return paths


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('start', help='First UTC date, inclusive')
    parser.add_argument('end', help='Last UTC date, inclusive')
    parser.add_argument('--manifest', type=Path, help='Existing screening manifest.csv')
    parser.add_argument('--output-dir', type=Path)
    parser.add_argument('--window', choices=('context', 'core'), default='context')
    parser.add_argument('--mean-max', type=float, help='Candidate clear mean limit, RU; visual diagnostic only')
    parser.add_argument('--std-max', type=float, help='Candidate clear standard-deviation limit, RU')
    args = parser.parse_args()
    if date_bound(args.end) < date_bound(args.start):
        parser.error('End date precedes start date')
    import config
    output = args.output_dir or Path(config.FIG_SUBDIR)/'radiance_calibration'
    manifest = args.manifest or getattr(config, 'CLOUD_SCREEN_MANIFEST', None)
    if manifest is None:
        print('No manifest selected. Screening locally available cases offline; no downloads will be made.', flush=True)
        from get_sgp_data import SGP_DATA
        manifest = SGP_DATA(args.start, args.end).screen_cases(
            offline=True, retrieval_data='none', output_dir=output/'screening')
    print(f'Reading {manifest}', flush=True)
    plot_calibration(manifest, args.start, args.end, output, args.window, args.mean_max, args.std_max)


if __name__ == '__main__':
    main()
