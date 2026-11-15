"""Turn a CutoutSet into one aligned, stacked image per epoch (the blink frames).

For each cutout: subtract the zodiacal-light model, blank broken pixels, reproject
onto one shared north-up grid, and subtract the leftover sky level. Then the
cutouts of each epoch are median-stacked. Every epoch uses the same grid and the
same brightness scale, so in a blink anything that moves or changes stands out.

    from spherex_data import get_cutouts, frames
    cs = get_cutouts("Barnard's Star", detectors=[2])
    stacks = frames.stack_epochs(cs)
    frames.write(stacks, "frames/barnards-star")   # PNGs, FITS, JSON, GIF
"""
from __future__ import annotations

import json
import re
import warnings
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from astropy.io import fits
from astropy.time import Time
from astropy.wcs import WCS
from reproject import reproject_interp

from . import epochs as epochmod
from . import flags as flagmod
from .core import CutoutSet

PIX_ARCSEC = 6.2   # native SPHEREx pixel

# Pixels with these flags hold no usable signal, so they are blanked before stacking.
# Saturation-type flags (OVERFLOW, BLOOM, TRANSIENT...) sit on every bright star's core;
# blanking them would punch a hole in the star, so they are left in.
BROKEN_BITS = {"NONFUNC", "MISSING_DATA", "HOT", "COLD", "OUTLIER"}


@dataclass
class EpochStack:
    epoch: int
    image: np.ndarray          # MJy/sr above the local sky, on the common grid
    n_frames: int
    mjd_start: float
    mjd_mid: float
    mjd_end: float
    detectors: list[int]
    wavelength_um: tuple[float, float] | None   # range covered at the target pixel
    n_saturated: int = 0       # pixels filled in by fill_saturated (display only)


@dataclass
class StackSet:
    target: str
    ra: float
    dec: float
    fov_deg: float
    wcs: WCS
    epochs: list[EpochStack]


DEFAULT_DETECTORS = [2]
DEFAULT_FOV_DEG = 0.1


def folder_name(target: str, detectors: list[int] | None, fov_deg: float | None) -> str:
    """Folder for one target + settings, shared by make_frames.py and the API so they reuse each other's work.

    "Barnard's Star", [2], 0.1  -> "barnards-star"
    "WISE ...", [5, 6], 0.1     -> "wise-...-d5-6"
    "R Dra", None, 0.2          -> "r-dra_dall_fov0.2"
    """
    name = re.sub(r"[^a-z0-9]+", "-", target.lower().replace("'", "")).strip("-")
    if detectors != DEFAULT_DETECTORS:
        name += "_d" + ("-".join(map(str, sorted(detectors))) if detectors else "all")
    if fov_deg is not None and abs(fov_deg - DEFAULT_FOV_DEG) > 1e-9:
        name += f"_fov{fov_deg:g}"
    return name


def common_grid(ra: float, dec: float, fov_deg: float, oversample: int = 2) -> tuple[WCS, tuple[int, int]]:
    """North-up TAN grid centred on (ra, dec), `oversample` pixels per SPHEREx pixel."""
    scale = PIX_ARCSEC / oversample / 3600
    n = int(round(fov_deg / scale)) | 1          # odd, so the target sits on a pixel centre
    w = WCS(naxis=2)
    w.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    w.wcs.crval = [ra, dec]
    w.wcs.crpix = [(n + 1) / 2, (n + 1) / 2]
    w.wcs.cdelt = [-scale, scale]
    w.wcs.radesys = "ICRS"
    return w, (n, n)


def _broken(flags: np.ndarray) -> np.ndarray:
    names = flagmod.bit_names(None)
    bits = sum(1 << b for b, (n, _) in names.items() if n in BROKEN_BITS)
    return (np.asarray(flags).astype(np.int64) & bits) != 0


def reproject_cutout(c, wcs: WCS, shape, mask_broken: bool = True) -> np.ndarray:
    """One cutout on the common grid, zodi and sky removed. NaN where it has no data."""
    img = c.image.astype(np.float64)
    if c.zodi is not None and c.zodi.shape == img.shape:
        img = img - c.zodi
    if mask_broken:
        img = np.where(_broken(c.flags), np.nan, img)
    out, _ = reproject_interp((img, c.wcs.celestial), wcs, shape_out=shape)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        sky = np.nanmedian(out)
    return out - sky if np.isfinite(sky) else out


def fill_saturated(img: np.ndarray, max_px: int = 400) -> tuple[np.ndarray, int]:
    """Fill small NaN holes enclosed by data with their brightest neighbour.

    SPHEREx sets saturated pixels to NaN, so a bright star's core is a hole in
    every frame and shows black. Holes touching the edge (no coverage) are kept.
    Returns the filled image and how many pixels were filled.
    """
    from scipy import ndimage

    holes = ~np.isfinite(img)
    if not holes.any():
        return img, 0
    lab, n = ndimage.label(holes)
    edge = set(np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]])))
    sizes = ndimage.sum(holes, lab, range(1, n + 1))
    fill = np.isin(lab, [i for i in range(1, n + 1) if i not in edge and sizes[i - 1] <= max_px])
    out = img.copy()
    todo = fill.copy()
    while todo.any():
        grown = ndimage.grey_dilation(np.where(np.isfinite(out), out, -np.inf), size=3)
        ok = todo & np.isfinite(grown)
        if not ok.any():
            break
        out[ok] = grown[ok]
        todo &= ~ok
    return out, int(fill.sum())


def _median(stack):
    with warnings.catch_warnings():            # pixels no frame covers stay NaN
        warnings.simplefilter("ignore", RuntimeWarning)
        return np.nanmedian(stack, axis=0)


def stack_epochs(cs: CutoutSet, fov_deg: float | None = None, detector: int | None = None,
                 oversample: int = 2) -> StackSet:
    """Median-stack each epoch's cutouts on one grid centred on the target."""
    fov = min(fov_deg or cs.size_deg, cs.size_deg)
    wcs, shape = common_grid(cs.ra, cs.dec, fov, oversample)
    out = []
    for e, group in cs.by_epoch(detector).items():
        masked = _median([reproject_cutout(c, wcs, shape, True) for c in group])
        # Where every frame was blanked, fall back to the unmasked data rather than a hole.
        if np.isnan(masked).any():
            raw = _median([reproject_cutout(c, wcs, shape, False) for c in group])
            masked = np.where(np.isnan(masked), raw, masked)
        masked, n_sat = fill_saturated(masked)
        mjds = sorted(c.mjd for c in group)
        wls = [c.wavelength_um for c in group if c.wavelength_um is not None]
        out.append(EpochStack(
            epoch=e, image=masked.astype(np.float32), n_frames=len(group),
            mjd_start=mjds[0], mjd_mid=float(np.median(mjds)), mjd_end=mjds[-1],
            detectors=sorted({c.detector for c in group}), n_saturated=n_sat,
            wavelength_um=(round(min(wls), 3), round(max(wls), 3)) if wls else None))
    return StackSet(cs.target, cs.ra, cs.dec, fov, wcs, out)


def display_range(ss: StackSet, lo: float = 1.0, hi: float = 99.9) -> tuple[float, float]:
    """One brightness range shared by every epoch, so brightness changes are real."""
    vals = np.concatenate([s.image[np.isfinite(s.image)] for s in ss.epochs])
    return float(np.percentile(vals, lo)), float(np.percentile(vals, hi))


def to_uint8(img: np.ndarray, vmin: float, vmax: float, softening: float = 0.02) -> np.ndarray:
    """Asinh stretch to 0-255 (faint detail visible without burning out bright stars)."""
    x = np.clip((np.nan_to_num(img, nan=vmin) - vmin) / (vmax - vmin), 0, 1)
    y = np.arcsinh(x / softening) / np.arcsinh(1 / softening)
    return (y * 255).astype(np.uint8)[::-1]      # flip: FITS row 0 is the bottom


def residuals(ss: StackSet) -> dict[int, np.ndarray]:
    """Each epoch minus the median of all epochs.

    Anything constant cancels, so blinking these shows only what moved or changed.
    With 3+ epochs the median doesn't contain a mover, so it shows up bright where
    it is in that epoch; with 2 epochs the median is the mean and each frame shows
    half of the pair.
    """
    ref = _median([s.image for s in ss.epochs])
    return {s.epoch: (s.image - ref).astype(np.float32) for s in ss.epochs}


def pair(ss: StackSet, a: int | None = None, b: int | None = None) -> np.ndarray:
    """Epoch b minus epoch a (default: last minus first). A mover = dark/bright pair."""
    by = {s.epoch: s for s in ss.epochs}
    a = min(by) if a is None else a
    b = max(by) if b is None else b
    return (by[b].image - by[a].image).astype(np.float32)


def diff_limit(images, pct: float = 99.5, min_sigma: float = 10.0) -> float:
    """One symmetric +/- range for a set of difference images.

    At least `min_sigma` times the noise, so a faint field isn't stretched until
    the noise fills the frame.
    """
    vals = np.concatenate([d[np.isfinite(d)] for d in images])
    if not vals.size:
        return 1.0
    noise = 1.4826 * float(np.median(np.abs(vals - np.median(vals))))   # robust sigma
    lim = max(float(np.percentile(np.abs(vals), pct)), min_sigma * noise)
    return lim if lim > 0 else 1.0


def to_uint8_signed(img: np.ndarray, lim: float) -> np.ndarray:
    """Linear stretch of a difference image: mid-grey = no change, white = brighter, black = fainter.

    Linear, not asinh: asinh lifts the noise until a faint field looks like static.
    """
    x = np.clip(np.nan_to_num(img, nan=0.0) / lim, -1, 1)
    return np.round((x + 1) * 127.5).astype(np.uint8)[::-1]


def _gif(images, labels, path, ms=600, scale=4):
    from PIL import Image, ImageDraw

    frames = []
    for im, label in zip(images, labels):
        big = im.resize((im.width * scale, im.height * scale), Image.NEAREST).convert("RGB")
        d = ImageDraw.Draw(big)
        cx, cy = big.width / 2, big.height / 2   # the grid centre = target position
        for a, b in (((cx - 18, cy), (cx - 8, cy)), ((cx + 8, cy), (cx + 18, cy)),
                     ((cx, cy - 18), (cx, cy - 8)), ((cx, cy + 8), (cx, cy + 18))):
            d.line([a, b], fill=(0, 220, 255), width=2)
        d.text((6, 6), label, fill=(255, 220, 0))
        frames.append(big)
    if frames:
        frames[0].save(path, save_all=True, append_images=frames[1:], duration=ms, loop=0)


def write(ss: StackSet, out_dir: str | Path, gif_ms: int = 600, gif_scale: int = 4) -> dict:
    """Write the frames for one target and return the JSON describing them.

    epoch_N.png   each epoch's stack
    diff_N.png    each epoch minus the median of all epochs (blink these for movers)
    pair.png      last epoch minus first (a mover = dark spot + bright spot)
    stacks.fits   the float images behind all of the above
    frames.json   dates, files, grid and display ranges, for the web page
    blink.gif, diff_blink.gif   labelled, enlarged previews

    PNGs are 1 image pixel per grid pixel; the browser scales them.
    """
    from PIL import Image

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for pattern in ("epoch_*.png", "diff_*.png"):  # a re-run may have fewer epochs
        for old in out.glob(pattern):
            old.unlink()
    vmin, vmax = display_range(ss)
    years = {s.epoch: Time(s.mjd_mid, format="mjd").decimalyear for s in ss.epochs}
    imgs = []
    for s in ss.epochs:
        im = Image.fromarray(to_uint8(s.image, vmin, vmax))
        im.save(out / f"epoch_{s.epoch}.png")
        imgs.append(im)
    _gif(imgs, [f"{ss.target}  epoch {s.epoch}  {years[s.epoch]:.2f}  ({s.n_frames} frames)"
                for s in ss.epochs], out / "blink.gif", gif_ms, gif_scale)

    res = residuals(ss)
    pr = pair(ss)
    first, last = min(years), max(years)
    lim = diff_limit(list(res.values()) + [pr])
    dimgs = []
    for e, d in res.items():
        im = Image.fromarray(to_uint8_signed(d, lim))
        im.save(out / f"diff_{e}.png")
        dimgs.append(im)
    Image.fromarray(to_uint8_signed(pr, lim)).save(out / "pair.png")
    _gif(dimgs, [f"{ss.target}  epoch {e} minus median  {years[e]:.2f}" for e in res],
         out / "diff_blink.gif", gif_ms, gif_scale)

    hdr = ss.wcs.to_header()
    hdus = [fits.PrimaryHDU(header=fits.Header({"OBJECT": ss.target}))]
    for s in ss.epochs:
        h = hdr.copy()
        h["EXTNAME"] = f"EPOCH{s.epoch}"
        h["MJD-AVG"] = s.mjd_mid
        h["NFRAMES"] = s.n_frames
        h["BUNIT"] = "MJy/sr"
        hdus.append(fits.ImageHDU(s.image, header=h))
    h = hdr.copy()
    h["EXTNAME"] = "PAIR"
    h["EPOCHA"], h["EPOCHB"], h["BUNIT"] = first, last, "MJy/sr"
    hdus.append(fits.ImageHDU(pr, header=h))
    fits.HDUList(hdus).writeto(out / "stacks.fits", overwrite=True)

    ny, nx = ss.epochs[0].image.shape if ss.epochs else (0, 0)
    meta = {
        "target": ss.target, "ra": round(ss.ra, 7), "dec": round(ss.dec, 7),
        "fov_deg": ss.fov_deg, "width": nx, "height": ny,
        "pixel_arcsec": round(abs(ss.wcs.wcs.cdelt[0]) * 3600, 3),
        "wcs": {k: hdr[k] for k in ("CTYPE1", "CTYPE2", "CRVAL1", "CRVAL2",
                                    "CRPIX1", "CRPIX2", "CDELT1", "CDELT2")},
        "display": {"stretch": "asinh", "vmin": vmin, "vmax": vmax, "unit": "MJy/sr",
                    "diff_limit": lim},
        "pair": {"file": "pair.png", "from_epoch": first, "to_epoch": last,
                 "note": "later minus earlier: white = brighter now, black = fainter now"},
        "frames": [{
            "epoch": s.epoch, "file": f"epoch_{s.epoch}.png", "diff_file": f"diff_{s.epoch}.png",
            "n_frames": s.n_frames,
            "start": epochmod.mjd_to_iso(s.mjd_start), "end": epochmod.mjd_to_iso(s.mjd_end),
            "mid_year": round(Time(s.mjd_mid, format="mjd").decimalyear, 3),
            "detectors": s.detectors, "wavelength_um": s.wavelength_um,
            "saturated_px": s.n_saturated,
        } for s in ss.epochs],
    }
    (out / "frames.json").write_text(json.dumps(meta, indent=2))
    return meta
