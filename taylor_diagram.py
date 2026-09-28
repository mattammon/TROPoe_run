"""Paired, normalized Taylor diagrams for aggregated TROPoe profiles."""
import csv
import logging
from pathlib import Path

import numpy as np
import matplotlib.pyplot as plt

LOG = logging.getLogger(__name__)


def taylor_statistics(observed, retrieved):
    """Population moments on an already paired, finite sample."""
    obs, ret = np.asarray(observed, float), np.asarray(retrieved, float)
    if obs.shape != ret.shape or obs.size < 2 or not (np.isfinite(obs).all() and np.isfinite(ret).all()):
        raise ValueError('Taylor statistics require at least two paired finite values')
    so, sr = float(obs.std()), float(ret.std())
    bias = float(np.mean(ret-obs))
    crmse = float(np.sqrt(np.mean(((ret-ret.mean())-(obs-obs.mean()))**2)))
    corr = float(np.clip(np.mean((obs-obs.mean())*(ret-ret.mean()))/(so*sr), -1, 1)) if so > 0 and sr > 0 else None
    return dict(n_samples=obs.size, observed_std=so, retrieved_std=sr, correlation=corr,
                std_ratio=sr/so if so > 0 else None, centered_rmse=crmse,
                normalized_centered_rmse=crmse/so if so > 0 else None,
                bias=bias, rmse=float(np.sqrt(np.mean((ret-obs)**2))))


def interpolate(height, values, grid):
    height, values = np.asarray(height, float), np.asarray(values, float)
    if height.ndim != 1 or values.shape != height.shape or len(height) < 2:
        raise ValueError('Height and values must be matching one-dimensional profiles')
    if not np.isfinite(height).all() or not np.all(np.diff(height) > 0):
        raise ValueError('Height must be finite and strictly increasing')
    # Preserve internal missing values; do not bridge gaps or extrapolate.
    values = np.where(np.isfinite(values), values, np.nan)
    return np.interp(grid, height, values, left=np.nan, right=np.nan)


def plot_taylor_profiles(evaluation, models, output_dir, max_height=3., grid_step=0.1,
                         variables=('T', 'q'), anomalies=False):
    """Pool identical case-height samples for all models, separately per variable.

    Observed T/q in Aggregate_Retrievals are already interpolated to each case's
    Ch1 grid; observed_snd['hgt'] still describes the original sounding grid.
    """
    if not np.isfinite(max_height) or not np.isfinite(grid_step) or max_height <= 0 or grid_step <= 0:
        raise ValueError('max_height and grid_step must be positive and finite')
    if not models or not variables:
        raise ValueError('At least one model and variable are required')
    grid = np.arange(int(np.floor(max_height/grid_step))+1)*grid_step
    grid = grid[grid <= max_height]
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    truth = evaluation.profile_data['observed_snd']
    forecasts = evaluation.profile_data['retrieval_snd']
    dates = list(evaluation.good_dts)
    fig, axes = plt.subplots(1, len(variables), figsize=(7*len(variables), 6),
                             subplot_kw={'projection': 'polar'}, squeeze=False)
    records, exclusions, counts = [], [], {}
    colors = plt.get_cmap('tab20')
    for var, ax in zip(variables, axes[0]):
        observed, predicted = [], []
        for date in dates:
            try:
                case = forecasts[date]
                obs = interpolate(case['Ch1']['hgt'], truth[date][var], grid)
                ret = np.array([interpolate(case[m]['hgt'], case[m][var], grid) for m in models])
                mask = np.isfinite(obs) & np.isfinite(ret).all(axis=0)
                if not mask.any():
                    raise ValueError('No common finite case-height samples')
                observed.append(np.where(mask, obs, np.nan))
                predicted.append(np.where(mask[None, :], ret, np.nan))
            except (KeyError, ValueError) as exc:
                exclusions.append(dict(case=date, variable=var, reason=str(exc)))
        stats = []
        sample_count = 0
        if observed:
            obs = np.asarray(observed)
            ret = np.asarray(predicted)
            if anomalies:
                # Remove each dataset's own across-case mean at each height.
                n = np.isfinite(obs).sum(axis=0)
                obs -= np.divide(np.nansum(obs, axis=0), n, out=np.zeros(len(grid)), where=n > 0)
                ret -= np.divide(np.nansum(ret, axis=0), n[None, :],
                                 out=np.zeros((len(models), len(grid))), where=n[None, :] > 0)[None, :, :]
                obs[:, n < 2] = np.nan
                ret[:, :, n < 2] = np.nan
            mask = np.isfinite(obs)
            sample_count = int(mask.sum())
            if sample_count >= 2:
                for i, model in enumerate(models):
                    st = taylor_statistics(obs[mask], ret[:, i, :][mask])
                    stats.append(st)
                    records.append(dict(variable=var, model=model, mode='height_anomalies' if anomalies else 'pooled',
                                        n_cases=int(mask.any(axis=1).sum()), max_height_km=max_height,
                                        grid_step_km=grid_step, **st))
        counts[var] = sample_count
        extent = 180 if any(s['correlation'] is not None and s['correlation'] < 0 for s in stats) else 90
        upper = max([1.5]+[1.15*s['std_ratio'] for s in stats if s['std_ratio'] is not None])
        ax.set_thetamin(0); ax.set_thetamax(extent); ax.set_ylim(0, upper)
        correlations = np.array([0, .2, .4, .6, .8, .9, .95, .99, 1.])
        if extent == 180:
            correlations = np.r_[-1., -.99, -.95, -.9, -.8, -.6, -.4, -.2, correlations]
        ax.set_thetagrids(np.degrees(np.arccos(correlations)), labels=[f'{c:g}' for c in correlations])
        theta = np.linspace(0, np.deg2rad(extent), 200)
        radius = np.linspace(0, upper, 200)
        tt, rr = np.meshgrid(theta, radius)
        distances = np.sqrt(np.maximum(0, 1+rr**2-2*rr*np.cos(tt)))
        cs = ax.contour(tt, rr, distances, levels=5, colors='0.5', linewidths=.7, linestyles='--')
        ax.clabel(cs, inline=True, fontsize=8, fmt='%.2g')
        ax.plot(theta, np.ones_like(theta), color='0.5', linewidth=.7)
        ax.plot(0, 1, 'k*', ms=13, label='Sounding reference')
        for i, (model, st) in enumerate(zip(models, stats)):
            if st['std_ratio'] is None:
                continue
            if st['correlation'] is None and st['retrieved_std'] != 0:
                continue
            angle = np.arccos(st['correlation']) if st['correlation'] is not None else 0.
            ax.plot(angle, st['std_ratio'], marker='o' if i < 20 else 's', linestyle='none',
                    color='black' if model == 'Ch1' else colors(i % 20), ms=7, label=model)
        if not stats or stats[0]['observed_std'] == 0:
            ax.text(.5, .5, 'Insufficient samples or zero reference variance', transform=ax.transAxes, ha='center', wrap=True)
        ax.set_title(f'{var}: {sample_count} paired case-height samples\nCorrelation (angular axis)', pad=26)
        ax.set_ylabel('Standard deviation / sounding standard deviation', labelpad=25)
        ax.grid(alpha=.35)
        ax.legend(loc='upper left', bbox_to_anchor=(1.04, 1.05), fontsize=8)
    mode = 'height_anomalies' if anomalies else 'pooled'
    fig.suptitle(f'Taylor diagram: 0–{max_height:g} km, {mode.replace("_", " ")}', y=.99)
    fig.text(.5, .02, 'Dashed contours: normalized centered RMSE. Bias is excluded; full RMSE and bias are in the CSV.', ha='center', fontsize=10)
    fig.tight_layout(rect=(0, .06, 1, .94))
    image = output/f'Taylor_{mode}.png'
    fig.savefig(image, dpi=180, bbox_inches='tight')
    plt.close(fig)
    fields = ['variable','model','mode','n_cases','max_height_km','grid_step_km','n_samples','observed_std','retrieved_std','correlation','std_ratio','centered_rmse','normalized_centered_rmse','bias','rmse']
    with (output/f'Taylor_{mode}_statistics.csv').open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fields); writer.writeheader(); writer.writerows(records)
    with (output/f'Taylor_{mode}_exclusions.csv').open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=['case','variable','reason']); writer.writeheader(); writer.writerows(exclusions)
    print(f'Taylor diagram saved: {image}; paired samples: {counts}; excluded case-variable combinations: {len(exclusions)}')
    return records
