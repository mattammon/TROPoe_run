import numpy as np
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
from matplotlib.colors import TwoSlopeNorm
from mpl_toolkits.axes_grid1 import make_axes_locatable

from compile_retrieval_data import Aggregate_Retrievals
from config import *

# ==========================================
# 1. SETUP AND DATA EXTRACTION
# ==========================================
Ch2_bands_toEval = [1,2,3,4,5,6,7,8,9,10,11,12]
Ch2_bands_toPlot = [1,2,3,4,5,6,7,8,9,10,11,12]

max_height_eval = 3
max_height_plot = 3

EVAL = Aggregate_Retrievals(max_height_eval,
                            Ch2_bands_toEval,
                            Ch2_bands_toPlot)

dates = EVAL.good_dts

models = ['Ch1']
models.extend([f'Ch2_B{b}' for b in Ch2_bands_toPlot])
variables = ["T", "Td"]

profile_data_dict = EVAL.profile_data

truth_data = profile_data_dict['observed_snd']
forecast_data = profile_data_dict['retrieval_snd']

# ==========================================
# 2. COMPUTE ABSOLUTE RMSE (WITH NAN MASKING)
# ==========================================
# Dictionaries to store the matrices for plotting
# Shape: (Number of Models, Number of Cases)
rmse_matrices = {
    "T": np.zeros((len(models), len(dates))),
    "Td": np.zeros((len(models), len(dates)))
}

for v, var in enumerate(variables):
    for j, date in enumerate(dates):
        # Convert to float array to easily detect NaNs
        truth_profile = np.array(truth_data[date][var], dtype=float)

        # Create a boolean mask where the observed data is NOT missing/NaN
        valid_mask = ~np.isnan(truth_profile)

        # Calculate Baseline RMSE
        base_forecast = np.array(forecast_data[date]['Ch1'][var], dtype=float)

        # Only compute if there is at least one valid observation point
        if np.any(valid_mask):
            base_rmse = np.sqrt(np.mean((base_forecast[valid_mask] - truth_profile[valid_mask]) ** 2))
        else:
            base_rmse = np.nan

        rmse_matrices[var][0, j] = base_rmse

        # Calculate Experimental RMSE
        for i, model in enumerate(models[1:], start=1):
            exp_forecast = np.array(forecast_data[date][model][var], dtype=float)

            if np.any(valid_mask):
                exp_rmse = np.sqrt(np.mean((exp_forecast[valid_mask] - truth_profile[valid_mask]) ** 2))
            else:
                exp_rmse = np.nan

            # Store the absolute RMSE for all models
            rmse_matrices[var][i, j] = exp_rmse

# ==========================================
# 3. VISUALIZATION - CHECKERBOARD PLOTS (DIFF + MEDIAN)
# ==========================================
for var in variables:
    # Made the figure taller to accommodate the list of dates on the y-axis
    fig, ax = plt.subplots(figsize=(12, 15))
    abs_matrix = rmse_matrices[var]

    # Create Difference Matrix (Exp - Baseline)
    diff_matrix = np.zeros_like(abs_matrix)
    diff_matrix[0, :] = abs_matrix[0, :] # Row 0 stays absolute
    for i in range(1, len(models)):
        diff_matrix[i, :] = abs_matrix[i, :] - abs_matrix[0, :]

    # Calculate medians across cases (ignoring NaNs)
    medians = np.nanmedian(diff_matrix, axis=1)

    # Append medians, then TRANSPOSE so models are on X and dates are on Y
    plot_matrix = np.c_[diff_matrix, medians].T

    # Split for colormaps (Baseline is now Column 0 instead of Row 0)
    base_matrix = np.full_like(plot_matrix, np.nan)
    base_matrix[:, 0] = plot_matrix[:, 0]

    exp_matrix = np.full_like(plot_matrix, np.nan)
    exp_matrix[:, 1:] = plot_matrix[:, 1:]

    # Plot Baseline: Sequential colormap (Absolute RMSE)
    im_base = ax.imshow(base_matrix, cmap='Greys', aspect='auto')

    # Plot Experiments: Diverging colormap (Difference from Baseline)
    max_abs_diff = np.nanmax(np.abs(exp_matrix))
    if max_abs_diff == 0 or np.isnan(max_abs_diff):
        max_abs_diff = 1.0 # Fallback
    norm = TwoSlopeNorm(vcenter=0, vmin=-max_abs_diff, vmax=max_abs_diff)
    im_exp = ax.imshow(exp_matrix, cmap='seismic', norm=norm, aspect='auto')

    # Calculate Rankings based on the median differences
    ranks_text = [""] # No rank for Baseline
    exp_medians = medians[1:]
    ranks = np.empty_like(exp_medians, dtype=int)
    # argsort inherently puts the smallest (most negative/best) difference first
    ranks[np.argsort(exp_medians)] = np.arange(1, len(exp_medians) + 1)
    ranks_text.extend([str(r) for r in ranks])

    # Overlay the rank text onto the median row (which is at y-index = len(dates))
    for i, txt in enumerate(ranks_text):
        ax.text(i, len(dates), txt, ha='center', va='center', fontweight='bold', color='black', fontsize=12)

    # Formatting the grid
    y_labels = dates + ["Median (rank)"]
    ax.set_xticks(np.arange(len(models)))
    ax.set_yticks(np.arange(len(y_labels)))
    ax.set_xticklabels(models, rotation=45, ha='right', fontsize =14)
    ax.set_yticklabels(y_labels)

    # Minor ticks for drawing gridlines
    ax.set_xticks(np.arange(-0.5, len(models), 1), minor=True)
    ax.set_yticks(np.arange(-0.5, len(y_labels), 1), minor=True)
    ax.grid(which='minor', color='black', linestyle='-', linewidth=1)
    ax.tick_params(which='minor', bottom=False, left=False)

    # Draw thicker horizontal line separating the dates from the Median row
    ax.axhline(len(dates) - 0.5, color='black', linewidth=3.5)

    ax.set_title(f"{group_titles[GROUP_NAME]} Retrievals: {var} Profile RMSE Analysis", fontsize=16, fontweight='bold')

    # Colorbars
    divider = make_axes_locatable(ax)
    cax1 = divider.append_axes("right", size="3%", pad=0.2)
    cax2 = divider.append_axes("right", size="3%", pad=0.9)
    cbar1 = fig.colorbar(im_base, cax=cax1, extend = 'both', shrink=0.8)
    cbar2 = fig.colorbar(im_exp, cax=cax2, extend = 'both', shrink=0.8)
    cbar1.set_label(f"Absolute {var} RMSE (Ch1)", size = 14)
    cbar2.set_label(f"RMSE Diff (Ch2 - Ch1)", size = 14)
    cbar1.ax.tick_params(labelsize=12)
    cbar2.ax.tick_params(labelsize=12)

    plt.tight_layout()
    plt.savefig(f'{FIG_SUBDIR}/{var}_RMSE_checkerboard.png')
    plt.close(fig)

# ==========================================
# 4. VISUALIZATION - BOX AND WHISKER PLOT
# ==========================================
fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 9), sharex=True)
positions = np.arange(len(models))

T_data = [rmse_matrices["T"][i, :][~np.isnan(rmse_matrices["T"][i, :])] for i in range(len(models))]
Td_data = [rmse_matrices["Td"][i, :][~np.isnan(rmse_matrices["Td"][i, :])] for i in range(len(models))]

ax1.boxplot(T_data, positions=positions, widths=0.6, patch_artist=True,
           boxprops=dict(facecolor="tab:blue", alpha=0.7, edgecolor="black"),
           medianprops=dict(color="darkblue", linewidth=2),
           showfliers = False)
ax1.axhline(np.nanmedian(T_data[0]), linestyle='--', c='k')

ax1.set_title(f"TROPoe Retrieved T Profile RMSE Distributions by Band: {len(dates)} {group_titles[GROUP_NAME]} Cases",
                fontsize=13, fontweight='bold')
ax1.set_ylabel(f"0-{max_height_eval} km Vertically Accumulated T RMSE (C)")
ax1.grid(axis='y', linestyle='--', alpha=0.8)

ax2.boxplot(Td_data, positions=positions, widths=0.6, patch_artist=True,
           boxprops=dict(facecolor="tab:orange", alpha=0.7, edgecolor="black"),
           medianprops=dict(color="darkred", linewidth=2),
           showfliers = False)
ax2.axhline(np.nanmedian(Td_data[0]), linestyle='--', c='k')

ax2.set_title(f"TROPoe Retrieved Td Profile RMSE Distributions by Band: {len(dates)} {group_titles[GROUP_NAME]} Cases",
                fontsize=13, fontweight='bold')
ax2.set_ylabel(f"0-{max_height_eval} km Vertically Accumulated Td RMSE (C)")
ax2.grid(axis='y', linestyle='--', alpha=0.8)

ax2.set_xticks(positions)
ax2.set_xticklabels(models,size=12,rotation=30,ha='right')

max_T_rmse = np.nanmax(rmse_matrices["T"])
max_Td_rmse = np.nanmax(rmse_matrices["Td"])

ax1.set_ylim(0, max_T_rmse * 1.01)
ax2.set_ylim(0, max_Td_rmse * 1.01)

plt.tight_layout()
plt.savefig(f'{FIG_SUBDIR}/RMSE_Boxplots_Distributions.png')
plt.close(fig)

# ==========================================
# 5. VISUALIZATION - VERTICAL PROFILES PER CASE
# ==========================================
colors = plt.cm.tab10(np.linspace(0, 1, len(models)))

for date in dates:
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 8), sharey=True)

    for i, model in enumerate(models):
        mod_hgt = np.array(forecast_data[date][model]['hgt'])
        mod_T = np.array(forecast_data[date][model]['T'])
        mod_Td = np.array(forecast_data[date][model]['Td'])

        if model == 'Ch1':
            ax1.plot(mod_T, mod_hgt, color='k', linewidth=2, label=model)
            ax2.plot(mod_Td, mod_hgt, color='k', linewidth=2, label=model)
        else:
            ax1.plot(mod_T, mod_hgt, color=colors[i], linewidth=1.5, label=model)
            ax2.plot(mod_Td, mod_hgt, color=colors[i], linewidth=1.5, label=model)

    obs_hgt = mod_hgt
    obs_T = np.array(truth_data[date]['T'])
    obs_Td = np.array(truth_data[date]['Td'])

    ax1.plot(obs_T, obs_hgt, color='black', linewidth=3, linestyle='--', label='Observed', zorder=10)
    ax2.plot(obs_Td, obs_hgt, color='black', linewidth=3, linestyle='--', label='Observed', zorder=10)

    ax1.set_title(f"Temperature (T) Profiles", fontsize=12, fontweight='bold')
    ax1.set_xlabel("T", fontsize=11)
    ax1.set_ylabel("Height (km)", fontsize=11)
    ax1.grid(True, linestyle=':', alpha=0.7)

    ax2.set_title(f"Dewpoint (Td) Profiles", fontsize=12, fontweight='bold')
    ax2.set_xlabel("Td", fontsize=11)
    ax2.grid(True, linestyle=':', alpha=0.7)

    fig.suptitle(f"Vertical Profiles for {date}", fontsize=16, fontweight='bold', y=0.98)
    ax2.legend(loc='upper right', bbox_to_anchor=(1.45, 1.0), title="Models")

    plt.tight_layout()
    plt.subplots_adjust(right=0.85, top=0.9)
    plt.savefig(f'{FIG_SUBDIR}/Profile_Plots/Vertical_Profiles_{date}.png', bbox_inches='tight')
    plt.close(fig)

# ==========================================
# 6. VISUALIZATION - VERTICAL LEVEL RMSE CHECKERBOARD
# ==========================================
# Extract the reference heights from the first case to define our y-axis
ref_hgt = np.array(forecast_data[dates[0]]['Ch1']['hgt'])
num_heights = len(ref_hgt)

for var in variables:
    fig, ax = plt.subplots(figsize=(10, 10))
    vert_matrix = np.zeros((num_heights, len(models)))

    # Compute absolute RMSE per vertical level, aggregated across all dates
    for k in range(num_heights):
        for i, model in enumerate(models):
            sq_errs = []
            for date in dates:
                truth_prof = np.array(truth_data[date][var], dtype=float)
                fcst_prof = np.array(forecast_data[date][model][var], dtype=float)

                # Ensure height index exists and both truth and forecast are valid at this level
                if k < len(truth_prof) and k < len(fcst_prof):
                    t_val = truth_prof[k]
                    f_val = fcst_prof[k]
                    if not np.isnan(t_val) and not np.isnan(f_val):
                        sq_errs.append((f_val - t_val)**2)

            if sq_errs:
                vert_matrix[k, i] = np.sqrt(np.mean(sq_errs))
            else:
                vert_matrix[k, i] = np.nan

    # Plot Vertical RMSE using 'lower' origin so surface (index 0) is at the bottom
    im = ax.imshow(vert_matrix, cmap='gnuplot2_r', aspect='auto', origin='lower')

    ax.set_xticks(np.arange(len(models)))
    ax.set_xticklabels(models, rotation=45, ha='right', size=13)

    # Set y-ticks efficiently to avoid overcrowding (e.g., plot every Nth tick)
    tick_step = max(1, num_heights // 15)
    ax.set_yticks(np.arange(0, num_heights, tick_step))
    ax.set_yticklabels([f"{ref_hgt[i]:.2f}" for i in np.arange(0, num_heights, tick_step)],size=12)

    ax.set_ylabel("Height (km)", fontsize=13)
    ax.set_title(f"{group_titles[GROUP_NAME]} Retrieved Vertical {var} Profile RMSE (Aggregated over all Cases)", fontsize=14, fontweight='bold')

    # Minor ticks for drawing gridlines
    ax.set_xticks(np.arange(-0.5, len(models), 1), minor=True)
    ax.set_yticks(np.arange(-0.5, num_heights, 1), minor=True)
    ax.grid(which='minor', color='black', linestyle='-', linewidth=0.5)
    ax.tick_params(which='minor', bottom=False, left=False)

    divider = make_axes_locatable(ax)
    cax = divider.append_axes("right", size="3%", pad=0.1)
    fig.colorbar(im, cax=cax, label=f"Absolute {var} RMSE")

    plt.tight_layout()
    plt.savefig(f'{FIG_SUBDIR}/{var}_Vertical_RMSE_checkerboard.png')
    plt.close(fig)
