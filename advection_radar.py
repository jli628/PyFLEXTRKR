import numpy as np
import matplotlib.pyplot as plt
import matplotlib
import scipy as sp
import xarray as xr
from netCDF4 import Dataset

from scipy.signal import fftconvolve
import glob, os, sys
from matplotlib.colors import LogNorm
from scipy.signal import medfilt


from skimage import data, draw
from skimage.feature import masked_register_translation
from scipy import ndimage as ndi
import datetime

from joblib import Parallel, delayed


DBZ_THRESHOLD=20
dx = 0.5
dy = 0.5
NJOBS = 30
MED_FILT_LEN=9

def offset_to_speed(x, y, time_lag, dx=0.5, dy=0.5):
    """ Return normalized speed assuming uniform grid.
    """
    mag_movement = np.sqrt((dx * x) ** 2 + (dy * y) ** 2)
    mag_dir = np.arctan2(x * dx, y * dy) * 180 / np.pi
    mag_movement_mps = np.array(
        [mag_movement_i / (time_lag) * 1000.0 for mag_movement_i in mag_movement.T]
    ).T
    return mag_movement, mag_dir, mag_movement_mps


def get_pixel_size_of_clouds(dataset, total_tracks, track_variable='pcptracknumber'):

    """ Calculate pixel size of each identified cloud in the file.
    Parameters:
    -----------
    dataset: Dataset
        netcdf Dataset
    track_variable: string
        variable that contains pixel level values.
    Returns:
    --------
    counts: array_like
        Pixel size of every cloud in file. Cloud 0 is stored at 0.
    """
    storm_sizes = np.zeros(total_tracks + 1)

    track, counts = np.unique(dataset.variables[track_variable][:], return_counts=True)
    storm_sizes[track] = counts
    storm_sizes[0] = 0
    return storm_sizes


def movement_of_storm_fft(
    dset_1,
    dset_2,
    cuts=1,
    times=None,
    threshold=30,
    plot_subplots=False,
    buffer=30,
    size_threshold=10,
):

    """ Calculate Movement of first labeled storm
    Parameters
    ----------
    field_1: str
        Current field (t=0)
    field_2: str
        t=1 field
    """
    field_1 = np.squeeze(dset_1['dbz_comp'].values)
    field_2 = np.squeeze(dset_2['dbz_comp'].values)
    #     cuts = 1
    #     thresh = 25
    #     plot_subplots = False
    #     buffer = 30

    y_lag = np.zeros((cuts, cuts))
    x_lag = np.zeros((cuts, cuts))

    # mask_1 = np.logical_or(np.squeeze(dset_1['conv_mask_inflated'].values> 0), field_1>thresh)
    # mask_2 = np.logical_or(np.squeeze(dset_2['conv_mask_inflated'].values> 0), field_2>thresh)

    mask_1 = field_1 > threshold
    mask_2 = field_2 > threshold

    # field_1[field_1 < thresh] = -60
    # field_2[field_2 < thresh] = -60 # May cause issues with convolution later.

    # field_1[np.logical_not(mask_1)] = thresh
    # field_2[np.logical_not(mask_2)] = thresh # May cause issues with convolution later.

    dimensions = field_1.shape
    x_skip = int(dimensions[0] / cuts)
    y_skip = int(dimensions[1] / cuts)

    # Mask each region into a cut
    for col in range(0, cuts):
        for row in range(0, cuts):
            mask = np.zeros(field_1.shape)
            mask[
                buffer + row * x_skip : (row + 1) * x_skip - buffer,
                buffer + col * y_skip : (col + 1) * y_skip - buffer,
            ] = 1
            mask = mask * mask_1
            mask[field_1 < -100] = 0
            mask_2[field_2 < -100] = 0

            num_points = np.sum(mask > 0)
            y, x = -1 * masked_register_translation(
                field_1, field_2, mask_1, mask_2, overlap_ratio=0.7
            )

            if plot_subplots:
                plt.figure(figsize=(10, 5))
                plt.subplot(1, 2, 1)
                plt.pcolormesh(field_1 * mask, vmin=-20, vmax=50, cmap='jet')
                plt.colorbar()
                plt.arrow(100, 100, x, y, head_width=5)
                plt.subplot(1, 2, 2)
                plt.pcolormesh(field_2 * mask_2, vmin=-20, vmax=50, cmap='jet')
                plt.colorbar()

                plt.figure(figsize=(10, 10))
                plt.pcolormesh(field_2 * mask_2, vmin=-20, vmax=50, cmap='jet')
                shifted_field_1 = ndi.shift(mask_1, [int(y), int(x)])
                #                 plt.contour(mask_2.astype(float)-shifted_field_1, vmin=-1, vmax=1, cmap='seismic', levels=3)
                plt.contour(shifted_field_1, vmin=-1, vmax=1, cmap='seismic', levels=3)
                plt.contour(-1 * mask_1, vmin=-1, vmax=1, cmap='seismic', levels=3)

                plt.arrow(100, 100, x, y, head_width=15)

                plt.colorbar()

            if num_points < size_threshold:
                x_lag[row, col] = np.nan
                y_lag[row, col] = np.nan
                continue

            y_lag[row, col] = y
            x_lag[row, col] = x

    mag_movement, mag_dir, mag_movement_mps = offset_to_speed(x_lag, y_lag, 15 * 60)

    x_lag[mag_movement_mps > 60] = np.nan
    y_lag[mag_movement_mps > 60] = np.nan

    x_lag[np.isnan(x_lag)] = np.nanmedian(0)
    y_lag[np.isnan(y_lag)] = np.nanmedian(0)
    return y_lag[0,0], x_lag[0,0]


def get_basetime(filename):
    """ Get basetime from file"""

    filedate, filetime = os.path.basename(filename).split('_')[2].split('.')[2:4]
    # print(filedate, filetime)
    basetime = datetime.datetime(
        year=int(filedate[0:4]),
        month=int(filedate[4:6]),
        day=int(filedate[6:]),
        hour=int(filetime[0:2]),
        minute=int(filetime[2:4]),
        second=int(filetime[4:6]),
        tzinfo=datetime.timezone.utc,
    )
    return int(basetime.timestamp()), str(basetime)

def movement_of_storm_fft_l(filenames):
    """ This just exists to make parallelism easier"""
    dset_1 = xr.open_dataset(filenames[0])
    dset_2 = xr.open_dataset(filenames[1])

    y1, x1 = movement_of_storm_fft(dset_1, dset_2, threshold=DBZ_THRESHOLD)
    return y1, x1


if __name__ == "__main__":
    output_path_name = "../../csapr2_500m_advection_full_campaign_20dbz.nc"
    filelist = sorted(
        glob.glob(
            '/home/josephhardinee/data/proj-shared/iclass/cacti/radar_processing/taranis_corcsapr2cfrppiqcM1_gridded_convmask.c1/*.nc'
        )
    )
    print(f'Found {len(filelist)} files.')
    x = np.zeros((len(filelist), 1))
    y = np.zeros((len(filelist), 1))
    # for test_file_idx in np.arange(0, len(filelist) - 1):
    #     filename_1 = filelist[test_file_idx]
    #     filename_2 = filelist[test_file_idx + 1]

    #     dset_1 = xr.open_dataset(filename_1)
    #     dset_2 = xr.open_dataset(filename_2)

    #     y1, x1 = movement_of_storm_fft(dset_1, dset_2, threshold=10)
    #     x[test_file_idx, :] = x1.ravel()
    #     y[test_file_idx, :] = y1.ravel()
    # import pdb; pdb.set_trace()

    results = list(Parallel(n_jobs=NJOBS)(delayed(movement_of_storm_fft_l)(i ) for i in zip(filelist[:-1], filelist[1:])))
    x_and_y = np.array(tuple(zip(*results)))
    y = x_and_y[0]
    x = x_and_y[1]

    mag = np.sqrt((x * dx) ** 2 + (y * dy) ** 2)
    mag_mps = 1000 / (60 * 15) * mag

    angle = 90 - np.arctan2(y, x) * 180 / np.pi
    mag_med = medfilt(np.squeeze(mag), MED_FILT_LEN)
    mag_mps_med = medfilt(np.squeeze(mag_mps), MED_FILT_LEN)
    angle_med = medfilt(np.squeeze(angle), MED_FILT_LEN)

    med_x = (1 / dx) * mag_med * np.cos(np.pi / 180 * (90 - angle_med))
    med_y = (1 / dy) * mag_med * np.sin(np.pi / 180 * (90 - angle_med))

    corrections = zip(map(get_basetime, filelist), zip(med_x, med_y, mag_med, angle_med))
    corrections = list(corrections)
    basetime = np.array([t[0][0] for t in corrections])
    basedate = [t[0][1] for t in corrections]

    rootgrp = Dataset(
        output_path_name, "w", format="NETCDF4"
    )
    d_time = rootgrp.createDimension("time", len(corrections))
    v_basetime = rootgrp.createVariable("basetime", "i8", ("time",))
    v_x = rootgrp.createVariable("x", "f8", ("time",))
    v_y = rootgrp.createVariable("y", "f8", ("time",))
    v_mag = rootgrp.createVariable("magnitude", "f8", ("time",))
    v_dir = rootgrp.createVariable("direction", "f8", ("time",))

    v_basetime[:] = [t[0][0] for t in corrections]
    v_basetime.units = 'Seconds since 1970-1-1 0:00:00 0:00'
    v_x[:] = [np.round(t[1][0]) for t in corrections]
    v_y[:] = [np.round(t[1][1]) for t in corrections]
    v_mag[:] = [t[1][2] for t in corrections]
    v_dir[:] = [t[1][3] for t in corrections]

    rootgrp.dbz_threshold=DBZ_THRESHOLD
    rootgrp.close()
