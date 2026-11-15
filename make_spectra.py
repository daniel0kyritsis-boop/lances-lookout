"""Pre-build spectra (brightness vs wavelength per epoch) so the website shows them instantly.

    python make_spectra.py                         # the five test targets
    python make_spectra.py Sirius "Proxima Centauri"

Writes frames/_spectra/<target>.json, the same files the API (/api/spectrum) reads.
Uses every detector it can get; if IRSA's search is down, it uses whatever image
lists are cached (the file then says which detectors were available).
"""
import argparse
import json
import time
from pathlib import Path

from astropy import log

from spherex_data import TEST_TARGETS, frames, spectrum, targets

log.setLevel("WARNING")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("targets", nargs="*", help="names or 'ra dec'; default = the 5 test targets")
    ap.add_argument("--out", default="frames/_spectra")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    for name in a.targets or list(TEST_TARGETS.values()):
        t0 = time.time()
        try:
            s = spectrum.build(name)
        except Exception as e:
            print(f"{name}: failed: {str(e).splitlines()[0]}", flush=True)
            continue
        path = out / (frames.folder_name(targets.parse(name).name, frames.DEFAULT_DETECTORS, None) + ".json")
        path.write_text(json.dumps(s))
        ms = [f"{e['mid_year']:.2f}: x{e['matched']['ratio']:.2f}" for e in s["epochs"] if e["matched"]]
        print(f"{name}: {len(s['points'])} points, detectors {s['detectors']}, {s['n_saturated']} saturated, "
              f"{len(s['bins'])} matched bins [{', '.join(ms)}], {time.time() - t0:.0f}s -> {path}", flush=True)


if __name__ == "__main__":
    main()
