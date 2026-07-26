import numpy as np
import matplotlib.pyplot as plt
from matplotlib.colors import TwoSlopeNorm
from mpl_toolkits.axes_grid1 import make_axes_locatable

from compile_retrieval_data import Retrieval_Evaluation
from config import *


Ch2_bands_toEval = [1,2,6,11,12]

#Plot_Ch1 = True
Ch2_bands_toPlot = [1,2,6,11,12]

#Plot_Observed = True

max_height_eval = 5
max_height_plot = 5

EVAL = Retrieval_Evaluation(max_height_eval,
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
# 1. GENERATE MOCK DATA (Matching your structure)
# ==========================================
# dates = [f"2026-07-{d:02d}" for d in range(1, 8)]
# models = ["Baseline"] + [f"Exp_{i}" for i in range(1, 11)]
# variables = ["T", "Td"]
# profile_length = 20

# # Truth Dictionary
# truth_data = {}
# for date in dates:
#     truth_data[date] = {
#         "T": np.linspace(30, -10, profile_length) + np.random.normal(0, 1, profile_length),
#         "Td": np.linspace(20, -20, profile_length) + np.random.normal(0, 1, profile_length)
#     }

# # Forecast Dictionary
# forecast_data = {model: {} for model in models}
# for model in models:
#     for date in dates:
#         # Simulate forecasts with slight variations
#         error_magnitude = 2.0 if model == "Baseline" else np.random.uniform(1.0, 3.0)
#         forecast_data[model][date] = {
#             "T": truth_data[date]["T"] + np.random.normal(0, error_magnitude, profile_length),
#             "Td": truth_data[date]["Td"] + np.random.normal(0, error_magnitude, profile_length)
#         }

# ==========================================
# 2. COMPUTE RMSE
# ==========================================
# Dictionaries to store the matrices for plotting
# Shape: (Number of Models, Number of Cases)
rmse_matrices = {
    "T": np.zeros((len(models), len(dates))),
    "Td": np.zeros((len(models), len(dates)))
}

for v, var in enumerate(variables):
    for j, date in enumerate(dates):
        truth_profile = np.array(truth_data[date][var])

        # Calculate Baseline RMSE first
        base_forecast = np.array(forecast_data[date]['Ch1'][var])

        print(truth_profile)
        print(base_forecast)

        base_rmse = np.sqrt(np.mean((base_forecast - truth_profile) ** 2))
        rmse_matrices[var][0, j] = base_rmse

        # Calculate Experimental RMSE and store the difference from baseline
        for i, model in enumerate(models[1:], start=1):
            exp_forecast = np.array(forecast_data[date][model][var])
            exp_rmse = np.sqrt(np.mean((exp_forecast - truth_profile) ** 2))

            # Storing the difference: (Experiment RMSE - Baseline RMSE)
            # Negative means Experiment has lower error (Improvement)
            rmse_matrices[var][i, j] = exp_rmse - base_rmse

# ==========================================
# 3. VISUALIZATION
# ==========================================
fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 12))
axes = {"T": ax1, "Td": ax2}

for var, ax in axes.items():
    matrix = rmse_matrices[var]

    # Split the matrix into Baseline (Row 0) and Experiments (Rows 1+)
    # We use np.full with np.nan to mask out the other rows during plotting
    base_matrix = np.full_like(matrix, np.nan)
    base_matrix[0, :] = matrix[0, :]

    exp_matrix = np.full_like(matrix, np.nan)
    exp_matrix[1:, :] = matrix[1:, :]

    # Plot Baseline: Sequential colormap (Absolute RMSE)
    # Greys colormap: darker = higher RMSE
    im_base = ax.imshow(base_matrix, cmap='Greys', aspect='auto')

    # Plot Experiments: Diverging colormap (Difference from Baseline)
    # RdBu_r: Blue = Negative diff (Improvement), Red = Positive diff (Degradation), White = 0
    # TwoSlopeNorm ensures that 0 is exactly in the center of the colormap.
    max_abs_diff = np.nanmax(np.abs(exp_matrix))
    norm = TwoSlopeNorm(vcenter=0, vmin=-max_abs_diff, vmax=max_abs_diff)
    im_exp = ax.imshow(exp_matrix, cmap='RdBu_r', norm=norm, aspect='auto')

    # Formatting the grid to look like a checkerboard
    ax.set_xticks(np.arange(len(dates)))
    ax.set_yticks(np.arange(len(models)))
    ax.set_xticklabels(dates, rotation=45, ha='right')
    ax.set_yticklabels(models)

    ax.set_xticks(np.arange(-0.5, len(dates), 1), minor=True)
    ax.set_yticks(np.arange(-0.5, len(models), 1), minor=True)
    ax.grid(which='minor', color='black', linestyle='-', linewidth=1)
    ax.tick_params(which='minor', bottom=False, left=False)

    ax.set_title(f"{var} Profile RMSE Analysis", fontsize=14, fontweight='bold')

    # Adding Colorbars side-by-side using make_axes_locatable
    divider = make_axes_locatable(ax)
    cax1 = divider.append_axes("right", size="3%", pad=0.1)
    cax2 = divider.append_axes("right", size="3%", pad=0.8)

    fig.colorbar(im_base, cax=cax1, label="Baseline Abs RMSE")
    fig.colorbar(im_exp, cax=cax2, label="Diff (Exp - Baseline)")

#plt.savefig(f'{profile_figure_dir}/test.png')
plt.savefig(f'test.png')

plt.tight_layout()
plt.show()

