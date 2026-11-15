"""Offline tests for the frame builder (alignment, stacking, differences, folder names)."""
import json

import numpy as np
from astropy.wcs import WCS

from spherex_data import frames
from spherex_data.core import Cutout, CutoutSet


def make_cutout(ra, dec, mjd, epoch, star_offset_arcsec=0.0, rotate=False, n=41):
    """A synthetic cutout with one star, optionally on a rotated detector grid."""
    w = WCS(naxis=2)
    w.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    w.wcs.crval = [ra, dec]
    w.wcs.crpix = [(n + 1) / 2, (n + 1) / 2]
    s = 6.2 / 3600
    w.wcs.cd = [[0, s], [s, 0]] if rotate else [[-s, 0], [0, s]]
    yy, xx = np.mgrid[0:n, 0:n]
    # star `star_offset_arcsec` north of centre, put in through the WCS so rotation is honoured
    sx, sy = w.world_to_pixel_values(ra, dec + star_offset_arcsec / 3600)
    img = 1.0 + 100 * np.exp(-((xx - sx) ** 2 + (yy - sy) ** 2) / (2 * 0.8 ** 2))
    return Cutout(url=f"u{mjd}", mjd=mjd, detector=2, epoch=epoch, image=img.astype(np.float32),
                  flags=np.zeros((n, n), np.int32), variance=None, zodi=None, header=None,
                  wcs=w, target_px=(n // 2, n // 2), wavelength_um=1.3, version=None)


def brightest_offset_arcsec(img, pix_arcsec):
    """(east, north) offset of the brightest pixel from the grid centre, in arcsec."""
    y, x = np.unravel_index(np.nanargmax(img), img.shape)
    c = img.shape[0] // 2
    return (-(x - c) * pix_arcsec, (y - c) * pix_arcsec)


def test_stacks_line_up_and_show_motion():
    ra, dec = 150.0, 2.0
    cs = CutoutSet("test", ra, dec, 0.06, [
        make_cutout(ra, dec, 60800, 0, 0.0), make_cutout(ra, dec, 60801, 0, 0.0, rotate=True),
        make_cutout(ra, dec, 61170, 1, 12.4), make_cutout(ra, dec, 61171, 1, 12.4, rotate=True),
    ], [])
    ss = frames.stack_epochs(cs)
    pix = abs(ss.wcs.wcs.cdelt[0]) * 3600
    e0, e1 = (brightest_offset_arcsec(s.image, pix) for s in ss.epochs)
    assert abs(e0[0]) <= pix and abs(e0[1]) <= pix            # both detector orientations agree
    assert abs(e1[1] - 12.4) <= pix and abs(e1[0]) <= pix     # moved 12.4" north
    pr = frames.pair(ss)
    assert pr[np.unravel_index(np.nanargmax(pr), pr.shape)] > 0   # white where it is now
    assert np.nanmin(pr) < 0                                       # black where it was


def test_fill_saturated_fills_enclosed_holes_only():
    img = np.ones((9, 9))
    img[4, 4] = np.nan                  # saturated core, surrounded by data
    img[4, 3] = 50
    img[0, :3] = np.nan                 # no-coverage strip on the edge
    out, n = frames.fill_saturated(img)
    assert n == 1 and out[4, 4] == 50
    assert np.isnan(out[0, :3]).all()


def test_difference_stretch_is_grey_at_zero():
    d = np.array([[-2.0, 0.0, 2.0]])
    u8 = frames.to_uint8_signed(d, lim=2.0)
    assert u8.tolist() == [[0, 128, 255]]


def test_folder_names_match_existing_layout():
    assert frames.folder_name("Barnard's Star", [2], 0.1) == "barnards-star"
    assert frames.folder_name("WISE J085510.83-071442.5", [5, 6], 0.1) == "wise-j085510-83-071442-5_d5-6"
    assert frames.folder_name("R Dra", None, 0.2) == "r-dra_dall_fov0.2"


def test_write_produces_files_for_the_page(tmp_path):
    ra, dec = 150.0, 2.0
    cs = CutoutSet("test", ra, dec, 0.06, [make_cutout(ra, dec, 60800, 0), make_cutout(ra, dec, 61170, 1, 6.2)], [])
    meta = frames.write(frames.stack_epochs(cs), tmp_path)
    for f in ["epoch_0.png", "epoch_1.png", "diff_0.png", "pair.png", "stacks.fits", "blink.gif"]:
        assert (tmp_path / f).exists(), f
    assert json.loads((tmp_path / "frames.json").read_text()) == json.loads(json.dumps(meta))
    assert [f["diff_file"] for f in meta["frames"]] == ["diff_0.png", "diff_1.png"]


def test_merge_epochs_until_every_detector_present():
    from spherex_data.core import CutoutSet
    # detector pairs arrive in different short epochs, as near the ecliptic poles
    layout = {0: [3, 6], 1: [1, 4, 2, 5], 2: [1, 4], 3: [2, 5, 3, 6], 4: [1, 4]}
    cs = CutoutSet("t", 0, 0, 0.1, [_cutout(e, d) for e, ds in layout.items() for d in ds], [])
    merged = frames._merge_until_complete(cs)
    groups = {}
    for c in merged.cutouts:
        groups.setdefault(c.epoch, set()).add(c.detector)
    assert groups == {0: {1, 2, 3, 4, 5, 6}, 1: {1, 2, 3, 4, 5, 6}}


def _cutout(epoch, detector):
    import numpy as np
    from astropy.wcs import WCS
    from spherex_data.core import Cutout
    z = np.zeros((2, 2), np.float32)
    return Cutout(url="", mjd=float(epoch), detector=detector, epoch=epoch, image=z, flags=z,
                  variance=None, zodi=None, header=None, wcs=WCS(naxis=2), target_px=None,
                  wavelength_um=None, version=None)
