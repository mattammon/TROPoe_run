import sys, os
import pandas as pd
from datetime import datetime
import glob
import xarray as xr  # Added to read the Ch1 NetCDF file
import numpy as np   # Added to find the closest time match

from config import *
from utils import *
from vip_gen import VIP
from SINGLE_TROPoe import run_tropoe

##########################################

obs_snd_files = sorted(glob.glob(f'{SONDE_DIR}/{GROUP_NAME}/*sonde*'))
dates = [f'{file[-19:-11]}{file[-10:-6]}' for file in obs_snd_files]

do_ch1 = False
bands = [3]
verbose='1'

##########################################

VIP_obj = VIP(in_group=True)

if 'clear' in GROUP_NAME:
    for d in dates:
        if do_ch1 == True:
            run_tropoe(d, VIP_obj, channel=1, verbose=verbose)

        # ==========================================
        # LWP FILTER LOGIC
        # ==========================================
        # 1. Find the Channel-1 file for the current date
        ch1_files = sorted(glob.glob(f'{RETRIEVAL_DIR}/{GROUP_NAME}/*Ch1.{d[:8]}*'))

        if not ch1_files:
            print(f"Skipping {d}: No Channel-1 retrieval file found.")
            continue  # Skip to the next date in the loop

        # 2. Match the exact file if multiple exist for the same day
        if len(ch1_files) > 1:
            idx = np.argmin([abs(int(i[-9:-7]) - int(d[8:10])) for i in ch1_files])
            ch1_file = ch1_files[idx]
        else:
            ch1_file = ch1_files[0]

        # 3. Read LWP and evaluate
        try:
            with xr.open_dataset(ch1_file) as ds:
                lwp = ds.lwp.data[0]
                lwp_unc = ds.sigma_lwp.data[0]

            # If the conditions are violated, skip the Ch2 retrievals
            if lwp >= 1 and lwp > lwp_unc:
                print(f"Skipping {d}: Failed LWP check (LWP: {lwp:.3f}, Unc: {lwp_unc:.3f})")
                continue

        except Exception as e:
            print(f"Skipping {d}: Failed to read LWP from {ch1_file}. Error: {e}")
            continue
        # ==========================================

        # If the script makes it here, the Ch1 retrieval passed the LWP check!
        for b in bands:
            run_tropoe(d, VIP_obj, channel=2, band=b, verbose=verbose)

        print(f'\nAll Retrievals for {d} Done!\n')

else:
    for d in dates:
        if do_ch1 == True:
            run_tropoe(d,VIP_obj,channel=1,verbose=verbose)
        for b in bands:
            run_tropoe(d,VIP_obj,channel=2,band=b,verbose=verbose)
        print(f'\nAll Retrievals for {d} Done!\n')
