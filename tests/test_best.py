"""Automatic detector choice (best.decide) and the stale-cache fallback for image lists."""
import json
import os
import time

from spherex_data import best, config, query


def s(snr, sat=0.0, px=0):
    return {"snr": snr, "saturated_frac": sat, "saturated_px": px}


def test_brightest_unsaturated_band_wins():
    per = {1: s(900, sat=1, px=10), 2: s(800, sat=1, px=9), 4: s(300), 5: s(200)}
    assert best.decide(per)[0] == [4]


def test_faint_target_combines_bands_where_detected():
    # WISE 0855-like: invisible at short wavelengths, faint at 4-5 microns
    per = {1: s(0.5), 2: s(1), 3: s(2), 4: s(4), 5: s(12), 6: s(9)}
    dets, reason = best.decide(per)
    assert dets == [5, 6]
    assert "combining" in reason


def test_saturated_everywhere_picks_least_saturated():
    per = {d: s(1000, sat=1, px=14 - d) for d in range(1, 7)}
    assert best.decide(per)[0] == [6]


def test_no_samples_falls_back_to_detector_2():
    assert best.decide({})[0] == [2]


def _write(path, recs, age_h):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(recs))
    t = time.time() - age_h * 3600
    os.utime(path, (t, t))


def test_stale_cache_used_when_archive_down(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CACHE_DIR", tmp_path)
    rec = lambda d, t: {"uri": f"u{d}{t}", "mjd": t, "bandpass": f"SPHEREx-D{d}", "detector": d}
    _write(query._cache_path(1, 2, [5]), [rec(5, 3.0), rec(5, 1.0)], age_h=1000)
    _write(query._cache_path(1, 2, [6]), [rec(6, 2.0)], age_h=1000)

    def down(_):
        raise RuntimeError("502 Proxy Error")

    got = query.find_images(1, 2, [5, 6], _tap=down)
    assert [r.mjd for r in got] == [1.0, 2.0, 3.0]
    assert query.find_images(1, 2, [5], _tap=down)[0].detector == 5


def test_all_detector_cache_answers_a_subset(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CACHE_DIR", tmp_path)
    recs = [{"uri": f"u{d}", "mjd": float(d), "bandpass": f"SPHEREx-D{d}", "detector": d} for d in range(1, 7)]
    _write(query._cache_path(1, 2, None), recs, age_h=0)

    def never(_):
        raise AssertionError("should not query the archive")

    assert [r.detector for r in query.find_images(1, 2, [2, 4], _tap=never)] == [2, 4]


def test_archive_failure_is_a_clear_503(monkeypatch):
    from fastapi.testclient import TestClient
    import server

    def down(*a, **k):
        raise TimeoutError("IRSA's image search didn't answer within 30 s")

    monkeypatch.setattr(server, "get_cutouts", down)
    r = TestClient(server.app).get("/api/frames", params={"ra": 12.345, "dec": -6.789, "detectors": "2"})
    assert r.status_code == 503
    assert "IRSA archive isn't answering" in r.json()["detail"]


def test_archive_down_falls_back_to_prebuilt_view(monkeypatch):
    from fastapi.testclient import TestClient
    import server

    def down(*a, **k):
        raise TimeoutError("IRSA down")

    monkeypatch.setattr(server, "get_cutouts", down)
    monkeypatch.setattr(server.best, "remembered_choice", lambda *a, **k: {"detectors": [2]})
    c = TestClient(server.app)
    for params in ({"fov": 0.25}, {"detectors": "all"}):
        r = c.get("/api/frames", params={"target": "Polaris", **params})
        assert r.status_code == 200, r.text
        assert r.json()["fallback"] is True and r.json()["fov_deg"] == 0.1
    assert "fallback" not in c.get("/api/frames", params={"target": "Polaris"}).json()


def test_single_detector_from_a_cached_pair(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CACHE_DIR", tmp_path)
    recs = [{"uri": f"u{d}", "mjd": float(d), "bandpass": f"SPHEREx-D{d}", "detector": d} for d in (5, 6)]
    _write(query._cache_path(1, 2, [5, 6]), recs, age_h=1000)

    def down(_):
        raise RuntimeError("502")

    assert [r.detector for r in query.find_images(1, 2, [5], _tap=down)] == [5]
