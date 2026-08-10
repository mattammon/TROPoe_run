import numpy as np

def CVI(arr,val):
    return np.abs(arr - val).argmin()

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
