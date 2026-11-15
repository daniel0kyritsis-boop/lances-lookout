"""Spectrum measurement and the matched-wavelength comparison (spherex_data/spectrum.py)."""
import numpy as np
from astropy.wcs import WCS

from spherex_data import spectrum
from spherex_data.core import Cutout


def _cutout(peak, nan_core=False):
    ny = nx = 31
    yy, xx = np.mgrid[:ny, :nx]
    img = (0.5 + peak * np.exp(-((xx - 15) ** 2 + (yy - 15) ** 2) / (2 * 0.8 ** 2))).astype(np.float32)
    if nan_core:
        img[15, 15] = np.nan
    return Cutout(url="", mjd=60000.0, detector=2, epoch=0, image=img,
                  flags=np.zeros((ny, nx), np.int32), variance=np.full((ny, nx), 1e-4, np.float32),
                  zodi=None, header=None, wcs=WCS(naxis=2), target_px=(15, 15), wavelength_um=1.3, version=None)


def test_measure_scales_with_brightness_and_ignores_sky():
    a = spectrum.measure(_cutout(1.0), 15, 15)
    b = spectrum.measure(_cutout(2.0), 15, 15)
    assert a["flux_mjy"] > 0 and not a["saturated"]
    assert abs(b["flux_mjy"] / a["flux_mjy"] - 2) < 0.01        # the 0.5 sky level cancels


def test_blank_core_counts_as_saturated():
    assert spectrum.measure(_cutout(1.0, nan_core=True), 15, 15)["saturated"]


def _points(epoch, scale, wls):
    # A red-ish spectrum: brighter at longer wavelengths, so mixing wavelengths would mislead.
    return [{"epoch": epoch, "wavelength_um": w, "flux_mjy": scale * 10 * w, "err_mjy": 0.1,
             "saturated": False} for w in wls]


def test_matched_comparison_finds_real_change_not_wavelength_mix():
    # Epoch 0 sampled short wavelengths, epoch 1 long ones: a naive average says epoch 1
    # is brighter. Matched bins (where both have points) say they are the same...
    w0 = [1.10, 1.15, 1.20, 1.30, 1.40]
    w1 = [1.20, 1.30, 1.40, 1.50, 1.60]
    summary, rows = spectrum.matched_comparison(_points(0, 1.0, w0) + _points(1, 1.0, w1), [0, 1])
    assert summary[0]["ratio"] == summary[1]["ratio"] == 1.0
    # ... and a real 30% brightening shows as one.
    summary, _ = spectrum.matched_comparison(_points(0, 1.0, w0) + _points(1, 1.3, w1), [0, 1])
    assert summary[1]["ratio"] / summary[0]["ratio"] > 1.25


def test_saturated_points_are_left_out():
    pts = _points(0, 1.0, [1.2, 1.3]) + _points(1, 1.0, [1.2, 1.3])
    for p in pts:
        p["saturated"] = True
    summary, rows = spectrum.matched_comparison(pts, [0, 1])
    assert summary == {} and rows == []
