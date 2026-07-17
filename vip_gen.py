import numpy as np
import pandas as pd
import os
from config import *
from spectralBands import *

def write_vip(data_path=None,irs_channel=None,band=None):
    file = f'{VIP_DIR}/curr_VIP.txt'
    try:
        os.remove(file)
    except FileNotFoundError:
        pass
    if irs_channel == 1:
        band_label = ''
        band_label2 = ''
        spectral_bands = ch1_bands
    elif irs_channel == 2:
        band_label = f'_B{band}'
        band_label2 = f'band{band}'
        spectral_bands = ch2_bands[band_label2]

    with open(file, 'w') as f:
        f.write('tres = 10     # Temporal resolution [min], 0 implies maximum (native) temporal resolution\n')
        f.write('avg_instant = 1\n')
        f.write('\n')
        f.write('station_lat = 36.60611         # Station latitude [degN]\n')
        f.write('station_lon = -97.484726      # Station longitude [degE]\n')
        f.write('station_alt = 237.43         # Station altitude [m MSL]\n')
        f.write('station_pres = 980.0        # Station pressure [mb]; will be only be used if there is no other Psfc input\n')
        f.write('\n')
        f.write('irs_type = 1                    # Specifies the type of IRS data to read\n')
        f.write(f'irsch1_path = {DATA_DIR}/irs_ch{irs_channel}/{data_path}     # Path to the IRS ch1 radiance files\n')
        f.write(f'irssum_path = {DATA_DIR}/irs_sum/{data_path}     # Path to the IRS summary files\n')
        f.write(f'irseng_path = {DATA_DIR}/irs_eng/{data_path}     # Path to the IRS engineering files\n')
        f.write('irs_use_missingDataFlag = 0\n')
        f.write('\n')
        f.write('cbh_type = 1                # Specifies the type of CBH data to read\n')
        f.write(f'cbh_path = {DATA_DIR}/dlfp       # Path to the CBH data\n')
        f.write('cbh_default_ht = 2.0        # Default CBH height [km AGL], if no CBH data found\n')
        f.write('\n')
        f.write(f'output_rootname = tropoeOutput_Ch{irs_channel}{band_label}      # String with the rootname of the output file\n')
        f.write(f'output_path = {DATA_DIR}/tropoe/{data_path}          # Path where the output file will be placed\n')
        f.write('output_clobber = 2\n')
        f.write('\n')
        f.write(f'spectral_bands = {spectral_bands} #{band_label2}\n')
        f.write('\n')
        f.write('lbl_tape3 = TAPE3.10-3500cm-1.first_7_molecules\n')
        f.write(f'lbl_temp_dir = {DATA_DIR}/tmp2\n')
        f.write('\n')
        f.write('recenter_prior = 1\n')
        f.close()

