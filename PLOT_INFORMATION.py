"""Compare vertical DFS on the cases selected by Aggregate_Retrievals.

Run through PLOT_STATS.py, from a notebook, or with --bands on this script.
See INFORMATION_CONTENT.md for scientific definitions and output descriptions.
"""

from pathlib import Path
import json
import warnings

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

from information_content import remap_dfs, information_depth


def _band(ax, values, heights, color, label, step=False):
    p25, median, p75 = np.percentile(values, [25, 50, 75], axis=0)
    if step:
        ax.stairs(median, heights, orientation='horizontal', baseline=None,
                  color=color, label=label)
        ax.fill_betweenx(heights, np.r_[p25, p25[-1]], np.r_[p75, p75[-1]],
                         color=color, alpha=0.12, step='post')
    else:
        ax.plot(median, heights, color=color, label=label)
        ax.fill_betweenx(heights, p25, p75, color=color, alpha=0.12)


def plot_information_profiles(evaluation, models=None, max_height=3.0,
                              bin_width=0.1, output_dir=None, per_case=False):
    """Write paired DFS figures and tables; return summary/manifest and paths.

    Each variable uses only cases with valid diagnostics and complete vertical
    coverage for EVERY requested model, and one diagnostic family for all models
    in that case (raw kernel or cdfs fallback). All source names and exclusions
    are exported. Existing RMSE case selection and RMSE values are not modified.
    """
    from config import FIG_SUBDIR, GROUP_NAME, group_titles

    if not np.isfinite(max_height) or max_height <= 0 or not np.isfinite(bin_width) or bin_width <= 0:
        raise ValueError('max_height and bin_width must be positive and finite')
    if models is None:
        first = next(iter(evaluation.profile_data['retrieval_snd'].values()), {})
        models = ['Ch1'] + [m for m in first if m != 'Ch1']
    models = list(models)
    if not models or models[0] != 'Ch1' or len(set(models)) != len(models):
        raise ValueError('models must be unique with Ch1 first')
    edges = np.r_[np.arange(0., max_height, bin_width), max_height]
    directory = Path(output_dir or Path(FIG_SUBDIR)/'Information_Content')
    directory.mkdir(parents=True, exist_ok=True)
    # Put each requested comparison in its own directory to avoid stale plots
    # when switching bands or height limits.
    source_mode = getattr(evaluation, 'information_source', 'auto')
    observation_mode = 'no_model' if getattr(evaluation, 'information_no_model', False) else 'all_obs'
    tag = f"{'-'.join(models)}_0-{max_height:g}km_dz{bin_width:g}_{source_mode}_{observation_mode}"
    directory = directory / tag
    directory.mkdir(parents=True, exist_ok=True)
    # Remove only this reporter's reproducible products, so a failed/empty
    # rerun cannot leave old figures or profile tables looking current.
    for pattern in ('*_information_profiles.png', '*_layer_dfs.png',
                    'information_native_profiles.csv', 'information_binned_profiles.csv',
                    'Cases/*_information.png'):
        for old in directory.glob(pattern):
            old.unlink()
    title = group_titles.get(GROUP_NAME, GROUP_NAME)
    colors = dict(zip(models, ['black'] + list(plt.get_cmap('tab10').colors)))
    if len(models) > 11:
        colors = {m: ('black' if i == 0 else plt.get_cmap('turbo')(i/len(models)))
                  for i, m in enumerate(models)}
    rows, audit, native_rows, binned_rows = [], [], [], []
    paired = {'T': {}, 'q': {}}
    for variable in paired:
        for date in evaluation.good_dts:
            candidates, case_audit = {}, []
            for model in models:
                profile = evaluation.profile_data['retrieval_snd'].get(date, {}).get(model, {})
                info = profile.get('information', {})
                diag = info.get('variables', {}).get(variable)
                row = {'case': date, 'model': model, 'variable': variable,
                       'file': profile.get('source_file', ''),
                       'time_index': info.get('time_index', ''),
                       'retrieval_time': info.get('time', ''),
                       'qc_flag': info.get('qc_flag', ''), 'source': '',
                       'paired': False, 'status': 'missing', 'reason': ''}
                if diag is None:
                    row['reason'] = info.get('errors', {}).get(variable, 'Information diagnostic unavailable')
                else:
                    row['source'] = diag['source']
                    try:
                        binned = remap_dfs(info['height_km'], diag['dfs_level'], edges)
                        if not np.all(np.isfinite(binned['dfs_bin'])):
                            raise ValueError(f'Native height grid does not cover 0--{max_height:g} km')
                        candidates[model] = (info, diag, binned)
                        row['status'] = 'valid'
                    except ValueError as exc:
                        row['status'], row['reason'] = 'invalid', str(exc)
                case_audit.append(row)
            complete = len(candidates) == len(models)
            families = {('cdfs' if d['source'].startswith('cdfs_') else 'kernel',
                         bool(info.get('no_model', False)))
                        for info, d, _ in candidates.values()}
            if complete and len(families) > 1:
                complete = False
                reason = 'Mixed diagnostic families across models; rerun with source=cdfs or consistent kernels'
            else:
                reason = 'At least one requested model is missing/invalid'
            for row in case_audit:
                row['paired'] = complete
                if not complete and row['status'] == 'valid':
                    row['reason'] = reason
            audit.extend(case_audit)
            if not complete:
                continue
            paired[variable][date] = {m: candidates[m][2] for m in models}
            baseline = candidates['Ch1'][2]['dfs_bin'].sum()
            for model, (info, diag, binned) in candidates.items():
                total = binned['dfs_bin'].sum()
                rows.append({'case': date, 'model': model, 'variable': variable,
                             'source': diag['source'], 'layer_top_km': max_height,
                             'layer_dfs': total, 'delta_dfs_vs_ch1': total-baseline,
                             'z50_layer_km': information_depth(info['height_km'], diag['dfs_level'], max_height, 0.5),
                             'z90_layer_km': information_depth(info['height_km'], diag['dfs_level'], max_height, 0.9),
                             'negative_native_dfs': diag['has_negative_dfs']})
                for z, local, cumulative in zip(info['height_km'], diag['dfs_level'], diag['cumulative_dfs']):
                    native_rows.append({'case': date, 'model': model, 'variable': variable,
                                        'source': diag['source'], 'height_km': z,
                                        'dfs_level': local, 'cumulative_dfs': cumulative})
                for k, mass in enumerate(binned['dfs_bin']):
                    binned_rows.append({'case': date, 'model': model, 'variable': variable,
                                        'z_lower_km': edges[k], 'z_upper_km': edges[k+1],
                                        'dfs_bin': mass, 'dfs_per_km': binned['density'][k],
                                        'cumulative_dfs_at_upper_edge': binned['cumulative'][k+1]})

    manifest = pd.DataFrame(audit, columns=['case', 'model', 'variable', 'file', 'time_index',
                                           'retrieval_time', 'qc_flag', 'source', 'paired', 'status', 'reason'])
    summary = pd.DataFrame(rows, columns=['case', 'model', 'variable', 'source', 'layer_top_km',
                                          'layer_dfs', 'delta_dfs_vs_ch1', 'z50_layer_km',
                                          'z90_layer_km', 'negative_native_dfs'])
    manifest.to_csv(directory/'information_manifest.csv', index=False)
    summary.to_csv(directory/'information_summary.csv', index=False)
    if native_rows:
        pd.DataFrame(native_rows).to_csv(directory/'information_native_profiles.csv', index=False)
        pd.DataFrame(binned_rows).to_csv(directory/'information_binned_profiles.csv', index=False)
    paths = []
    for variable, cases in paired.items():
        if not cases:
            warnings.warn(f'No paired {variable} information profiles; see {directory}/information_manifest.csv', stacklevel=2)
            continue
        counts = summary[(summary.variable == variable) & (summary.model == 'Ch1')].source.value_counts().to_dict()
        source_label = ', '.join(f'{key}: {value}' for key, value in counts.items())
        density = {m: np.stack([c[m]['density'] for c in cases.values()]) for m in models}
        cumulative = {m: np.stack([c[m]['cumulative'] for c in cases.values()]) for m in models}
        fig, axes = plt.subplots(1, 3, figsize=(14, 6), sharey=True)
        for model in models:
            _band(axes[0], density[model], edges, colors[model], model, step=True)
            _band(axes[1], cumulative[model], edges, colors[model], model)
            if model != 'Ch1':
                _band(axes[2], density[model]-density['Ch1'], edges, colors[model], model, step=True)
        for ax, label in zip(axes, ['DFS density (km$^{-1}$)', 'Cumulative DFS from surface',
                                    'Paired DFS density difference (Ch2 - Ch1)']):
            ax.set_xlabel(label)
            ax.set_ylim(0, max_height)
            ax.grid(alpha=0.25)
        axes[0].set_ylabel('Height (km AGL)')
        axes[2].axvline(0, color='gray', linestyle='--')
        axes[0].legend(fontsize=8)
        fig.suptitle(f'{title}: {variable} information profiles | N={len(cases)} paired cases\n'
                     f'Median and interquartile range; sources: {source_label}', fontsize=11)
        fig.tight_layout(rect=(0, 0, 1, 0.92))
        path = directory/f'{variable}_information_profiles.png'
        fig.savefig(path, dpi=180)
        plt.close(fig)
        paths.append(path)

        fig, axes = plt.subplots(1, 2, figsize=(12, 5))
        totals = [cumulative[m][:, -1] for m in models]
        axes[0].boxplot(totals, positions=np.arange(len(models)), showfliers=True)
        axes[0].set_xticks(np.arange(len(models)), models, rotation=40, ha='right')
        axes[0].set_ylabel(f'0--{max_height:g} km DFS')
        if len(models) > 1:
            axes[1].boxplot([v-totals[0] for v in totals[1:]], showfliers=True)
            axes[1].set_xticks(np.arange(1, len(models)), models[1:], rotation=40, ha='right')
        axes[1].axhline(0, color='gray', linestyle='--')
        axes[1].set_ylabel('Paired layer DFS difference (Ch2 - Ch1)')
        for ax in axes:
            ax.grid(axis='y', alpha=0.25)
        fig.suptitle(f'{title}: {variable} layer information | N={len(cases)} paired cases')
        fig.tight_layout()
        path = directory/f'{variable}_layer_dfs.png'
        fig.savefig(path, dpi=180)
        plt.close(fig)
        paths.append(path)
        if per_case:
            case_dir = directory/'Cases'
            case_dir.mkdir(exist_ok=True)
            for date, case in cases.items():
                fig, axes = plt.subplots(1, 2, figsize=(9, 5), sharey=True)
                for model in models:
                    axes[0].stairs(case[model]['density'], edges, orientation='horizontal',
                                   baseline=None, color=colors[model], label=model)
                    axes[1].plot(case[model]['cumulative'], edges, color=colors[model])
                axes[0].set_xlabel('DFS density (km$^{-1}$)')
                axes[1].set_xlabel('Cumulative DFS from surface')
                axes[0].set_ylabel('Height (km AGL)')
                axes[0].legend(fontsize=8)
                for ax in axes:
                    ax.set_ylim(0, max_height)
                    ax.grid(alpha=0.25)
                fig.suptitle(f'{date}: {variable} information profiles')
                fig.tight_layout()
                path = case_dir/f'{date}_{variable}_information.png'
                fig.savefig(path, dpi=150)
                plt.close(fig)
                paths.append(path)
    metadata = {'models': models, 'height_bin_edges_km': edges.tolist(),
                'input_cases': len(evaluation.good_dts),
                'paired_cases': {v: list(cases) for v, cases in paired.items()},
                'source': getattr(evaluation, 'information_source', 'unknown'),
                'no_model': getattr(evaluation, 'information_no_model', False),
                'figures': [str(p.relative_to(directory)) for p in paths],
                'notes': ['DFS includes all active observation types unless no_model excludes model inputs.',
                          'IQR is case spread, not a confidence interval.',
                          'Layer DFS uses fractional midpoint cells; no RMSE weights are applied.',
                          'Existing evaluation file/time selection and QC policy are inherited.']}
    (directory/'information_run.json').write_text(json.dumps(metadata, indent=2)+'\n')
    if rows:
        sources = sorted(summary.source.unique())
        if any(s.startswith('cdfs_') for s in sources):
            warnings.warn('Using TROPoe cdfs increments for some profiles; these can differ from raw diag(A). '
                          'Sources are recorded in information_manifest.csv.', stacklevel=2)
    print(f'Information diagnostics: T N={len(paired["T"])}, q N={len(paired["q"])}; {directory}')
    return {'summary': summary, 'manifest': manifest, 'output_dir': directory, 'figures': paths}


def main():
    import argparse
    from compile_retrieval_data import Aggregate_Retrievals

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bands', type=int, nargs='+', required=True)
    parser.add_argument('--max-height', type=float, default=3.)
    parser.add_argument('--bin-width', type=float, default=0.1)
    parser.add_argument('--source', choices=['auto', 'kernel', 'cdfs'], default='auto')
    parser.add_argument('--no-model', action='store_true', help='Require *_no_model diagnostics')
    parser.add_argument('--per-case', action='store_true')
    parser.add_argument('--output-dir')
    args = parser.parse_args()
    evaluation = Aggregate_Retrievals(args.max_height, args.bands, include_information=True,
                                     information_source=args.source, information_no_model=args.no_model)
    plot_information_profiles(evaluation, ['Ch1']+[f'Ch2_B{b}' for b in args.bands],
                              args.max_height, args.bin_width, args.output_dir, args.per_case)


if __name__ == '__main__':
    main()
