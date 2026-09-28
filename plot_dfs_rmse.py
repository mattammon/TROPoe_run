"""Layer-integrated DFS versus sounding RMSE on a common paired case set."""
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from information_content import remap_dfs
from taylor_diagram import interpolate


def plot_dfs_rmse(evaluation, models, output_dir, max_height=3., grid_step=.1,
                  show_cases=False):
    if not models or not np.isfinite(max_height) or not np.isfinite(grid_step) or min(max_height, grid_step) <= 0:
        raise ValueError('Models and positive finite height/grid step are required')
    # Midpoint quadrature gives equal weight per unit height, including the
    # shortened last bin when the layer top is not a multiple of grid_step.
    edges = np.r_[np.arange(0., max_height, grid_step), max_height]
    grid, weights = (edges[:-1]+edges[1:])/2, np.diff(edges)/max_height
    rows, exclusions = [], []
    for variable in ('T', 'q'):
        for date in evaluation.good_dts:
            try:
                case = evaluation.profile_data['retrieval_snd'][date]
                obs = interpolate(case['Ch1']['hgt'], evaluation.profile_data['observed_snd'][date][variable], grid)
                candidates, families = [], set()
                for model in models:
                    profile = case[model]
                    info = profile.get('information', {})
                    diag = info.get('variables', {}).get(variable)
                    if diag is None:
                        raise ValueError(model+': '+info.get('errors', {}).get(variable, 'missing information diagnostic'))
                    mass = remap_dfs(info['height_km'], diag['dfs_level'], [0., max_height])['dfs_bin']
                    ret = interpolate(profile['hgt'], profile[variable], grid)
                    if not (np.isfinite(mass).all() and np.isfinite(obs).all() and np.isfinite(ret).all()):
                        raise ValueError(model+': incomplete finite coverage of evaluation layer')
                    families.add(('cdfs' if diag['source'].startswith('cdfs_') else 'kernel', bool(info.get('no_model', False))))
                    mse = float(np.sum(weights*(ret-obs)**2))
                    candidates.append(dict(case=date, model=model, variable=variable, source=diag['source'],
                                           layer_top_km=max_height, layer_dfs=float(mass.sum()),
                                           mse=mse, rmse=float(np.sqrt(mse))))
                if len(families) != 1:
                    raise ValueError('Mixed diagnostic families across models within case')
                rows.extend(candidates)
            except (KeyError, ValueError) as exc:
                exclusions.append(dict(case=date, variable=variable, reason=str(exc)))
    data = pd.DataFrame(rows, columns=['case','model','variable','source','layer_top_km','layer_dfs','mse','rmse'])
    out = Path(output_dir); out.mkdir(parents=True, exist_ok=True)
    summary = []
    fig, axes = plt.subplots(1, 2, figsize=(13, 5.5))
    for ax, variable, unit in zip(axes, ('T','q'), ('°C','g/kg')):
        subset = data[data.variable == variable]
        for i, model in enumerate(models):
            d = subset[subset.model == model]
            if d.empty:
                continue
            x, y = float(d.layer_dfs.mean()), float(np.sqrt(d.mse.mean()))
            summary.append(dict(variable=variable, model=model, n_cases=len(d), layer_top_km=max_height,
                                grid_step_km=grid_step, mean_layer_dfs=x, pooled_rmse=y,
                                sources=';'.join(sorted(d.source.unique()))))
            color = 'black' if model == 'Ch1' else plt.get_cmap('tab20')(i % 20)
            if show_cases:
                ax.scatter(d.layer_dfs, d.rmse, s=12, alpha=.12, color=color)
            ax.scatter(x, y, s=90, marker='*' if model == 'Ch1' else 'o', color=color, label=model, zorder=3)
        ax.set_title(f'{variable}: {subset.case.nunique()} paired cases')
        ax.set_xlabel(f'Mean accumulated DFS, 0–{max_height:g} km')
        ax.set_ylabel(f'Pooled layer RMSE ({unit})')
        ax.grid(alpha=.3)
        if subset.empty:
            ax.text(.5,.5,'No paired DFS/RMSE cases\nSee exclusions CSV',transform=ax.transAxes,ha='center')
        else:
            ax.legend(loc='upper left',bbox_to_anchor=(1.01,1),fontsize=8)
    fig.suptitle('Observational information versus retrieval error')
    fig.text(.5,.01,'Each marker summarizes the same cases across models within its panel. More DFS does not by itself imply greater accuracy.',ha='center',fontsize=9)
    fig.tight_layout(rect=(0,.05,1,.95))
    fig.savefig(out/'DFS_vs_RMSE.png',dpi=180,bbox_inches='tight');plt.close(fig)
    data.to_csv(out/'DFS_vs_RMSE_cases.csv',index=False)
    pd.DataFrame(summary,columns=['variable','model','n_cases','layer_top_km','grid_step_km','mean_layer_dfs','pooled_rmse','sources']).to_csv(out/'DFS_vs_RMSE_summary.csv',index=False)
    pd.DataFrame(exclusions,columns=['case','variable','reason']).to_csv(out/'DFS_vs_RMSE_exclusions.csv',index=False)
    print(f'DFS/RMSE plot saved: {out}/DFS_vs_RMSE.png; excluded case-variable combinations: {len(exclusions)}')
    return data, summary
