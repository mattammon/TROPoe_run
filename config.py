
###############################################################
"""""
Update the parameters in this block with your personalized directories
and profile info.

GROUP_NAME: The "group" that the desired retrievals can be described by
            (i.e., clear sky, cloudy sky, winter, summer, etc.) all
            retrievals and relevant data will be organized into
            subdirectories named GROUP_NAME. Add desired figure title name
            for this group to group_titles dictionary below.

DATA_DIR: Root directory where raw datasets and completed retrievals (and the
          subdirectories within which they are located) are.

FIG_DIR: Where any produced figures should be saved.

SCRIPT_DIR: Directory where the scripts that make up this repository are stored.
"""""

GROUP_NAME = 'clear_sky_days'
DATA_DIR = f'/data'
FIG_DIR = f'{DATA_DIR}/FIGS'
SCRIPT_DIR = f'{DATA_DIR}/script_repo'

###############################################################
###############################################################

"""""
Anything in this block is automatically set up and/or created upon running
setup script.
"""""

SITE = 'sgp' #Only site currently supported

FIG_SUBDIR = f'{FIG_DIR}/{SITE}'
SONDE_DIR = f'{DATA_DIR}/radiosonde/{SITE}'
ASI_DIR = f'{DATA_DIR}/asi/{SITE}'
CH1_DIR = f'{DATA_DIR}/irs_ch1/{SITE}'
CH2_DIR = f'{DATA_DIR}/irs_ch2/{SITE}'
SUM_DIR = f'{DATA_DIR}/irs_sum/{SITE}'
ENG_DIR = f'{DATA_DIR}/irs_eng/{SITE}'
SFC_DIR = f'{DATA_DIR}/met/{SITE}'
SAT_IMAGERY_DIR = f'{DATA_DIR}/satellite/{SITE}'
RETRIEVAL_DIR = f'{DATA_DIR}/tropoe/{SITE}'
MASTER_DATA_FOLDER = 'ALL'

SCRIPT_DIR = f'{DATA_DIR}/script_repo'
RUN_DIR = f'{DATA_DIR}/script_repo'
VIP_DIR = f'{DATA_DIR}/vips/{SITE}'

###############################################################


site_coordinates = {
    'sgp':[-97.484726, 36.60611],
    'nwc':[-97.44, 35.18]
}

site_altitude = {
    'sgp':237.43,
    'nwc':210.0,
}

group_titles = {
    'clear_sky_days':'Clear Sky',
    'clear_sky_withSfc':'Clear Sky',
    'clear_sky_noSfc':'Clear Sky',
}

bad_dts = {
    'clear_sky_days':[
        '202501012326',
        '202501052326',
        '202501092327',
        '202501172328',
        '202501232329',
        '202501252340',
        '202505011132',
        '202505191131',
        '202505231132',
        '202506121132',
        '202506241131',
        '202506281122',
        '202507181128',
        '202507201128',
        '202502122329',
        '202507082324',
        '202505071132'
    ],
}
