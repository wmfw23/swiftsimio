"""
Projection kernels.
"""

from typing import Union
from math import sqrt
from numpy import float64, float32, int32

from swiftsimio.accelerated import jit, NUM_THREADS, prange

# Taken from Dehnen & Aly 2012
kernel_gamma = float32(1.897367)
kernel_constant = float32(7.0 / 3.14159)


@jit("float32(float32, float32)", nopython=True, fastmath=True)
def kernel_single_precision(r: float32, H: float32):
    """
    Kernel implementation for swiftsimio. This is the Wendland-C2
    kernel as shown in Denhen & Aly (2012).

    Give it a radius and a kernel width (i.e. not a smoothing length, but the
    radius of compact support) and it returns the contribution to the
    density.
    """
    # ALEXEI: add param, return, examples docs
    kernel_constant = float32(2.22817109)

    inverse_H = 1.0 / H
    ratio = r * inverse_H

    kernel = 0.0

    if ratio < 1.0:
        one_minus_ratio = 1.0 - ratio
        one_minus_ratio_2 = one_minus_ratio * one_minus_ratio
        one_minus_ratio_4 = one_minus_ratio_2 * one_minus_ratio_2

        kernel = max(one_minus_ratio_4 * (1.0 + 4.0 * ratio), 0.0)

        kernel *= kernel_constant * inverse_H * inverse_H

    return kernel


@jit("float64(float64, float64)", nopython=True, fastmath=True)
def kernel_double_precision(r: float64, H: float64):
    """
    Kernel implementation for swiftsimio. This is the Wendland-C2
    kernel as shown in Denhen & Aly (2012).

    Give it a radius and a kernel width (i.e. not a smoothing length, but the
    radius of compact support) and it returns the contribution to the
    density.
    """
    # ALEXEI: add param, return, examples docs
    kernel_constant = float64(2.22817109)

    inverse_H = 1.0 / H
    ratio = r * inverse_H

    kernel = 0.0

    if ratio < 1.0:
        one_minus_ratio = 1.0 - ratio
        one_minus_ratio_2 = one_minus_ratio * one_minus_ratio
        one_minus_ratio_4 = one_minus_ratio_2 * one_minus_ratio_2

        kernel = max(one_minus_ratio_4 * (1.0 + 4.0 * ratio), 0.0)

        kernel *= kernel_constant * inverse_H * inverse_H

    return kernel
