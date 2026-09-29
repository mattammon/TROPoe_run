import sys, os
import pandas as pd
import glob
import xarray as xr  # Added to read the Ch1 NetCDF file

from config import *
from cloud_screening import selected_sounding_files
from utils import *
from vip_gen import VIP
from SINGLE_TROPoe import run_tropoe

##########################################

obs_snd_files = selected_sounding_files(SONDE_DIR, GROUP_NAME, CLOUD_SCREEN_MANIFEST, CLOUD_SCREEN_CATEGORY)
dates = [f'{file[-19:-11]}{file[-10:-6]}' for file in obs_snd_files]

do_ch1 = False
bands = [2,6,7,10,18]
verbose='1'

catalog = pd.read_csv(f'{RETRIEVAL_DIR}/{GROUP_NAME}/catalog/files.csv')
catalog_files = {os.path.basename(path) for path in catalog.loc[catalog['n_usable'] > 0, 'file']}

##########################################

def completed_retrieval(date, channel, catalog_files, band=None):
    root = f'tropoeOutput_Ch{channel}' + (f'_B{band}' if band is not None else '')
    stem = f'{root}.{date[:8]}.{date[8:10]}'
    return any(name.startswith(stem) for name in catalog_files)

VIP_obj = VIP(in_group=True)

if APPLY_RETRIEVAL_LWP_FILTER:
    for d in dates:
        if do_ch1 == True:
            if not completed_retrieval(d, 1, catalog_files):
                run_tropoe(d, VIP_obj, channel=1, verbose=verbose)

        # ==========================================
        # LWP FILTER LOGIC
        # ==========================================
        # 1. Find the Channel-1 file for the current date
        ch1_files = sorted(glob.glob(f'{RETRIEVAL_DIR}/{GROUP_NAME}/tropoeOutput_Ch1.{retrieval_stamp(d)}00.nc'))

        if not ch1_files:
            print(f"Skipping {d}: No Channel-1 retrieval file found.")
            continue  # Skip to the next date in the loop

        # 2. Match the retrieval's rounded time, not a different case on the same day.
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
            if not completed_retrieval(d, 2, catalog_files, b):
                run_tropoe(d, VIP_obj, channel=2, band=b, verbose=verbose)

        print(f'\nAll Retrievals for {d} Done!\n')

else:
    for d in dates:
        if do_ch1 == True:
            if not completed_retrieval(d, 1, catalog_files):
                run_tropoe(d,VIP_obj,channel=1,verbose=verbose)
        for b in bands:
            if not completed_retrieval(d, 2, catalog_files, b):
                run_tropoe(d,VIP_obj,channel=2,band=b,verbose=verbose)
        print(f'\nAll Retrievals for {d} Done!\n')
