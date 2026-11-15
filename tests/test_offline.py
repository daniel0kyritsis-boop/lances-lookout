"""Offline tests: fake TAP results and synthetic FITS cutouts, no network needed."""
import numpy as np
import pytest
from astropy.io import fits
from astropy.wcs import WCS

import spherex_data.core as core
import spherex_data.query as query
from spherex_data import config, epochs, flags, targets


@pytest.fixture(autouse=True)
def tmp_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CACHE_DIR", tmp_path)


def fake_fits(path, ra, dec, n=33, star_offset_px=(0, 0), flag_bit=None):
    w = WCS(naxis=2)
    w.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    w.wcs.crval = [ra, dec]
    w.wcs.crpix = [(n + 1) / 2, (n + 1) / 2]   # FITS is 1-based: pixel 16 (0-based) is the centre
    w.wcs.cdelt = [-6.2 / 3600, 6.2 / 3600]
    img = np.random.default_rng(0).normal(1, 0.05, (n, n)).astype(np.float32)
    cx, cy = n // 2 + star_offset_px[0], n // 2 + star_offset_px[1]
    img[cy, cx] += 50
    fl = np.zeros((n, n), np.int32)
    if flag_bit is not None:
        fl[n // 2, n // 2] = 1 << flag_bit
    hl = fits.HDUList([
        fits.PrimaryHDU(header=fits.Header({"VERSION": "test-v1"})),
        fits.ImageHDU(img, header=w.to_header(), name="IMAGE"),
        fits.ImageHDU(fl, name="FLAGS"),
        fits.ImageHDU(np.full((n, n), 0.01, np.float32), name="VARIANCE"),
        fits.ImageHDU(np.zeros((n, n), np.float32), name="ZODI"),
    ])
    # Real SPHEREx files name each bit with MSKNnnnn / MSKDnnnn cards in the FLAGS header.
    hl[2].header["MSKN0001"] = ("OVERFLOW", "Name for mask plane 1")
    hl[2].header["MSKD0001"] = "Overflow detected during SUR"
    hl[2].header["MSKN0021"] = ("SOURCE", "Name for mask plane 21")
    hl[2].header["MSKD0021"] = "Pixel mapped to a known source"
    hl.writeto(path)
    return path


def test_adql_has_position_and_detectors():
    q = query.build_adql(10.5, -20.25, [3, 1])
    assert "CONTAINS(POINT('ICRS', 10.5000000, -20.2500000), p.poly)" in q
    assert "IN ('SPHEREx-D1', 'SPHEREx-D3')" in q
    assert q.endswith("ORDER BY p.time_bounds_lower")


def test_cutout_url_format():
    r = query.ImageRecord("ibe/data/spherex/x.fits", 60800.0, "SPHEREx-D2", 2)
    assert r.cutout_url(1.5, -2.5, 0.1) == \
        "https://irsa.ipac.caltech.edu/ibe/data/spherex/x.fits?center=1.5000000,-2.5000000d&size=0.1"


def test_find_images_caches():
    calls = []
    def tap(adql):
        calls.append(adql)
        return [("/ibe/a.fits", 60900.0, "SPHEREx-D2"), ("/ibe/b.fits", 60800.0, "SPHEREx-D5")]
    r1 = query.find_images(1, 2, None, _tap=tap)
    r2 = query.find_images(1, 2, None, _tap=tap)
    assert len(calls) == 1 and r1 == r2
    assert r1[0].uri == "ibe/a.fits" and r1[1].detector == 5


def test_epoch_grouping():
    # three surveys ~6 months apart, several visits each, given out of order
    mjds = [60810, 60800, 60802, 60990, 60985, 61170]
    assert epochs.group_into_epochs(mjds) == [0, 0, 0, 1, 1, 2]


def test_straggler_stays_with_its_pass():
    # Barnard's Star real case: pass 18-28 Aug 2026 plus one image on 22 Sep
    mjds = [61270.9, 61275.0, 61280.2, 61305.6]
    assert epochs.group_into_epochs(mjds) == [0, 0, 0, 0]


def test_epoch_grouping_near_ecliptic_pole():
    # observed every 2 days for 120 days: no gaps, so cut into 30-day bins
    mjds = [60800 + 2 * i for i in range(61)]
    labels = epochs.group_into_epochs(mjds)
    assert len(set(labels)) == 4
    assert labels == sorted(labels)


def test_flag_summary_reads_header_names():
    fl = np.zeros((5, 5), np.int32)
    fl[2, 2] = 1 << 1                      # OVERFLOW on the target
    fl[:, :] |= 1 << 21                    # SOURCE everywhere (informational)
    hdr = fits.Header()
    hdr["MSKN0001"], hdr["MSKD0001"] = "OVERFLOW", "Overflow detected during SUR"
    hdr["MSKN0021"], hdr["MSKD0021"] = "SOURCE", "Pixel mapped to a known source"
    s = flags.summarize(fl, hdr, center_px=(2, 2))
    assert s["bits"] == {"OVERFLOW": 1, "SOURCE": 25}
    assert s["at_target"] == ["OVERFLOW", "SOURCE"]
    assert s["problems_at_target"] == ["OVERFLOW"]          # SOURCE isn't a problem
    assert s["flagged_fraction"] == pytest.approx(1 / 25)   # ...and isn't counted as flagged
    assert s["descriptions"]["OVERFLOW"] == "Overflow detected during SUR"


def test_flag_names_fall_back_without_header():
    fl = np.zeros((3, 3), np.int32)
    fl[1, 1] = 1 << 10
    assert flags.summarize(fl, None)["bits"] == {"HOT": 1}


def test_get_cutouts_end_to_end(tmp_path, monkeypatch):
    ra, dec = 150.0, 2.0
    recs = [query.ImageRecord(f"ibe/img{i}.fits", m, f"SPHEREx-D{d}", d)
            for i, (m, d) in enumerate([(60800, 1), (60801, 2), (60990, 1), (61170, 2)])]
    monkeypatch.setattr(core, "find_images", lambda *a, **k: recs)

    def fake_fetch(urls, progress=None):
        out = {}
        for i, u in enumerate(urls):
            if i == 3:
                out[u] = RuntimeError("HTTP 503")       # one failed download
            else:
                out[u] = fake_fits(tmp_path / f"c{i}.fits", ra, dec, star_offset_px=(i, 0),
                                   flag_bit=1 if i == 0 else None)
        return out
    monkeypatch.setattr(core, "fetch_many", fake_fetch)

    cs = core.get_cutouts((ra, dec), size_deg=0.05)
    assert len(cs.cutouts) == 3 and len(cs.failed) == 1
    assert [c.epoch for c in cs.cutouts] == [0, 0, 1]
    assert cs.cutouts[0].target_px == (16, 16)
    assert cs.cutouts[0].flag_summary["at_target"] == ["OVERFLOW"]
    m = cs.metadata()
    assert m["n_epochs"] == 2 and m["epochs"][0]["detectors"] == {1: 1, 2: 1}
    assert set(cs.by_epoch(detector=1)) == {0, 1}
    import json; json.dumps(m)   # must be JSON-serialisable for the API


def test_proper_motion_moves_barnards_star():
    from astropy.coordinates import SkyCoord, Distance
    from astropy.time import Time
    import astropy.units as u
    # Barnard's Star-like motion: ~10.4 arcsec/yr, mostly north
    c = SkyCoord(269.452 * u.deg, 4.693 * u.deg, pm_ra_cosdec=-800 * u.mas / u.yr,
                 pm_dec=10360 * u.mas / u.yr, distance=Distance(parallax=547 * u.mas),
                 obstime=Time("J2000"))
    t = targets.Target("test", c, True)
    moved = t.position_at(Time("2026-01-01")).separation(c.apply_space_motion(new_obstime=Time("J2000")))
    assert 250 < moved.arcsec < 290   # ~4.5 arcmin in 26 years


def test_parse_coordinate_strings():
    t = targets.parse("269.45 4.69")
    assert abs(t.coord.ra.deg - 269.45) < 1e-9
    t = targets.parse("08h55m10.831s -07d14m42.53s")
    assert abs(t.coord.dec.deg - (-7.24515)) < 1e-4


def test_builtin_targets_need_no_network(monkeypatch):
    import astroquery.simbad
    monkeypatch.setattr(astroquery.simbad, "Simbad", None)   # any SIMBAD use would crash
    from astropy.time import Time
    for key in targets.TEST_TARGETS:
        t = targets.parse(key)
        t.position_at(Time("2026-01-01"))
    b = targets.parse("Barnard's Star")
    moved = b.position_at(Time("2026-01-01")).separation(b.coord)
    assert 250 < moved.arcsec < 290
