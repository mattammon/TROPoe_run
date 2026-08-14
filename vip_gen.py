import numpy as np
import pandas as pd
import os
from config import *
from spectralBands import *
import secrets

class VIP:
    vip_id = secrets.token_hex(2)
    def __init__(self,data_path=GROUP_SUBDIR):
        self.vip_type_dict = {
            'default':self.default_vip,
            'no_surface':self.no_surface_vip,
        }

        self.vip_file = f'{VIP_DIR}/curr_VIP_{self.vip_id}.txt'
        self.data_path = data_path

    def write_vip(self,vip_type='default',irs_channel=None,band=None):
        try:
            os.remove(self.vip_file)
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

        vip_args = {
            'irs_channel':irs_channel,
            'band':band,
            'band_label':band_label,
            'band_label2':band_label2,
            'spectral_bands':spectral_bands,
            'data_path':self.data_path
        }

        if vip_type in self.vip_type_dict:
            self.vip_type_dict[vip_type](**vip_args)

    def no_surface_vip(self,irs_channel=None,band=None,
                       band_label=None,band_label2=None,
                       spectral_bands=None,data_path=None):
        file = self.vip_file
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
            f.write(f'output_rootname = tropoeOutput_Ch{irs_channel}{band_label}_noSfc      # String with the rootname of the output file\n')
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

    def default_vip(self,irs_channel=None,band=None,
                    band_label=None,band_label2=None,
                    spectral_bands=None,data_path=None):
        file = self.vip_file
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
            f.write('ext_sfc_temp_type = 1\n')
            f.write('ext_sfc_temp_fieldname = temp_mean\n')
            f.write('ext_sfc_temp_units = 1\n')
            f.write('ext_sfc_temp_npts = 1\n')
            f.write('ext_sfc_temp_random_error = 0.5\n')
            f.write('ext_sfc_temp_rep_error = 0.0\n')
            f.write('ext_sfc_wv_type = 1\n')
            f.write('ext_sfc_wv_fieldname = rh_mean\n')
            f.write('ext_sfc_wv_units = 1\n')
            f.write('ext_sfc_wv_npts = 1\n')
            f.write('ext_sfc_rh_random_error = 3.0\n')
            f.write('ext_sfc_wv_mult_error = 1.0\n')
            f.write('ext_sfc_wv_rep_error = 0.0\n')
            f.write('ext_sfc_pres_type = 1\n')
            f.write('ext_sfc_pres_fieldname = atmos_pressure\n')
            f.write('ext_sfc_pres_units = 1\n')
            f.write(f'ext_sfc_path = {DATA_DIR}/met\n')
            f.write('ext_sfc_rootname = sgpmetE13\n')
            f.write('ext_sfc_time_format = 0\n')
            f.write('ext_sfc_time_delta = 0.2\n')
            f.write('ext_sfc_relative_height = 0\n')
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

