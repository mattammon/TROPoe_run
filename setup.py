import os
from config import *

def create_directories():
    print("Setting up repository directories...")

    # List of directories explicitly defined in config.py
    directories = [
        DATA_DIR,
        FIG_DIR,
        SCRIPT_DIR,
        GROUP_SUBDIR,
        SONDE_DIR,
        ASI_DIR,
        CH1_DIR,
        CH2_DIR,
        SUM_DIR,
        ENG_DIR,
        SFC_DIR,
        RETRIEVAL_DIR,
        SAT_IMAGERY_DIR,
        VIP_DIR
    ]

    # Additional directories required by vip_gen.py
    directories.extend([
        f'{DATA_DIR}/dlfp',
        f'{DATA_DIR}/tmp2'
    ])

    for directory in directories:
        try:
            os.makedirs(directory, exist_ok=True)
            print(f"Created/Verified: {directory}")
        except PermissionError:
            print(f"Permission denied: {directory}. Try updating DATA_DIR in config.py to a local path.")
        except Exception as e:
            print(f"Error creating {directory}: {e}")

    print("\nSetup complete! Ensure you run in a TROPoe container!")

if __name__ == "__main__":
    create_directories()
