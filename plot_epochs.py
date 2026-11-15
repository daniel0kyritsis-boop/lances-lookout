"""Plot a target's SPHEREx cutouts epoch by epoch, all resampled north-up.

    python plot_epochs.py                          # Barnard's Star, detector 2
    python plot_epochs.py "eps Ind B" --detectors 2
    python plot_epochs.py "Barnard's Star" --out barnard.png --zoom 2

Each panel is the median of every cutout in that epoch (zodiacal light removed),
resampled onto the same sky grid so the panels line up. The red circle is where
proper motion predicts the star at that epoch; the cyan cross is a fixed reference
point (the first epoch's predicted position), so you can see the star move away from it.
Uses the local cache, so run prefetch.py first.
"""
import argparse
import warnings

import matplotlib.pyplot as plt
import numpy as np
from astropy import log
from astropy.time import Time
from astropy.visualization import AsinhStretch, ImageNormalize
from astropy.wcs import WCS

from spherex_data import get_cutouts, parse_target

# SPHEREx headers carry SIP distortion without the "-SIP" CTYPE suffix; astropy
# applies it anyway (which is what we want) but prints a long note per file.
log.setLevel("WARNING")

PIX_ARCSEC = 6.2   # SPHEREx pixel size


def common_wcs(ra, dec, half_arcmin):
    """North-up TAN grid centred on (ra, dec) at the SPHEREx pixel scale."""
    n = int(round(2 * half_arcmin * 60 / PIX_ARCSEC)) | 1   # odd, so the centre is a pixel
    w = WCS(naxis=2)
    w.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    w.wcs.crval = [ra, dec]
    w.wcs.crpix = [(n + 1) / 2, (n + 1) / 2]
    w.wcs.cdelt = [-PIX_ARCSEC / 3600, PIX_ARCSEC / 3600]
    return w, n


def resample(c, out_wcs, n):
    """Nearest-pixel resample of a cutout onto out_wcs (fine for a quick look)."""
    img = c.image.astype(float)
    if c.zodi is not None and c.zodi.shape == img.shape:
        img = img - c.zodi
    yy, xx = np.mgrid[0:n, 0:n]
    sky = out_wcs.pixel_to_world(xx, yy)
    sx, sy = c.wcs.celestial.world_to_pixel(sky)
    ix, iy = np.rint(sx).astype(int), np.rint(sy).astype(int)
    ok = (ix >= 0) & (iy >= 0) & (ix < img.shape[1]) & (iy < img.shape[0])
    out = np.full((n, n), np.nan)
    out[ok] = img[iy[ok], ix[ok]]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("target", nargs="?", default="Barnard's Star")
    ap.add_argument("--detectors", default="2", help="e.g. 2 or 1,2,3")
    ap.add_argument("--zoom", type=float, default=1.0, help="half-width of each panel, arcmin")
    ap.add_argument("--out", default=None, help="PNG path (default: <target>_epochs.png)")
    a = ap.parse_args()

    dets = [int(d) for d in a.detectors.split(",") if d] or None
    cs = get_cutouts(a.target, detectors=dets)
    if not cs.cutouts:
        raise SystemExit(f"No cutouts for {a.target!r}. Run prefetch.py first.")
    tgt = parse_target(a.target)
    groups = cs.by_epoch()

    # Predicted position at each epoch's median time.
    when = {e: Time(np.median([c.mjd for c in g]), format="mjd") for e, g in groups.items()}
    pos = {e: tgt.position_at(t) for e, t in when.items()}
    ref = pos[min(pos)]
    out_wcs, n = common_wcs(cs.ra, cs.dec, a.zoom)

    with warnings.catch_warnings():   # pixels no frame covers stay NaN; that's fine
        warnings.simplefilter("ignore", RuntimeWarning)
        stacks = {e: np.nanmedian([resample(c, out_wcs, n) for c in g], axis=0)
                  for e, g in groups.items()}
    vals = np.concatenate([s[np.isfinite(s)] for s in stacks.values()])
    vmin, vmax = np.percentile(vals, [10, 99.9])
    norm = ImageNormalize(vmin=vmin, vmax=vmax, stretch=AsinhStretch(0.02))

    k = len(stacks)
    fig = plt.figure(figsize=(3.6 * k, 4.6))
    for i, (e, img) in enumerate(stacks.items()):
        ax = fig.add_subplot(1, k, i + 1, projection=out_wcs)
        ax.imshow(img, origin="lower", cmap="gray", norm=norm)
        px, py = out_wcs.world_to_pixel(pos[e])
        rx, ry = out_wcs.world_to_pixel(ref)
        ax.plot(rx, ry, "+", color="cyan", ms=14, mew=1.2)
        ax.add_patch(plt.Circle((px, py), 2.5, fill=False, color="red", lw=1.2))
        moved = ref.separation(pos[e]).arcsec
        ax.set_title(f"Epoch {e}: {when[e].decimalyear:.2f}\n"
                     f"{len(groups[e])} frames, moved {moved:.1f}\"", fontsize=9)
        ax.coords[0].set_axislabel("RA")
        ax.coords[1].set_axislabel("Dec" if i == 0 else " ")
        if i:
            ax.coords[1].set_ticklabel_visible(False)
    fig.suptitle(f"{cs.target}: SPHEREx detector {a.detectors}, north up\n"
                 f"red = predicted position, cyan = epoch {min(pos)} position", fontsize=10)
    fig.tight_layout(rect=(0, 0, 1, 0.9))
    out = a.out or f"{cs.target.lower().replace(' ', '_').replace(chr(39), '')}_epochs.png"
    fig.savefig(out, dpi=130)
    print(f"Saved {out}")


if __name__ == "__main__":
    main()
