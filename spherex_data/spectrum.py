"""A target's spectrum at each epoch, and its brightness change at matched wavelengths.

SPHEREx's filters change wavelength across each detector, so every image measures
the target at one wavelength. Collecting the target's brightness from every image
gives each epoch its own spectrum: points from 0.75 to 5 microns.

Stacking mixes those wavelengths, and a star's brightness depends on wavelength, so
comparing stacks between epochs can show a small change that isn't real. Here the
comparison is made fairly instead: the points are grouped into narrow wavelength
bins, and each epoch is compared with the average of all epochs bin by bin. Only
bins that two or more epochs both cover, with the target clearly detected, count.

    from spherex_data import spectrum
    s = spectrum.build("RW Aur")
    s["epochs"][1]["matched"]   # {"ratio": 1.28, "n_bins": 12, ...}: 28% brighter
"""
from __future__ import annotations

import warnings

import numpy as np
from astropy.time import Time

from . import epochs as epochmod
from . import flags as flagmod
from . import targets
from .core import Cutout, get_cutouts

PIX_SR = (6.2 / 206264.806) ** 2       # solid angle of one SPHEREx pixel, steradians
MJY_SR_TO_MJY = 1e6 * PIX_SR * 1e3     # MJy/sr summed over pixels -> mJy
AP_R = 2.0                              # aperture radius, SPHEREx pixels (12.4")
ANNULUS = (4.0, 7.0)                    # sky annulus, pixels
BINS_PER_E = 20                         # bin width = 1/20 in ln(wavelength): ~5%, about
                                        # half SPHEREx's spectral resolution
MIN_SNR = 5
MAX_IMAGES = 360                        # 60 per detector
SIZE_DEG = 0.1                          # same cutouts as the blink frames (cache hits)
SATURATION_BITS = {"OVERFLOW", "NONLINEAR"}


def _sat_bits() -> int:
    names = flagmod.bit_names(None)
    return sum(1 << b for b, (n, _) in names.items() if n in SATURATION_BITS)


def measure(c: Cutout, x: float, y: float) -> dict | None:
    """Aperture flux (mJy) at pixel (x, y), minus the local sky; None if off the image."""
    img = c.image.astype(np.float64)
    if c.zodi is not None and c.zodi.shape == img.shape:
        img = img - c.zodi
    ny, nx = img.shape
    if not (ANNULUS[1] <= x < nx - ANNULUS[1] and ANNULUS[1] <= y < ny - ANNULUS[1]):
        return None
    yy, xx = np.mgrid[:ny, :nx]
    r2 = (xx - x) ** 2 + (yy - y) ** 2
    ap = r2 <= AP_R ** 2
    ann = (r2 >= ANNULUS[0] ** 2) & (r2 <= ANNULUS[1] ** 2) & np.isfinite(img)
    if ann.sum() < 10:
        return None
    sky = float(np.median(img[ann]))
    vals = img[ap]
    # Saturated = pixels blanked (NaN): that light is lost, so the point is left out.
    # OVERFLOW/NONLINEAR without blanking = SPHEREx still measured the pixel from the
    # readings taken before it filled, so the point is kept but marked "flagged".
    saturated = bool((~np.isfinite(vals)).any())
    flagged = bool(((np.asarray(c.flags)[ap].astype(np.int64) & _sat_bits()) != 0).any())
    flux = float(np.nansum(vals - sky)) * MJY_SR_TO_MJY
    if c.variance is not None:
        var = c.variance.astype(np.float64)[ap]
        err = float(np.sqrt(np.nansum(np.where(var > 0, var, 0)))) * MJY_SR_TO_MJY
    else:
        err = float(1.4826 * np.median(np.abs(img[ann] - sky)) * np.sqrt(ap.sum())) * MJY_SR_TO_MJY
    return {"flux_mjy": flux, "err_mjy": err, "saturated": saturated, "flagged": flagged}


def bin_edges(lo: float = 0.74, hi: float = 5.02) -> np.ndarray:
    n = int(np.ceil(np.log(hi / lo) * BINS_PER_E))
    return lo * np.exp(np.arange(n + 1) / BINS_PER_E)


def matched_comparison(points: list[dict], epoch_ids: list[int]) -> tuple[dict, list[dict]]:
    """Each epoch vs the average of all epochs, wavelength bin by wavelength bin.

    Returns ({epoch: summary}, [per-bin rows]). A bin counts when 2+ epochs cover it
    with unsaturated points and the target is detected there at S/N >= MIN_SNR.
    """
    edges = bin_edges()
    good = [p for p in points if not p["saturated"] and p["wavelength_um"]]
    rows = []
    for i in range(len(edges) - 1):
        lo, hi = edges[i], edges[i + 1]
        per = {}
        for e in epoch_ids:
            ps = [p for p in good if p["epoch"] == e and lo <= p["wavelength_um"] < hi]
            if ps:
                f = float(np.median([p["flux_mjy"] for p in ps]))
                err = float(np.median([p["err_mjy"] for p in ps])) / np.sqrt(len(ps))
                per[e] = (f, err, len(ps))
        if len(per) < 2:
            continue
        ref = float(np.median([v[0] for v in per.values()]))
        noise = float(np.median([v[1] for v in per.values()]))
        if ref <= 0 or ref < MIN_SNR * noise:
            continue
        rows.append({"lo_um": round(lo, 4), "hi_um": round(hi, 4), "mid_um": round(float(np.sqrt(lo * hi)), 4),
                     "ref_mjy": round(ref, 4),
                     "ratio": {str(e): round(v[0] / ref, 4) for e, v in per.items()}})
    summary = {}
    for e in epoch_ids:
        rs = [r["ratio"][str(e)] for r in rows if str(e) in r["ratio"]]
        if rs:
            summary[e] = {"ratio": round(float(np.median(rs)), 4),
                          "spread": round(float(np.percentile(rs, 84) - np.percentile(rs, 16)) / 2, 4),
                          "n_bins": len(rs),
                          "range_um": [min(r["lo_um"] for r in rows if str(e) in r["ratio"]),
                                       max(r["hi_um"] for r in rows if str(e) in r["ratio"])]}
    return summary, rows


def build(target, max_images: int = MAX_IMAGES) -> dict:
    """Measure the target in every SPHEREx image (all six detectors) and compare epochs."""
    tgt = targets.from_coords(*target) if isinstance(target, tuple) else targets.parse(target)
    cs = get_cutouts(target, size_deg=SIZE_DEG, detectors=None, max_images=max_images,
                     partial_ok=True)
    points = []
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for c in cs.cutouts:
            # Moving stars: measure where the star was on this image's date.
            pos = tgt.position_at(Time(c.mjd, format="mjd"))
            x, y = c.wcs.celestial.world_to_pixel_values(pos.ra.deg, pos.dec.deg)
            if not (np.isfinite(x) and np.isfinite(y)):
                continue
            m = measure(c, float(x), float(y))
            if m is None or c.wavelength_um is None:
                continue
            points.append({"epoch": c.epoch, "detector": c.detector, "mjd": round(c.mjd, 5),
                           "wavelength_um": round(c.wavelength_um, 4),
                           "flux_mjy": round(m["flux_mjy"], 4), "err_mjy": round(m["err_mjy"], 4),
                           "saturated": m["saturated"], "flagged": m["flagged"]})
    by = cs.by_epoch()
    epoch_ids = list(by)
    summary, rows = matched_comparison(points, epoch_ids)
    eps = []
    for e, g in by.items():
        mjds = sorted(c.mjd for c in g)
        eps.append({"epoch": e, "start": epochmod.mjd_to_iso(mjds[0]), "end": epochmod.mjd_to_iso(mjds[-1]),
                    "mid_year": round(epochmod.mjd_to_decimal_year(float(np.median(mjds))), 3),
                    "n_points": sum(1 for p in points if p["epoch"] == e),
                    "detectors": sorted({c.detector for c in g}),
                    "matched": summary.get(e)})
    dets = sorted({p["detector"] for p in points})
    return {
        "target": cs.target, "ra": round(cs.ra, 7), "dec": round(cs.dec, 7),
        "unit": "mJy", "aperture_arcsec": round(AP_R * 6.2, 1),
        "note": ("Aperture flux in a 12.4\" radius, sky subtracted, not corrected for light "
                 "outside the aperture. Hollow points are saturated (pixels blanked) and left out "
                 "of the comparison; flagged points were near saturation but still measured."),
        "detectors": dets, "partial": len(dets) < 6,
        "epochs": eps, "points": points, "bins": rows,
        "n_saturated": sum(p["saturated"] for p in points),
        "n_flagged": sum(p["flagged"] and not p["saturated"] for p in points),
    }
