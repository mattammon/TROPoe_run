import numpy as np
import matplotlib.pyplot as plt
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
        # Convert to float array to easily detect NaNs (and convert None to NaN if present)
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
# 3. VISUALIZATION - CHECKERBOARD PLOTS
# ==========================================
# YlOrRd (Yellow-Orange-Red) is an excellent sequential colormap
# for errors: lighter colors for low errors, darker reds for high errors.
cmap_choice = 'YlOrRd'

for var in variables:
    fig, ax = plt.subplots(figsize=(12, 6))
    matrix = rmse_matrices[var]

    # Plot absolute RMSE for the entire matrix
    im = ax.imshow(matrix, cmap=cmap_choice, aspect='auto')

    # Formatting the grid to look like a checkerboard
    ax.set_xticks(np.arange(len(dates)))
    ax.set_yticks(np.arange(len(models)))
    ax.set_xticklabels(dates, rotation=45, ha='right')
    ax.set_yticklabels(models)

    # Minor ticks for drawing the gridlines exactly between cells
    ax.set_xticks(np.arange(-0.5, len(dates), 1), minor=True)
    ax.set_yticks(np.arange(-0.5, len(models), 1), minor=True)
    ax.grid(which='minor', color='black', linestyle='-', linewidth=1)
    ax.tick_params(which='minor', bottom=False, left=False)

    ax.set_title(f"{var} Profile Absolute RMSE", fontsize=14, fontweight='bold')

    # Colorbar
    divider = make_axes_locatable(ax)
    cax = divider.append_axes("right", size="3%", pad=0.1)
    fig.colorbar(im, cax=cax, label=f"Absolute {var} RMSE")

    plt.tight_layout()
    plt.savefig(f'/data/temp_figs/{var}_RMSE_checkerboard.png')
    plt.close(fig)

# ==========================================
# 4. VISUALIZATION - BOX AND WHISKER PLOT
# ==========================================
# Create two vertically stacked subplots, sharing the x-axis
fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 8), sharex=True)

# Positions for each model along the x-axis
positions = np.arange(len(models))

# Drop NaNs for the boxplot distributions
T_data = [rmse_matrices["T"][i, :][~np.isnan(rmse_matrices["T"][i, :])] for i in range(len(models))]
Td_data = [rmse_matrices["Td"][i, :][~np.isnan(rmse_matrices["Td"][i, :])] for i in range(len(models))]

# Plot T distributions in the top panel
ax1.boxplot(T_data, positions=positions, widths=0.6, patch_artist=True,
           boxprops=dict(facecolor="tab:blue", alpha=0.7, edgecolor="black"),
           medianprops=dict(color="darkblue", linewidth=2),
           flierprops=dict(markerfacecolor="tab:blue", markeredgecolor="black", alpha=0.7))

ax1.set_title(f"TROPoe Retrieved T Profile RMSE Distributions by Band: {len(dates)} {group_titles[GROUP_NAME]} Cases",
                fontsize=13, fontweight='bold')
ax1.set_ylabel(f"0-{max_height_eval} km Vertically Accumulated T RMSE (C)")
ax1.grid(axis='y', linestyle='--', alpha=0.8)

# Plot Td distributions in the bottom panel
ax2.boxplot(Td_data, positions=positions, widths=0.6, patch_artist=True,
           boxprops=dict(facecolor="tab:orange", alpha=0.7, edgecolor="black"),
           medianprops=dict(color="darkred", linewidth=2),
           flierprops=dict(markerfacecolor="tab:orange", markeredgecolor="black", alpha=0.7))

ax2.set_title(f"TROPoe Retrieved Td Profile RMSE Distributions by Band: {len(dates)} {group_titles[GROUP_NAME]} Cases",
                fontsize=13, fontweight='bold')
ax2.set_ylabel(f"0-{max_height_eval} km Vertically Accumulated Td RMSE (C)")
ax2.grid(axis='y', linestyle='--', alpha=0.8)

# Formatting the shared x-axis on the bottom plot
ax2.set_xticks(positions)
ax2.set_xticklabels(models)

# Safe max limits ignoring NaNs
max_T_rmse = np.nanmax(rmse_matrices["T"])
max_Td_rmse = np.nanmax(rmse_matrices["Td"])

# Set y-limits with a 5% padding so tops aren't cut off
ax1.set_ylim(0, max_T_rmse * 1.05)
ax2.set_ylim(0, max_Td_rmse * 1.05)

plt.tight_layout()
plt.savefig('/data/temp_figs/RMSE_Boxplots_Distributions.png')
plt.close(fig)

# ==========================================
# 5. VISUALIZATION - VERTICAL PROFILES PER CASE
# ==========================================
# Generate distinct colors for the models to distinguish them easily
colors = plt.cm.tab10(np.linspace(0, 1, len(models)))

for date in dates:
    # sharey=True links the y-axis (height) so they pan/zoom together
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 8), sharey=True)

    # Loop over all models and plot their forecasts
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

    # Extract Observed Data
    obs_hgt = mod_hgt
    obs_T = np.array(truth_data[date]['T'])
    obs_Td = np.array(truth_data[date]['Td'])

    # Plot Observed Profiles (Black, thicker, dashed)
    ax1.plot(obs_T, obs_hgt, color='black', linewidth=3, linestyle='--', label='Observed', zorder=10)
    ax2.plot(obs_Td, obs_hgt, color='black', linewidth=3, linestyle='--', label='Observed', zorder=10)

    # --- Format T Panel (Left) ---
    ax1.set_title(f"Temperature (T) Profiles", fontsize=12, fontweight='bold')
    ax1.set_xlabel("T", fontsize=11)
    ax1.set_ylabel("Height (km)", fontsize=11)
    ax1.grid(True, linestyle=':', alpha=0.7)

    # --- Format Td Panel (Right) ---
    ax2.set_title(f"Dewpoint (Td) Profiles", fontsize=12, fontweight='bold')
    ax2.set_xlabel("Td", fontsize=11)
    ax2.grid(True, linestyle=':', alpha=0.7)

    # Add a single main title and legend for the whole figure
    fig.suptitle(f"Vertical Profiles for {date}", fontsize=16, fontweight='bold', y=0.98)

    # Place legend outside the plots or on the T panel
    ax2.legend(loc='upper right', bbox_to_anchor=(1.45, 1.0), title="Models")

    plt.tight_layout()
    # Adjust right margin so the legend fits if it's placed outside
    plt.subplots_adjust(right=0.85, top=0.9)
    plt.savefig(f'/data/temp_figs/Vertical_Profiles_{date}.png', bbox_inches='tight')
    plt.close(fig)
