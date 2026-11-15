"""Find every SPHEREx spectral image that covers a sky position.

Uses IRSA's TAP service and the `spherex.plane` / `spherex.artifact` tables,
following IRSA's "SPHEREx cutouts" tutorial notebook.
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass

from . import config


@dataclass
class ImageRecord:
    """One SPHEREx image that overlaps the position."""
    uri: str            # archive path of the full image, relative to IRSA_BASE
    mjd: float          # observation start time (MJD)
    bandpass: str       # e.g. "SPHEREx-D2"
    detector: int       # 1-6

    def cutout_url(self, ra: float, dec: float, size_deg: float) -> str:
        return f"{config.IRSA_BASE}{self.uri}?center={ra:.7f},{dec:.7f}d&size={size_deg:g}"


def build_adql(ra: float, dec: float, detectors: list[int] | None = None) -> str:
    query = (
        "SELECT a.uri, p.time_bounds_lower, p.energy_bandpassname "
        "FROM spherex.artifact a "
        "JOIN spherex.plane p ON a.planeid = p.planeid "
        f"WHERE 1 = CONTAINS(POINT('ICRS', {ra:.7f}, {dec:.7f}), p.poly)"
    )
    if detectors:
        names = ", ".join(f"'SPHEREx-D{d}'" for d in sorted(set(detectors)))
        query += f" AND p.energy_bandpassname IN ({names})"
    return query + " ORDER BY p.time_bounds_lower"


def _detector_from_bandpass(name: str) -> int:
    # "SPHEREx-D3" -> 3
    return int(str(name).strip().split("D")[-1])


TAP_TIMEOUT_S = 30


def _run_tap(adql: str) -> list[tuple]:
    """Run the search, giving up after TAP_TIMEOUT_S (when IRSA is struggling it can hang for minutes)."""
    import threading

    out = {}

    def run():
        try:
            import pyvo
            table = pyvo.dal.TAPService(config.TAP_URL).search(adql).to_table()
            out["rows"] = [(str(r["uri"]), float(r["time_bounds_lower"]), str(r["energy_bandpassname"]))
                           for r in table]
        except Exception as e:
            out["error"] = e

    # A daemon thread: a search still hanging after the timeout doesn't keep Python from exiting.
    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(TAP_TIMEOUT_S)
    if t.is_alive():
        raise TimeoutError(f"IRSA's image search didn't answer within {TAP_TIMEOUT_S} s")
    if "error" in out:
        raise out["error"]
    return out["rows"]


def _cache_path(ra: float, dec: float, detectors):
    # Round to ~0.4 arcsec so the same target typed twice hits the cache.
    det = "all" if not detectors else "".join(map(str, sorted(set(detectors))))
    key = f"q_{ra:.4f}_{dec:+.4f}_{det}.json"
    return config.CACHE_DIR / "queries" / key


def _read(path, max_age_h: float | None, detectors) -> list[ImageRecord] | None:
    if not path.exists():
        return None
    if max_age_h is not None and (time.time() - path.stat().st_mtime) / 3600 >= max_age_h:
        return None
    recs = [ImageRecord(**r) for r in json.loads(path.read_text())]
    if detectors:
        recs = [r for r in recs if r.detector in set(detectors)]
    return recs


TAP_RETRY_AFTER_S = 300
_tap_down_until = 0.0       # after a failure, skip IRSA's search for a while: use the cache


def find_images(ra: float, dec: float, detectors: list[int] | None = None,
                use_cache: bool = True, _tap=_run_tap, partial_ok: bool = False) -> list[ImageRecord]:
    """List SPHEREx images covering (ra, dec), oldest first.

    detectors: restrict to some of 1-6; None means all six.
    Results are cached for QUERY_TTL_HOURS so repeat lookups are instant but
    new weekly data still shows up. A cached list of all six detectors also
    answers a request for some of them. If IRSA's search is down, an older
    cached list is used rather than failing; after a failure IRSA isn't asked again
    for TAP_RETRY_AFTER_S seconds, so pages don't each wait for a timeout.
    partial_ok: during an outage, accept cached lists for only some of the detectors.
    """
    global _tap_down_until
    path = _cache_path(ra, dec, detectors)
    all_path = _cache_path(ra, dec, None)
    if use_cache:
        for p in (path, all_path):
            recs = _read(p, config.QUERY_TTL_HOURS, detectors)
            if recs is not None:
                return recs

    skip = time.time() < _tap_down_until
    try:
        if skip:
            raise ConnectionError("IRSA's image search failed recently; using cached image lists")
        rows = _tap(build_adql(ra, dec, detectors))
    except Exception:
        if not skip:
            _tap_down_until = time.time() + TAP_RETRY_AFTER_S
        for p in (path, all_path):                 # IRSA down: stale beats nothing
            recs = _read(p, None, detectors)
            if recs is not None:
                return recs
        wanted = set(detectors or range(1, 7))     # ... or any cached lists for this position
        found = {}                                 # (e.g. detector 5 from a cached "5,6" list)
        for p in path.parent.glob(path.name.rsplit("_", 1)[0] + "_*.json"):
            for r in _read(p, None, None) or []:
                if r.detector in wanted:
                    found[r.uri] = r
        if found and (partial_ok or {r.detector for r in found.values()} == wanted):
            return sorted(found.values(), key=lambda r: r.mjd)
        raise
    records = [ImageRecord(uri=u.lstrip("/"), mjd=t, bandpass=b,
                           detector=_detector_from_bandpass(b)) for u, t, b in rows]

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([asdict(r) for r in records]))
    return records
