SITE = 'sgp'
GROUP_NAME = 'clear_sky_days'

DATA_DIR = f'/data'

GROUP_SUBDIR = f'{SITE}/{GROUP_NAME}'
SONDE_DIR = f'{DATA_DIR}/radiosonde/{GROUP_SUBDIR}'
ASI_DIR = f'{DATA_DIR}/asi/{GROUP_SUBDIR}'
CH1_DIR = f'{DATA_DIR}/irs_ch1/{GROUP_SUBDIR}'
CH2_DIR = f'{DATA_DIR}/irs_ch2/{GROUP_SUBDIR}'
SUM_DIR = f'{DATA_DIR}/irs_sum/{GROUP_SUBDIR}'
ENG_DIR = f'{DATA_DIR}/irs_eng/{GROUP_SUBDIR}'
RETRIEVAL_DIR = f'{DATA_DIR}/tropoe/{GROUP_SUBDIR}'

SCRIPT_DIR = f'{DATA_DIR}/script_repo'
RUN_DIR = f'{DATA_DIR}/script_repo'
VIP_DIR = f'{DATA_DIR}/vips/{SITE}'

profile_figure_dir = f'{DATA_DIR}/Retrieved_Profiles/{GROUP_SUBDIR}'
retrieval_stats_dir = f'{DATA_DIR}/Retrieval_Statistics/{GROUP_SUBDIR}'

#### ARM Profile ####
username = 'ammo0000'
token = '1135d911aebbb142'

login = f'-u {username}:{token}'
#####################

#import sys
#print(sys.path)
# sys.path.append(SCRIPT_DIR)
