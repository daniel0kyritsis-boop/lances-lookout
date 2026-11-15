"""Choose the best SPHEREx detector for a target automatically.

"Best" = the band where the target stands out most above the noise without its
core saturating:

1. Download a few small cutouts per detector (3 each, spread across time).
2. In each, measure the target's peak above the sky in units of the noise (S/N),
   and whether its core is saturated (SPHEREx blanks saturated pixels to NaN and
   flags overflow/non-linearity).
3. Among detectors where the core is not saturated in most samples, take the one
   with the highest median S/N. If the target is faint even there (S/N < 20), add
   the other unsaturated detectors where it reaches at least half that S/N, so the
   stack has more light (this is how WISE 0855 ends up on detectors 5+6).
4. If it saturates in every band, take the band with the smallest saturated core,
   which is usually the one where it is faintest.

    from spherex_data.best import choose_detectors
    choose_detectors("Sirius")   # {"detectors": [4], "reason": "...", "per_detector": {...}}
"""
from __future__ import annotations

import warnings

import numpy as np

from . import flags as flagmod
from .core import Cutout, get_cutouts

SAMPLE_PER_DETECTOR = 3
SAMPLE_SIZE_DEG = 0.04        # ~23 SPHEREx pixels across: enough sky to measure the noise
CORE_R = 2                    # pixels around the predicted position (covers ~1 yr of fast motion)
FAINT_SNR = 20
SATURATION_BITS = {"OVERFLOW", "NONLINEAR"}


def _saturation_mask(c: Cutout) -> np.ndarray:
    names = flagmod.bit_names(None)
    bits = sum(1 << b for b, (n, _) in names.items() if n in SATURATION_BITS)
    return ~np.isfinite(c.image) | ((np.asarray(c.flags).astype(np.int64) & bits) != 0)


def measure(c: Cutout) -> dict | None:
    """Target S/N and saturation in one cutout; None if the target is off the cutout."""
    if c.target_px is None:
        return None
    x, y = c.target_px
    img = c.image.astype(np.float64)
    if c.zodi is not None and c.zodi.shape == img.shape:
        img = img - c.zodi
    ny, nx = img.shape
    yy, xx = np.mgrid[:ny, :nx]
    r2 = (yy - y) ** 2 + (xx - x) ** 2
    core = r2 <= CORE_R ** 2
    sky_px = img[(r2 > (3 * CORE_R) ** 2) & np.isfinite(img)]
    if sky_px.size < 20:
        return None
    sky = float(np.median(sky_px))
    noise = 1.4826 * float(np.median(np.abs(sky_px - sky))) or 1e-9
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        peak = float(np.nanmax(np.where(core, img, np.nan)))
    sat = _saturation_mask(c) & core
    return {"snr": (peak - sky) / noise if np.isfinite(peak) else float("nan"),
            "saturated": bool(sat.any()), "saturated_px": int(sat.sum()),
            "wavelength_um": c.wavelength_um}


def score(cutouts: list[Cutout]) -> dict[int, dict]:
    """Per detector: median S/N, fraction of samples saturated, median saturated pixels."""
    out = {}
    for d in sorted({c.detector for c in cutouts}):
        ms = [m for c in cutouts if c.detector == d and (m := measure(c))]
        if not ms:
            continue
        snrs = [m["snr"] for m in ms if np.isfinite(m["snr"])]
        wls = [m["wavelength_um"] for m in ms if m["wavelength_um"]]
        out[d] = {
            "snr": round(float(np.median(snrs)), 1) if snrs else 0.0,
            "saturated_frac": round(sum(m["saturated"] for m in ms) / len(ms), 2),
            "saturated_px": int(np.median([m["saturated_px"] for m in ms])),
            "n_samples": len(ms),
            "wavelength_um": round(float(np.median(wls)), 2) if wls else None,
        }
    return out


def decide(per: dict[int, dict]) -> tuple[list[int], str]:
    """The rule described in the module docstring, on the per-detector scores."""
    if not per:
        return [2], "no usable samples; using detector 2"
    clean = {d: s for d, s in per.items() if s["saturated_frac"] < 0.5}
    if clean:
        best = max(clean, key=lambda d: clean[d]["snr"])
        top = clean[best]["snr"]
        if top < FAINT_SNR:
            extra = sorted(d for d, s in clean.items() if d != best and s["snr"] >= max(top / 2, 3))
            chosen = sorted([best, *extra])
            if len(chosen) > 1:
                return chosen, (f"faint everywhere (best S/N {top:.0f} on D{best}); "
                                f"combining the bands where it is detected")
            return chosen, f"faint everywhere; strongest on D{best} (S/N {top:.0f})"
        return [best], f"brightest band without saturating (S/N {top:.0f})"
    # Saturated everywhere: smallest saturated core, then the longest wavelength.
    best = min(per, key=lambda d: (per[d]["saturated_px"], -d))
    return [best], f"saturated in every band; least saturated on D{best}"


def choose_detectors(target, sample_per_detector: int = SAMPLE_PER_DETECTOR,
                     size_deg: float = SAMPLE_SIZE_DEG) -> dict:
    cs = get_cutouts(target, size_deg=size_deg, detectors=None,
                     sample_per_detector=sample_per_detector)
    per = score(cs.cutouts)
    dets, reason = decide(per)
    return {"detectors": dets, "reason": reason, "per_detector": per, "method": "auto"}


def remembered_choice(name: str, auto_dir, lock=None) -> dict:
    """choose_detectors(name), worked out once and kept as <auto_dir>/<target>.json.

    If the archive can't be reached, falls back to detector 2 without remembering,
    so a later request tries again.
    """
    import contextlib
    import json
    import logging
    from pathlib import Path

    from .frames import DEFAULT_DETECTORS, folder_name

    path = Path(auto_dir) / (folder_name(name, DEFAULT_DETECTORS, None) + ".json")
    if path.exists():
        return json.loads(path.read_text())
    with lock or contextlib.nullcontext():
        if path.exists():
            return json.loads(path.read_text())
        try:
            choice = choose_detectors(name)
        except Exception as e:
            logging.getLogger("uvicorn.error").warning("auto detector choice for %s failed: %s", name, e)
            return {"detectors": list(DEFAULT_DETECTORS), "method": "fallback",
                    "reason": "couldn't compare detectors right now (archive unavailable); using detector 2"}
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(choice, indent=1))
        return choice
