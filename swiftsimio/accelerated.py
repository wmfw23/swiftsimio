"""
Functions that can be accelerated by numba. Numba does not use classes, unfortunately.
"""

import numpy as np

from h5py._hl.dataset import Dataset

from typing import Tuple
from numba.typed import List
from itertools import chain

try:
    from numba import jit, prange
    from numba.core.config import NUMBA_NUM_THREADS as NUM_THREADS
except ImportError:
    print(
        "You do not have numba installed. Please consider installing "
        "if you are going to be doing visualisation or indexing large arrays "
        "(pip install numba)"
    )

    def jit(*args, **kwargs):
        def x(func):
            return func

        return x

    prange = range
    NUM_THREADS = 1


@jit(nopython=True)
def ranges_from_array(array: np.array) -> np.ndarray:
    """
    Finds contiguous ranges of IDs in sorted list of IDs

    Parameters
    ----------
    array : np.array of int
        sorted list of IDs 

    Returns
    -------
    np.ndarray
        list of length two arrays corresponding to contiguous 
        ranges of IDs (inclusive) in the input array
    
    Examples
    --------
    The array

    [0, 1, 2, 3, 5, 6, 7, 9, 11, 12, 13]

    would return

    [[0, 4], [5, 8], [9, 10], [11, 14]]

    """

    output = []

    start = array[0]
    stop = array[0]

    for value in array[1:]:
        if value != stop + 1:
            output.append([start, stop + 1])

            start = value
            stop = value
        else:
            stop = value

    output.append([start, stop + 1])

    return np.array(output)


def read_ranges_from_file(
    handle: Dataset,
    ranges: np.ndarray,
    output_shape: Tuple,
    output_type: type = np.float64,
    columns: np.lib.index_tricks.IndexExpression = np.s_[:],
) -> np.array:
    """
    Takes a hdf5 dataset, and the set of ranges from
    ranges_from_array, and reads only those ranges from the file.

    Unfortunately this functionality is not built into HDF5.

    Parameters
    ----------

    handle: Dataset
        HDF5 dataset to slice data from

    ranges: np.ndarray
        Array of ranges (see :func:`ranges_from_array`)

    output_shape: Tuple
        Resultant shape of output. 
    
    output_type: type, optional
        ``numpy`` type of output elements. If not supplied, we assume ``np.float64``.

    columns: np.lib.index_tricks.IndexExpression, optional
        Selector for columns if using a multi-dimensional array. If the array is only
        a single dimension this is not used.

    
    Returns
    -------

    array: np.ndarray
        Result from reading only the relevant values from ``handle``.
    """

    output = np.empty(output_shape, dtype=output_type)
    already_read = 0
    handle_multidim = handle.ndim > 1

    for (read_start, read_end) in ranges:
        if read_end == read_start:
            continue

        # Because we read inclusively
        size_of_range = read_end - read_start

        # Construct selectors so we can use read_direct to prevent creating
        # copies of data from the hdf5 file.
        hdf5_read_sel = (
            np.s_[read_start:read_end, columns]
            if handle_multidim
            else np.s_[read_start:read_end]
        )

        output_dest_sel = np.s_[already_read : size_of_range + already_read]

        handle.read_direct(output, source_sel=hdf5_read_sel, dest_sel=output_dest_sel)

        already_read += size_of_range

    return output


def index_dataset(handle: Dataset, mask_array: np.array) -> np.array:
    """
    Indexes the dataset using the mask array.

    This is not currently a feature of h5py. (March 2019)

    Parameters
    ----------
    handle : Dataset
        data to be indexed
    mask_array : np.array
        mask used to index data

    Returns
    -------
    np.array
        Subset of the data specified by the mask
    """

    output_type = handle[0].dtype
    output_size = mask_array.size

    ranges = ranges_from_array(mask_array)

    return read_ranges_from_file(handle, ranges, output_size, output_type)


################################ ALEXEI: playing around with better read_ranges_from_file implementation #################################


@jit(nopython=True, fastmath=True)
def get_chunk_ranges(ranges, chunk_size, array_length):
    chunk_ranges = List()
    n_ranges = len(ranges) // 2
    for i in range(n_ranges):
        lower = (ranges[2 * i] // chunk_size) * chunk_size
        upper = min(-((-ranges[2 * i + 1]) // chunk_size) * chunk_size, array_length)

        # Before appending new chunk range we need to check
        # that it doesn't already exist or overlap with an
        # existing one. The only way overlap can happen is
        # if the current lower index is less than or equal
        # to the previous upper one. In that case simply
        # update the previous upper to cover current chunk
        if len(chunk_ranges) > 0:
            if lower > chunk_ranges[-1]:
                chunk_ranges.extend((lower, upper))
            elif lower <= chunk_ranges[-1]:
                chunk_ranges[-1] = upper
        # If chunk_ranges is empty, don't do any checks
        else:
            chunk_ranges.extend((lower, upper))

    return chunk_ranges


@jit(nopython=True, fastmath=True)
def expand_ranges(ranges: List):
    n_ranges = len(ranges) // 2
    length = np.asarray(
        [ranges[2 * i + 1] - ranges[2 * i] for i in range(n_ranges)]
    ).sum()

    output = np.zeros(length, dtype=np.int64)
    i = 0
    for k in range(n_ranges):
        lower = ranges[2 * k]
        upper = ranges[2 * k + 1]
        bound_length = upper - lower
        output[i : i + bound_length] = np.arange(lower, upper, dtype=np.int64)
        i += bound_length

    return output


@jit(nopython=True, fastmath=True)
def extract_ranges_from_chunks(array, chunks, ranges):
    # Find out which of the chunks in the chunks array each range in ranges belongs to
    n_ranges = len(ranges) // 2
    chunk_array_index = np.zeros(len(ranges), dtype=np.int32)
    chunk_index = 0
    i = 0
    while i < n_ranges:
        if (
            chunks[chunk_index] <= ranges[2 * i]
            and chunks[chunk_index + 1] >= ranges[2 * i + 1]
        ):
            chunk_array_index[2 * i] = chunk_index
            i += 1
        else:
            chunk_index += 2

    # Need to get the locations of the range boundaries with
    # respect to the indexing in the array of chunked data
    # (as opposed to the whole dataset)
    adjusted_ranges = ranges
    running_sum = 0
    for i in range(n_ranges):
        offset = chunks[2 * chunk_array_index[i]] - running_sum
        adjusted_ranges[2 * i] = ranges[2 * i] - offset
        adjusted_ranges[2 * i + 1] = ranges[2 * i + 1] - offset
        if i < n_ranges:
            if chunk_array_index[i + 1] > chunk_array_index[i]:
                running_sum += (
                    chunks[2 * chunk_array_index[i] + 1]
                    - chunks[2 * chunk_array_index[i]]
                )

    return array[expand_ranges(adjusted_ranges)]


def new_read_ranges_from_file(
    handle: Dataset,
    ranges: np.ndarray,
    output_shape: Tuple,
    output_type: type = np.float64,
    columns: np.lib.index_tricks.IndexExpression = np.s_[:],
) -> np.array:
    """
    Takes a hdf5 dataset, and the set of ranges from
    ranges_from_array, and reads only those ranges from the file.

    Unfortunately this functionality is not built into HDF5.

    Parameters
    ----------

    handle: Dataset
        HDF5 dataset to slice data from

    ranges: np.ndarray
        Array of ranges (see :func:`ranges_from_array`)

    output_shape: Tuple
        Resultant shape of output. 
    
    output_type: type, optional
        ``numpy`` type of output elements. If not supplied, we assume ``np.float64``.

    columns: np.lib.index_tricks.IndexExpression, optional
        Selector for columns if using a multi-dimensional array. If the array is only
        a single dimension this is not used.

    
    Returns
    -------

    array: np.ndarray
        Result from reading only the relevant values from ``handle``.
    """

    # Get chunk size
    ranges_list = List(chain.from_iterable(ranges))
    chunk_ranges = get_chunk_ranges(ranges_list, handle.chunks[0], handle.size)
    n_chunk_ranges = len(chunk_ranges) // 2
    chunk_size = np.sum(
        [chunk_ranges[2 * i + 1] - chunk_ranges[2 * i] for i in range(n_chunk_ranges)]
    )
    shape = output_shape
    if isinstance(output_shape, tuple):
        shape[0] = chunk_size
    else:
        shape = chunk_size

    output = np.empty(shape, dtype=output_type)
    already_read = 0
    handle_multidim = handle.ndim > 1

    for i in range(n_chunk_ranges):
        read_start = chunk_ranges[2 * i]
        read_end = chunk_ranges[2 * i + 1]
        if read_end == read_start:
            continue

        # Because we read inclusively
        size_of_range = read_end - read_start

        # Construct selectors so we can use read_direct to prevent creating
        # copies of data from the hdf5 file.
        hdf5_read_sel = (
            np.s_[read_start:read_end, columns]
            if handle_multidim
            else np.s_[read_start:read_end]
        )

        output_dest_sel = np.s_[already_read : size_of_range + already_read]

        handle.read_direct(output, source_sel=hdf5_read_sel, dest_sel=output_dest_sel)

        already_read += size_of_range

    return extract_ranges_from_chunks(output, chunk_ranges, ranges_list)
