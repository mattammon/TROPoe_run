import numpy as np
from datetime import datetime, timedelta
from typing import Iterable
import matplotlib.colors as colors
from matplotlib.pyplot import colormaps
import sys
import subprocess
import importlib

def install_and_import(package_name):
    try:
        # Check if the package is already available
        importlib.import_module(package_name)
    except ImportError:
        print(f"Installing {package_name}...")
        # Use sys.executable to target the active Python environment
        subprocess.check_call([sys.executable, "-m", "pip", "install", package_name])
        print(f"{package_name} successfully installed!")

def CVI(arr,val):
    return np.abs(arr - val).argmin()

def truncate_colormap(cmap_name, minval=0.0, maxval=1.0, n=100):
    cmap = colormaps[cmap_name]
    sampled_colors = cmap(np.linspace(minval, maxval, n))
    return colors.LinearSegmentedColormap.from_list(
        f'trunc({cmap.name},{minval:.2f},{maxval:.2f})',
        sampled_colors
    )

def dew_point(tair,relh):
    """ Calulate Dew Point Temperature
    :param tair:   Temperature in degrees Celsius.
    :param relh:   Relative Humidity in percent.
    :return:       Dew Point in degrees Celsius.
    """
    es = 6.1365 * np.exp((17.502 * tair) / (240.97 + tair))
    e = (relh / 100.0) * es
    td = 240.97 * np.log(e / 6.1365) / (17.502 - np.log(e / 6.1365))
    diff = td - tair
    td[diff>0] = np.nan
    return td

def datetime_to_decimal_hours(
    datetimes: Iterable[datetime],
    wrap_midnight: bool = False,) -> list[float]:
    """
    Convert datetime objects to decimal hours rounded to the nearest 15 minutes.

    Examples
    --------
    09:07 -> 9.00
    09:08 -> 9.25
    09:29 -> 9.50
    09:53 -> 10.00
    23:55 -> 0.00 when wrap_midnight=True
    """
    decimal_times = []

    for dt in datetimes:
        # Include seconds and microseconds in the rounding.
        seconds_since_midnight = (
            dt.hour * 3600
            + dt.minute * 60
            + dt.second
            + dt.microsecond / 1_000_000
        )

        # Each 15-minute interval contains 900 seconds.
        rounded_intervals = int(seconds_since_midnight / 900 + 0.5)
        decimal_hour = rounded_intervals * 0.25

        if wrap_midnight:
            decimal_hour %= 24

        decimal_times.append(f'{decimal_hour}')

    return decimal_times
