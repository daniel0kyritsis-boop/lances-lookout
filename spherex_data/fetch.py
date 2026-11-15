"""Download cutouts from IRSA's cutout service, with an on-disk cache and retries."""
from __future__ import annotations

import hashlib
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

from . import config


def _cache_file(url: str) -> Path:
    h = hashlib.sha1(url.encode()).hexdigest()
    return config.CACHE_DIR / "cutouts" / h[:2] / f"{h}.fits"


def fetch_cutout(url: str, session: requests.Session | None = None) -> Path:
    """Return a local path to the cutout FITS file, downloading it if needed.

    The same URL always gives the same file, so files are cached for good.
    """
    out = _cache_file(url)
    if out.exists() and out.stat().st_size > 0:
        return out
    out.parent.mkdir(parents=True, exist_ok=True)
    sess = session or requests.Session()

    last_err = None
    for attempt in range(config.HTTP_RETRIES):
        try:
            r = sess.get(url, timeout=config.HTTP_TIMEOUT_S)
            r.raise_for_status()
            if not r.content.startswith(b"SIMPLE"):
                raise ValueError(f"Not a FITS file (starts {r.content[:40]!r})")
            tmp = out.with_suffix(".part")
            tmp.write_bytes(r.content)
            tmp.replace(out)          # atomic, so a crash never leaves a half file
            return out
        except Exception as e:        # timeouts, 5xx, dropped connections
            last_err = e
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"Failed after {config.HTTP_RETRIES} tries: {url}: {last_err}")


def fetch_many(urls: list[str], max_workers: int | None = None,
               progress=None) -> dict[str, Path | Exception]:
    """Download many cutouts in parallel. Returns {url: path or the error}.

    Failures are returned rather than raised: IRSA's tutorial sees a few
    percent of cutouts fail under parallel load, and one bad frame shouldn't
    sink the whole animation.
    """
    results: dict[str, Path | Exception] = {}
    with requests.Session() as sess, ThreadPoolExecutor(max_workers or config.MAX_WORKERS) as pool:
        futures = {pool.submit(fetch_cutout, u, sess): u for u in urls}
        for i, fut in enumerate(as_completed(futures), 1):
            url = futures[fut]
            try:
                results[url] = fut.result()
            except Exception as e:
                results[url] = e
            if progress:
                progress(i, len(urls))
    return results
