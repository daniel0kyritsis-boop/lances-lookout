"""Main entry point: get every SPHEREx cutout of a patch of sky, grouped by epoch.

    from spherex_data import get_cutouts
    cs = get_cutouts("Barnard's Star", size_deg=0.1, detectors=[1, 2, 3])
    for c in cs.cutouts:
        c.image, c.flags, c.variance, c.wcs, c.epoch, c.detector, c.wavelength_um
    cs.metadata()   # JSON-ready dict for the API / frontend
"""
from __future__ import annotations

import statistics
import warnings
from dataclasses import dataclass, field

import numpy as np
from astropy.io import fits
from astropy.time import Time
from astropy.wcs import WCS, FITSFixedWarning

from . import config, epochs, flags as flagmod, targets
from .fetch import fetch_many
from .query import ImageRecord, find_images

warnings.filterwarnings("ignore", category=FITSFixedWarning)


@dataclass
class Cutout:
    url: str
    mjd: float
    detector: int
    epoch: int
    image: np.ndarray          # surface brightness, MJy/sr
    flags: np.ndarray          # per-pixel bitmask
    variance: np.ndarray
    zodi: np.ndarray | None    # zodiacal light model (subtract it for a cleaner image)
    header: fits.Header        # IMAGE header
    wcs: WCS                   # sky coordinates of each pixel
    target_px: tuple[int, int] | None
    wavelength_um: float | None   # wavelength at the target pixel
    version: str | None
    flag_summary: dict = field(default_factory=dict)

    def wavelength_map(self) -> np.ndarray | None:
        """Wavelength (microns) of every pixel. SPHEREx's filter varies across the detector."""
        return _wavelength_grid(self)


@dataclass
class CutoutSet:
    target: str
    ra: float
    dec: float
    size_deg: float
    cutouts: list[Cutout]
    failed: list[dict]

    @property
    def n_epochs(self) -> int:
        return len({c.epoch for c in self.cutouts})

    def by_epoch(self, detector: int | None = None) -> dict[int, list[Cutout]]:
        out: dict[int, list[Cutout]] = {}
        for c in self.cutouts:
            if detector is None or c.detector == detector:
                out.setdefault(c.epoch, []).append(c)
        return dict(sorted(out.items()))

    def metadata(self) -> dict:
        """JSON-friendly summary: what the backend returns alongside the frames."""
        ep = {}
        for e, cs in self.by_epoch().items():
            mjds = [c.mjd for c in cs]
            ep[e] = {
                "epoch": e,
                "start": epochs.mjd_to_iso(min(mjds)),
                "end": epochs.mjd_to_iso(max(mjds)),
                "mid_year": round(epochs.mjd_to_decimal_year(statistics.median(mjds)), 3),
                "n_images": len(cs),
                "detectors": {d: sum(1 for c in cs if c.detector == d) for d in sorted({c.detector for c in cs})},
            }
        return {
            "target": self.target,
            "ra": round(self.ra, 7),
            "dec": round(self.dec, 7),
            "size_deg": self.size_deg,
            "n_images": len(self.cutouts),
            "n_epochs": self.n_epochs,
            "epochs": list(ep.values()),
            "images": [{
                "index": i, "epoch": c.epoch, "detector": c.detector,
                "time": epochs.mjd_to_iso(c.mjd), "mjd": round(c.mjd, 6),
                "wavelength_um": None if c.wavelength_um is None else round(c.wavelength_um, 4),
                "shape": list(c.image.shape), "version": c.version, "flags": c.flag_summary,
                "url": c.url,
            } for i, c in enumerate(self.cutouts)],
            "failed": self.failed,
        }


def get_cutouts(target: str | tuple[float, float], size_deg: float = config.DEFAULT_SIZE_DEG,
                detectors: list[int] | None = None, max_images: int | None = None,
                progress=None) -> CutoutSet:
    """Fetch all SPHEREx cutouts of a position.

    target: a name ("Barnard's Star"), a coordinate string, or (ra, dec) in degrees.
    detectors: subset of 1-6 (None = all). Fewer detectors = faster.
    max_images: cap the download for big queries (spread evenly across time).
    """
    if not 0 < size_deg <= config.MAX_SIZE_DEG:
        raise ValueError(f"size_deg must be between 0 and {config.MAX_SIZE_DEG}")
    tgt = targets.from_coords(*target) if isinstance(target, tuple) else targets.parse(target)

    # Find the images first (position as of today is close enough to find them),
    # then centre every cutout on where the object was mid-way through the data.
    first = tgt.position_at(Time.now())
    records = find_images(first.ra.deg, first.dec.deg, detectors)
    if not records:
        return CutoutSet(tgt.name, first.ra.deg, first.dec.deg, size_deg, [], [])
    mid = Time(statistics.median(r.mjd for r in records), format="mjd")
    centre = tgt.position_at(mid)
    ra, dec = centre.ra.deg, centre.dec.deg

    if max_images and len(records) > max_images:
        step = len(records) / max_images
        records = [records[int(i * step)] for i in range(max_images)]

    labels = epochs.group_into_epochs([r.mjd for r in records])
    urls = [r.cutout_url(ra, dec, size_deg) for r in records]
    files = fetch_many(urls, progress=progress)

    cutouts, failed = [], []
    for rec, url, ep in zip(records, urls, labels):
        res = files.get(url)
        if isinstance(res, Exception) or res is None:
            failed.append({"url": url, "mjd": rec.mjd, "error": str(res)})
            continue
        try:
            cutouts.append(load_cutout(res, rec, url, ep, ra, dec))
        except Exception as e:
            failed.append({"url": url, "mjd": rec.mjd, "error": f"unreadable: {e}"})
    cutouts.sort(key=lambda c: c.mjd)
    return CutoutSet(tgt.name, ra, dec, size_deg, cutouts, failed)


def _hdu(hdul, name, index):
    try:
        return hdul[name]
    except KeyError:
        return hdul[index] if index < len(hdul) else None


def load_cutout(path, rec: ImageRecord, url: str, epoch: int, ra: float, dec: float) -> Cutout:
    with fits.open(path, memmap=False) as hdul:
        img = _hdu(hdul, "IMAGE", 1)
        flg = _hdu(hdul, "FLAGS", 2)
        var = _hdu(hdul, "VARIANCE", 3)
        zod = _hdu(hdul, "ZODI", 4)
        header = img.header.copy()
        # SPHEREx headers carry SIP distortion terms but no "-SIP" on CTYPE.
        # Add it so astropy applies the distortion knowingly (and stops warning).
        if "A_ORDER" in header:
            for k in ("CTYPE1", "CTYPE2"):
                if k in header and not str(header[k]).endswith("-SIP"):
                    header[k] = str(header[k]) + "-SIP"
        wcs = WCS(header)
        px = None
        x, y = wcs.world_to_pixel_values(ra, dec)
        if np.isfinite(x) and np.isfinite(y):
            xi, yi = int(round(float(x))), int(round(float(y)))
            if 0 <= yi < img.data.shape[0] and 0 <= xi < img.data.shape[1]:
                px = (xi, yi)
        wl = _wavelength_at(hdul, header, px)
        c = Cutout(
            url=url, mjd=rec.mjd, detector=rec.detector, epoch=epoch,
            image=np.array(img.data, dtype=np.float32),
            flags=np.array(flg.data) if flg is not None else np.zeros(img.data.shape, np.int32),
            variance=np.array(var.data, dtype=np.float32) if var is not None else None,
            zodi=np.array(zod.data, dtype=np.float32) if zod is not None else None,
            header=header, wcs=wcs, target_px=px, wavelength_um=wl,
            version=hdul[0].header.get("VERSION"),
        )
        c._path = str(path)  # used for the wavelength grid
        c.flag_summary = flagmod.summarize(c.flags, flg.header if flg is not None else None, px)
    return c


def _wavelength_at(hdul, header, px) -> float | None:
    """Wavelength at one pixel, via the spectral WCS (keys ending in 'W', table in WCS-WAVE)."""
    if px is None:
        return None
    try:
        wwcs = WCS(header, fobj=hdul, key="W")
        vals = wwcs.pixel_to_world_values(px[0], px[1])
        return float(np.atleast_1d(vals[0])[0])
    except Exception:
        return None


def _wavelength_grid(c: Cutout) -> np.ndarray | None:
    try:
        with fits.open(c._path) as hdul:
            wwcs = WCS(c.header, fobj=hdul, key="W")
            ny, nx = c.image.shape
            yy, xx = np.mgrid[0:ny, 0:nx]
            return np.asarray(wwcs.pixel_to_world_values(xx, yy)[0], dtype=np.float32)
    except Exception:
        return None
