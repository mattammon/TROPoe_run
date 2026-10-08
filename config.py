
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
# Path printed by get_sgp_data.py. None preserves legacy group-folder selection.
CLOUD_SCREEN_MANIFEST = '/data/cloud_screening/sgp/20220101_20251231/manifest_reclassified_7_0p3.csv'
CLOUD_SCREEN_CATEGORY = 'clear_sky'
DATA_DIR = f'/data'
FIG_DIR = f'{DATA_DIR}/FIGS/temp'
SCRIPT_DIR = f'{DATA_DIR}/script_repo'

###############################################################
###############################################################

"""""
Anything in this block is automatically set up and/or created upon running
setup script.
"""""

SITE = 'sgp' #Only site currently supported

FIG_SUBDIR = f'{FIG_DIR}/{SITE}/{GROUP_NAME}'
SONDE_DIR = f'{DATA_DIR}/radiosonde/{SITE}'
ASI_DIR = f'{DATA_DIR}/asi/{SITE}'
CH1_DIR = f'{DATA_DIR}/irs_ch1/{SITE}'
CH2_DIR = f'{DATA_DIR}/irs_ch2/{SITE}'
SUM_DIR = f'{DATA_DIR}/irs_sum/{SITE}'
ENG_DIR = f'{DATA_DIR}/irs_eng/{SITE}'
SFC_DIR = f'{DATA_DIR}/met/{SITE}'
AOD_DIR = f'{DATA_DIR}/aod/{SITE}'
# Exact ARM datastream identifier for your AOD product (not yet in the pushed repo).
# Set this before downloading AOD; None leaves AOD downloads disabled.
AOD_DATASTREAM = None
RETRIEVAL_DIR = f'{DATA_DIR}/tropoe/{SITE}'
MASTER_DATA_FOLDER = 'ALL'
SAT_IMAGERY_DIR = f'{DATA_DIR}/satellite/{SITE}'
# Dashboard imports legacy CLOUD_SCREEN_MANIFEST if this is None.
CLOUD_MASTER_MANIFEST = '/data/cloud_screening/sgp/20220101_20251231/master_manifest.csv'
# Durable across app/container restarts; keep this directory on a mounted volume.
CLOUD_CLASSIFICATION_DIR = f'{DATA_DIR}/cloud_classification/{SITE}'
# A saved runs/.../classification.csv used by GROUP_TROPoe and cataloging.
CLOUD_CLASSIFICATION_MANIFEST = None
# Latest clear-sky case/band queue generated when entering the dashboard.
# GROUP_TROPoe uses this automatically; set None only for legacy execution.
RETRIEVAL_TODO_MANIFEST = f'{CLOUD_CLASSIFICATION_DIR}/{GROUP_NAME}/retrieval_todo.csv'
RETRIEVAL_TODO_BANDS = list(range(1, 19))  # Expected Ch2 bands; Ch1 is also required.
RETRIEVAL_TODO_TOLERANCE_SECONDS = 60.
# Cover the retrieval averaging/surface-data window, including UTC midnight.
RETRIEVAL_INPUT_PADDING_MINUTES = 15.
# Leave empty to run every band. Entries can be Ch1, Ch2_B6, or 6 (Ch2 band 6).
# GROUP_TROPoe.py --skip-bands overrides this setting for a single run.
GROUP_TROPOE_SKIP_BANDS = []
# Cloud selections do not also apply the legacy retrieval-LWP gate.
APPLY_RETRIEVAL_LWP_FILTER = (not (CLOUD_SCREEN_MANIFEST or CLOUD_MASTER_MANIFEST or CLOUD_CLASSIFICATION_MANIFEST)
                              and 'clear' in GROUP_NAME)

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


