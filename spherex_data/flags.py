"""Summarise the FLAGS extension of a SPHEREx cutout.

FLAGS is a per-pixel bitmask. SPHEREx files name each bit in the FLAGS header:
    MSKN0021 = 'SOURCE'                              (name of bit 21)
    MSKD0021 = 'Pixel mapped to a known source'      (what it means)
We read those cards, so new bits in future data releases are picked up
automatically. FALLBACK_BITS (copied from a real file's header) is only used if a
header is missing.

Not every bit means "bad pixel". SOURCE marks pixels on a catalogued star, and
FULLSAMPLE says extra data exists; neither is a problem, so INFO_BITS are left
out of `flagged_fraction` and `bad_mask`.
"""
from __future__ import annotations

import re

import numpy as np

# bit: (name, description), from the FLAGS header of a SPHEREx L2 image.
FALLBACK_BITS: dict[int, tuple[str, str]] = {
    0: ("TRANSIENT", "Transient detected during SUR"),
    1: ("OVERFLOW", "Overflow detected during SUR"),
    2: ("SUR_ERROR", "Error in onboard processing"),
    6: ("NONFUNC", "Permanently unusable"),
    7: ("DICHROIC", "Low efficiency due to dichroic"),
    9: ("MISSING_DATA", "Onboard data lost"),
    10: ("HOT", "Hot pixel"),
    11: ("COLD", "Anomalously low signal"),
    12: ("FULLSAMPLE", "Pixel full sample history is available"),
    14: ("PHANMISS", "Phantom correction was not applied"),
    15: ("NONLINEAR", "Nonlinearity correction cannot be applied reliably"),
    17: ("PERSIST", "Persistent charge above threshold"),
    19: ("OUTLIER", "Pixel flagged by Detect Outliers"),
    20: ("CROSSTALK", "Pixel affected by crosstalk."),
    21: ("SOURCE", "Pixel mapped to a known source"),
    22: ("GHOST", "Affected by a bright source inside the exposure"),
    23: ("GHOST_FPA", "Affected by a bright source on another detector"),
    24: ("GHOST_EXT", "Pixel affected by a bright source outside FOV"),
    25: ("STREAK", "Pixel affected by a streak"),
    26: ("BLOOM", "Pixel part of a bloom artifact"),
    27: ("SNOWBALL", "Pixel part of a snowball artifact"),
    28: ("HALO", "Pixel part of a transient halo"),
}

# Bits that describe a pixel rather than say something is wrong with it.
INFO_BITS = {"SOURCE", "FULLSAMPLE"}


def bit_names(header=None) -> dict[int, tuple[str, str]]:
    """{bit: (name, description)} from MSKNnnnn / MSKDnnnn cards, else the fallback table."""
    names: dict[int, tuple[str, str]] = {}
    if header is not None:
        for key in header:
            m = re.fullmatch(r"MSKN(\d{4})", key)
            if m:
                b = int(m.group(1))
                name = str(header[key]).strip()
                desc = str(header.get(f"MSKD{b:04d}", "")).strip()
                names[b] = (name, desc)
    return names or dict(FALLBACK_BITS)


def _name(names, b):
    return names[b][0] if b in names else f"bit{b}"


def bad_mask(flags: np.ndarray, header=None, ignore: set[str] = INFO_BITS) -> np.ndarray:
    """True where a pixel has any flag other than the informational ones."""
    names = bit_names(header)
    skip = sum(1 << b for b, (n, _) in names.items() if n in ignore)
    return (np.asarray(flags).astype(np.int64) & ~skip) != 0


def summarize(flags: np.ndarray, header=None, center_px: tuple[int, int] | None = None,
              radius_px: int = 2) -> dict:
    """Return a small JSON-friendly summary for the frontend.

    flagged_fraction: share of pixels with a problem flag (INFO_BITS don't count).
    bits: {name: pixel count} for every bit that occurs, informational ones included.
    at_target: names of bits set within radius_px of the target pixel, if given.
    problems_at_target: the same, minus the informational bits.
    descriptions: {name: what it means} for the bits listed, for tooltips.
    """
    flags = np.asarray(flags).astype(np.int64)
    names = bit_names(header)
    bad = bad_mask(flags, header)
    out = {"flagged_fraction": float(bad.mean()) if flags.size else 0.0,
           "bits": {}, "at_target": [], "problems_at_target": [], "descriptions": {}}
    seen = 0
    for b in range(32):
        n = int(np.count_nonzero(flags & (1 << b)))
        if n:
            out["bits"][_name(names, b)] = n
            seen |= 1 << b
    if center_px is not None:
        x, y = center_px
        y0, y1 = max(0, y - radius_px), min(flags.shape[0], y + radius_px + 1)
        x0, x1 = max(0, x - radius_px), min(flags.shape[1], x + radius_px + 1)
        local = int(np.bitwise_or.reduce(flags[y0:y1, x0:x1], axis=None)) if y1 > y0 and x1 > x0 else 0
        out["at_target"] = [_name(names, b) for b in range(32) if local & (1 << b)]
        out["problems_at_target"] = [n for n in out["at_target"] if n not in INFO_BITS]
    out["descriptions"] = {names[b][0]: names[b][1] for b in range(32)
                           if seen & (1 << b) and b in names}
    return out
