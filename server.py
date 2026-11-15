"""Web API for SPHEREx – Lance's Lookout (the SPHEREx blink tool).

    uvicorn server:app --reload            # then open http://127.0.0.1:8000/docs

Endpoints
    GET /api/targets                        the five test targets and whether they're ready
    GET /api/suggest?q=barn                 star names for the search box (typo tolerant)
    GET /api/famous                         well-known stars for quick access
    GET /api/frames?target=Barnard's Star   blink frames for a name or "ra dec"
    GET /api/frames?ra=269.45&dec=4.69      ... or for coordinates
        optional: fov (deg, 0.02-0.25), detectors (e.g. "5,6"), refresh=true
    GET /api/images?target=...              per-image details (time, wavelength, flags)
    GET /frames/<folder>/<file>             the PNGs and GIFs themselves

Frames are built once and kept in frames/<folder>/ (the same folders make_frames.py
writes), so repeat requests return instantly.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from astropy import log
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from spherex_data import TEST_TARGETS, frames, get_cutouts, names, parse_target

log.setLevel("WARNING")   # SPHEREx headers trigger a long, harmless SIP note per file

ROOT = Path(__file__).parent
FRAMES_DIR = Path(os.environ.get("SPHEREX_FRAMES_DIR", ROOT / "frames"))
WEB_DIR = ROOT / "web"
FRAMES_DIR.mkdir(parents=True, exist_ok=True)
# On start-up, build frames for any test target that doesn't have them (in the
# background, so the site is up straight away). Set to 0 to skip.
WARM_ON_START = os.environ.get("SPHEREX_WARM_ON_START", "1") != "0"
logger = logging.getLogger("uvicorn.error")

MIN_FOV, MAX_FOV = 0.02, 0.25          # degrees; bigger fields mean far more downloading
MAX_IMAGES = 150                       # per request, spread evenly across time

# What each test target is, and the detectors it shows up best on.
# WISE 0855 is a very cold brown dwarf: invisible at 1-2 microns, bright at 4-5.
TARGET_INFO = {
    "barnards-star": {"kind": "moving", "detectors": [2]},
    "eps-ind-b": {"kind": "moving", "detectors": [2]},
    "wise-0855": {"kind": "moving", "detectors": [5, 6]},
    "rw-aur": {"kind": "variable", "detectors": [2]},
    "r-dra": {"kind": "variable", "detectors": [2]},
}
BY_NAME = {name: key for key, name in TEST_TARGETS.items()}

def _warm_test_targets():
    for key, name in TEST_TARGETS.items():
        dets = TARGET_INFO[key]["detectors"]
        folder = frames.folder_name(name, dets, frames.DEFAULT_FOV_DEG)
        if (FRAMES_DIR / folder / "frames.json").exists():
            continue
        logger.info("warm-up: building frames for %s", name)
        try:
            with _lock(folder):
                cs = get_cutouts(name, detectors=dets, max_images=MAX_IMAGES)
                if cs.cutouts:
                    frames.write(frames.stack_epochs(cs), FRAMES_DIR / folder)
        except Exception as e:                      # never take the site down over this
            logger.warning("warm-up: %s failed: %s", name, e)
    logger.info("warm-up: test targets ready")


@asynccontextmanager
async def lifespan(app):
    if WARM_ON_START:
        threading.Thread(target=_warm_test_targets, daemon=True).start()
    yield


app = FastAPI(title="SPHEREx – Lance's Lookout API", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET"])
app.mount("/frames", StaticFiles(directory=FRAMES_DIR), name="frames")

_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _lock(key: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(key, threading.Lock())


def _parse_detectors(text: str | None) -> list[int] | None:
    if text is None:
        return None
    if text.strip().lower() in ("", "all"):
        return []                       # [] = every detector (distinct from "not given")
    try:
        dets = sorted({int(d) for d in text.split(",") if d.strip()})
    except ValueError:
        raise HTTPException(400, "detectors must look like 2 or 5,6")
    if not all(1 <= d <= 6 for d in dets):
        raise HTTPException(400, "SPHEREx detectors are numbered 1 to 6")
    return dets


def _resolve(target: str | None, ra: float | None, dec: float | None):
    if target is None and (ra is None or dec is None):
        raise HTTPException(400, "give target=<name or 'ra dec'>, or both ra and dec")
    text = target if target is not None else f"{ra} {dec}"
    try:
        return parse_target(text)
    except LookupError as e:
        # "Did you mean ..." for misspelled names, so the page can offer the right one.
        raise HTTPException(404, {"message": str(e), "suggestions": names.did_you_mean(text)})


def _with_urls(meta: dict, folder: str) -> dict:
    base = f"/frames/{folder}/"
    meta = dict(meta)
    meta["folder"] = folder
    meta["base_url"] = base
    meta["pair"] = dict(meta["pair"], url=base + meta["pair"]["file"])
    meta["frames"] = [dict(f, url=base + f["file"], diff_url=base + f["diff_file"])
                      for f in meta["frames"]]
    meta["blink_gif"] = base + "blink.gif"
    meta["diff_gif"] = base + "diff_blink.gif"
    meta["n_epochs"] = len(meta["frames"])
    if meta["n_epochs"] < 2:
        meta["warning"] = (f"Only {meta['n_epochs']} epoch covers this position so far, "
                           "so there is nothing to blink yet.")
    return meta


def _settings(tgt, detectors: str | None, fov: float):
    if not MIN_FOV <= fov <= MAX_FOV:
        raise HTTPException(400, f"fov must be between {MIN_FOV} and {MAX_FOV} degrees")
    dets = _parse_detectors(detectors)
    key = BY_NAME.get(tgt.name)
    if dets is None:                    # not given: the target's best detectors, else 2
        dets = TARGET_INFO[key]["detectors"] if key else list(frames.DEFAULT_DETECTORS)
    return (dets or None), key


@app.get("/api/targets")
def targets():
    out = []
    for key, name in TEST_TARGETS.items():
        info = TARGET_INFO[key]
        folder = frames.folder_name(name, info["detectors"], frames.DEFAULT_FOV_DEG)
        out.append({"key": key, "name": name, **info,
                    "ready": (FRAMES_DIR / folder / "frames.json").exists()})
    return out


@app.get("/api/suggest")
def suggest(q: str = "", limit: int = Query(8, ge=1, le=20)):
    """Star names matching what's been typed so far (prefix, contains, or close spelling)."""
    return names.suggest(q, limit)


@app.get("/api/famous")
def famous():
    """Well-known stars for the quick-access row."""
    return names.famous()


@app.get("/api/frames")
def get_frames(target: str | None = None, ra: float | None = None, dec: float | None = None,
               fov: float = Query(frames.DEFAULT_FOV_DEG), detectors: str | None = None,
               refresh: bool = False):
    tgt = _resolve(target, ra, dec)
    dets, key = _settings(tgt, detectors, fov)
    folder = frames.folder_name(tgt.name, dets, fov)
    out_dir = FRAMES_DIR / folder
    meta_file = out_dir / "frames.json"

    with _lock(folder):                 # two requests for the same field build it once
        if refresh or not meta_file.exists():
            # tgt.name is the resolved name, or "ra dec" for coordinates; both parse back.
            cs = get_cutouts(tgt.name, size_deg=max(fov, frames.DEFAULT_FOV_DEG),
                             detectors=dets, max_images=MAX_IMAGES)
            if not cs.cutouts:
                raise HTTPException(404, "No SPHEREx images cover this position yet "
                                         f"(detectors {dets or 'all'}).")
            frames.write(frames.stack_epochs(cs, fov_deg=fov), out_dir)
        meta = json.loads(meta_file.read_text())
    meta = _with_urls(meta, folder)
    meta["detectors_used"] = dets or [1, 2, 3, 4, 5, 6]
    if key:
        meta["test_target"] = {"key": key, **TARGET_INFO[key]}
    return meta


@app.get("/api/images")
def images(target: str | None = None, ra: float | None = None, dec: float | None = None,
           detectors: str | None = None):
    """Every individual image: time, detector, wavelength at the target, quality flags."""
    tgt = _resolve(target, ra, dec)
    dets, _ = _settings(tgt, detectors, frames.DEFAULT_FOV_DEG)
    cs = get_cutouts(tgt.name, detectors=dets, max_images=MAX_IMAGES)
    return JSONResponse(cs.metadata())


@app.get("/")
def index():
    page = WEB_DIR / "index.html"
    if page.exists():
        return FileResponse(page)
    return {"message": "SPHEREx – Lance's Lookout API. The web page isn't built yet; see /docs for the API."}
