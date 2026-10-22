from spectralBands import available_ch2_bands
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

def run_legacy(skip_models=(), only_models=None):
    obs_snd_files = selected_sounding_files(SONDE_DIR, GROUP_NAME, CLOUD_SCREEN_MANIFEST, CLOUD_SCREEN_CATEGORY)
    dates = [f'{file[-19:-11]}{file[-10:-6]}' for file in obs_snd_files]

    do_ch1 = 'Ch1' not in skip_models
    candidates = sorted(int(m.split('_B')[1]) for m in only_models if m != 'Ch1') if only_models is not None else available_ch2_bands()
    bands = [b for b in candidates if f'Ch2_B{b}' not in skip_models]
    verbose='1'

    from retrieval_todo import LiveInventory
    from pathlib import Path
    targets = [rounded_retrieval_time(d) for d in dates]
    live = LiveInventory(Path(UNIVERSAL_RETRIEVAL_DIR), targets,
                         ['Ch1']+['Ch2_B'+str(b) for b in bands], 60.)
    def completed(d, channel, band=None):
        index = live.refresh()
        target = pd.to_datetime(rounded_retrieval_time(d), utc=True)
        model = 'Ch1' if channel == 1 else 'Ch2_B'+str(band)
        return index.loc[index.model.eq(model) & index.status.eq('usable') &
                         ((index.time-target).dt.total_seconds().abs() <= 60.)]

    ##########################################

    VIP_obj = VIP(isolated_work=True) if only_models is not None else VIP()

    if APPLY_RETRIEVAL_LWP_FILTER:
        for d in dates:
            if do_ch1 == True:
                if completed(d, 1).empty:
                    run_tropoe(d, VIP_obj, channel=1, verbose=verbose)

            # ==========================================
            # LWP FILTER LOGIC
            # ==========================================
            # 1. Find the Channel-1 file for the current date
            stamp = rounded_retrieval_time(d).strftime('%Y%m%d.%H%M%S')
            ch1_files = completed(d, 1).file.tolist()

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
                if completed(d, 2, b).empty:
                    run_tropoe(d, VIP_obj, channel=2, band=b, verbose=verbose)

            print(f'\nAll Retrievals for {d} Done!\n')

    else:
        for d in dates:
            if do_ch1 == True:
                if completed(d, 1).empty:
                    run_tropoe(d,VIP_obj,channel=1,verbose=verbose)
            for b in bands:
                if completed(d, 2, b).empty:
                    run_tropoe(d,VIP_obj,channel=2,band=b,verbose=verbose)
            print(f'\nAll Retrievals for {d} Done!\n')



def main():
    import argparse
    import logging
    from pathlib import Path
    from retrieval_todo import normalize_skip_bands, expected_models
    parser = argparse.ArgumentParser(description='Run queued or legacy TROPoe retrievals.')
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument('--bands', nargs='+', metavar='BAND',
                           help='Run ONLY these bands; ignores GROUP_TROPOE_SKIP_BANDS. '
                                'Use Ch1 for channel 1 and integers or Ch2_Bn for channel 2, e.g. --bands Ch1 1 6.')
    selection.add_argument('--skip-bands', nargs='*', metavar='BAND', default=None,
                        help='Skip Ch1 and/or Ch2 bands (e.g. --skip-bands Ch1 3 6 or --skip-bands 3,6). '
                             'Overrides GROUP_TROPOE_SKIP_BANDS in config.py.')
    parser.add_argument('--todo', default=RETRIEVAL_TODO_MANIFEST, help='Saved group retrieval_todo.csv; defaults to the active app queue')
    args = parser.parse_args()
    try:
        only_models = normalize_skip_bands(args.bands) if args.bands is not None else None
        if only_models is not None and not only_models:
            parser.error('--bands requires at least one valid band')
        skip_models = (set(expected_models(available_ch2_bands()))-only_models if only_models is not None else
                       normalize_skip_bands(GROUP_TROPOE_SKIP_BANDS if args.skip_bands is None else args.skip_bands))
    except ValueError as exc:
        parser.error(str(exc))
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    if only_models is not None:
        print('Running only: '+', '.join(sorted(only_models))+' (GROUP_TROPOE_SKIP_BANDS ignored)')
    if skip_models and only_models is None:
        print('Skipping retrieval bands: '+', '.join(sorted(skip_models)))
    if args.todo:
        from retrieval_todo import execute_todo
        # A stale or empty queue must never fall back to the full legacy cohort.
        vip = None
        def run_one(date, channel, band):
            nonlocal vip
            if vip is None:
                vip = VIP(isolated_work=True)
            run_tropoe(date, vip, channel=channel, band=band, verbose='1')
        options = {}
        if only_models is not None:
            from uuid import uuid4
            plan = Path(args.todo)
            label = '_'.join(m for m in expected_models(available_ch2_bands()) if m in only_models)
            report = plan.with_name(plan.stem+'_run_'+label+'_'+uuid4().hex[:12]+'.csv')
            options = dict(only_bands=only_models, report_path=report)
            print('Worker execution report: '+str(report))
        results = execute_todo(args.todo, Path(UNIVERSAL_RETRIEVAL_DIR), run_one, skip_models, **options)
        remaining = sum(row['status'] in ('failed', 'still_missing_or_incomplete') for row in results)
        skipped = sum(row['status'] == 'skipped_band' for row in results)
        print(f'To-do execution finished: {len(results)-skipped} pairs checked; {skipped} skipped by band; {remaining} remain incomplete among attempted pairs.')
        if remaining:
            raise SystemExit(1)
    else:
        run_legacy(skip_models, only_models)


if __name__ == '__main__':
    main()
