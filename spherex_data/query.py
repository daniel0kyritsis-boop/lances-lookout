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


def _run_tap(adql: str) -> list[tuple]:
    import pyvo
    service = pyvo.dal.TAPService(config.TAP_URL)
    table = service.search(adql).to_table()
    return [(str(r["uri"]), float(r["time_bounds_lower"]), str(r["energy_bandpassname"]))
            for r in table]


def _cache_path(ra: float, dec: float, detectors):
    # Round to ~0.4 arcsec so the same target typed twice hits the cache.
    det = "all" if not detectors else "".join(map(str, sorted(set(detectors))))
    key = f"q_{ra:.4f}_{dec:+.4f}_{det}.json"
    return config.CACHE_DIR / "queries" / key


def find_images(ra: float, dec: float, detectors: list[int] | None = None,
                use_cache: bool = True, _tap=_run_tap) -> list[ImageRecord]:
    """List SPHEREx images covering (ra, dec), oldest first.

    detectors: restrict to some of 1-6; None means all six.
    Results are cached for QUERY_TTL_HOURS so repeat lookups are instant but
    new weekly data still shows up.
    """
    path = _cache_path(ra, dec, detectors)
    if use_cache and path.exists():
        age_h = (time.time() - path.stat().st_mtime) / 3600
        if age_h < config.QUERY_TTL_HOURS:
            return [ImageRecord(**r) for r in json.loads(path.read_text())]

    rows = _tap(build_adql(ra, dec, detectors))
    records = [ImageRecord(uri=u.lstrip("/"), mjd=t, bandpass=b,
                           detector=_detector_from_bandpass(b)) for u, t, b in rows]

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([asdict(r) for r in records]))
    return records
