"""Build the blink frames for one or more targets from the local cache.

    python make_frames.py                              # all five test targets, detector 2
    python make_frames.py "Barnard's Star"
    python make_frames.py "WISE J085510.83-071442.5" --detectors 5,6
    python make_frames.py "RW Aur" --fov 0.05

Writes frames/<folder>/ (see frames.folder_name; the API uses the same folders):
epoch_N.png, diff_N.png, pair.png, stacks.fits, frames.json, blink.gif, diff_blink.gif.
Run prefetch.py first so the cutouts are already downloaded.
"""
import argparse
import time

from astropy import log

from spherex_data import TEST_TARGETS, frames, get_cutouts

log.setLevel("WARNING")   # SPHEREx headers trigger a long, harmless SIP note per file


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("targets", nargs="*", help="names or 'ra dec'; default = the 5 test targets")
    ap.add_argument("--detectors", default="2", help="e.g. 2 or 5,6 (blank = all)")
    ap.add_argument("--fov", type=float, default=None, help="field of view, deg (default 0.1)")
    ap.add_argument("--out", default="frames")
    ap.add_argument("--max-images", type=int, default=150,
                    help="cap per target, spread evenly in time (same as the website)")
    a = ap.parse_args()

    dets = [int(d) for d in a.detectors.split(",") if d] or None
    fov = a.fov or frames.DEFAULT_FOV_DEG
    names = a.targets or list(TEST_TARGETS.values())
    failed = []
    for name in names:
        t0 = time.time()
        for attempt in range(4):           # IRSA sometimes answers 502 for a minute or two
            try:
                cs = get_cutouts(name, size_deg=max(fov, frames.DEFAULT_FOV_DEG), detectors=dets,
                                 max_images=a.max_images)
                break
            except Exception as e:
                print(f"{name}: attempt {attempt + 1} failed: {str(e).splitlines()[0]}", flush=True)
                time.sleep(30 * (attempt + 1))
        else:
            failed.append(name)
            continue
        if not cs.cutouts:
            print(f"{name}: no cutouts (run prefetch.py first?)")
            continue
        ss = frames.stack_epochs(cs, fov_deg=fov)
        out = f"{a.out}/{frames.folder_name(cs.target, dets, fov)}"
        meta = frames.write(ss, out)
        eps = ", ".join(f"{f['mid_year']:.2f} ({f['n_frames']})" for f in meta["frames"])
        print(f"{cs.target}: {len(meta['frames'])} epochs [{eps}], "
              f"{meta['width']}x{meta['height']} px, {time.time() - t0:.0f}s -> {out}", flush=True)
    if failed:
        print("Failed (try again later):", ", ".join(failed))


if __name__ == "__main__":
    main()
