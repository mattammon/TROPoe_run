import numpy as np
import pandas as pd
import os
from config import *
from spectralBands import *
import secrets

class VIP:
    vip_id = secrets.token_hex(2)
    def __init__(self,sfc_block=True,irs_type=1,recenter=1,
                 mwr_type=0,cbh_type=1,add_tropoe=0,
                 model_block=False,default_pres=980.0,default_cbh=2.0,
                 in_group=False):

        self.sfc_block = sfc_block
        self.irs_type = irs_type
        self.recenter = recenter
        self.mwr_type = mwr_type
        self.cbh_type = cbh_type
        self.add_tropoe = add_tropoe
        self.model_block = model_block
        self.default_pres = default_pres
        self.default_cbh = default_cbh

        if in_group is True:
            self.ret_subdir = GROUP_NAME
        else:
            self.ret_subdir = 'misc'

        self.vip_file = f'{VIP_DIR}/curr_VIP_{self.vip_id}.txt'

        self.site_lon, self.site_lat = site_coordinates[SITE]
        self.site_alt = site_altitude[SITE]


    def vip_config(self,irs_channel=None,band=None):
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

        vip_kwargs = {
            'irs_channel':irs_channel,
            'band':band,
            'band_label':band_label,
            'band_label2':band_label2,
            'spectral_bands':spectral_bands,
        }

        return vip_kwargs


    def write_vip(self,irs_channel=None,band=None):
        file = self.vip_file
        vip_kwargs = self.vip_config(irs_channel=irs_channel,band=band)

        with open(file, 'w') as f:
            f.write('tres = 10     # Temporal resolution [min], 0 implies maximum (native) temporal resolution\n')
            f.write('avg_instant = 1\n')
            f.write('\n')
            f.write(f'station_lat = {self.site_lat}         # Station latitude [degN]\n')
            f.write(f'station_lon = {self.site_lon}      # Station longitude [degE]\n')
            f.write(f'station_alt = {self.site_alt}         # Station altitude [m MSL]\n')
            f.write(f'station_pres = {self.default_pres}        # Station pressure [mb]; will be only be used if there is no other Psfc input\n')
            f.write('\n')
            f.write(f'irs_type = {self.irs_type}                    # Specifies the type of IRS data to read\n')
            f.write(f'irsch1_path = {DATA_DIR}/irs_ch{irs_channel}/{SITE}/{MASTER_DATA_FOLDER}     # Path to the IRS ch1 radiance files\n')
            f.write(f'irssum_path = {SUM_DIR}/{MASTER_DATA_FOLDER}     # Path to the IRS summary files\n')
            f.write(f'irseng_path = {ENG_DIR}/{MASTER_DATA_FOLDER}     # Path to the IRS engineering files\n')
            f.write('irs_use_missingDataFlag = 0\n')
            f.write('\n')
            f.write(f'cbh_type = {self.cbh_type}                # Specifies the type of CBH data to read\n')
            f.write(f'cbh_path = {DATA_DIR}/dlfp       # Path to the CBH data\n')
            f.write(f'cbh_default_ht = {self.default_cbh}        # Default CBH height [km AGL], if no CBH data found\n')
            f.write('\n')
            if self.sfc_block is True:
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
                f.write(f'ext_sfc_path = {SFC_DIR}/{MASTER_DATA_FOLDER}\n')
                f.write('ext_sfc_rootname = sgpmetE13\n')
                f.write('ext_sfc_time_format = 0\n')
                f.write('ext_sfc_time_delta = 0.2\n')
                f.write('ext_sfc_relative_height = 0\n')
                f.write('\n')
            f.write(f'output_rootname = tropoeOutput_Ch{irs_channel}{vip_kwargs["band_label"]}      # String with the rootname of the output file\n')
            f.write(f'output_path = {RETRIEVAL_DIR}/{self.ret_subdir}          # Path where the output file will be placed\n')
            f.write('output_clobber = 2\n')
            f.write('\n')
            f.write(f'spectral_bands = {vip_kwargs["spectral_bands"]} #{vip_kwargs["band_label2"]}\n')
            f.write('\n')
            f.write('lbl_tape3 = TAPE3.10-3500cm-1.first_7_molecules\n')
            f.write(f'lbl_temp_dir = {DATA_DIR}/tmp2\n')
            f.write('\n')
            f.write(f'recenter_prior = {self.recenter}\n')
            f.close()




