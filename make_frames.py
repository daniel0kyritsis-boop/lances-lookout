"""Build the blink frames for one or more targets from the local cache.

    python make_frames.py                              # all five test targets, detector 2
    python make_frames.py "Barnard's Star"
    python make_frames.py "WISE J085510.83-071442.5" --detectors 5,6
    python make_frames.py "RW Aur" --fov 0.05
    python make_frames.py Sirius Vega --detectors auto   # choose like the website

Writes frames/<folder>/ (see frames.folder_name; the API uses the same folders):
epoch_N.png, diff_N.png, pair.png, stacks.fits, frames.json, blink.gif, diff_blink.gif.
Run prefetch.py first so the cutouts are already downloaded.
"""
import argparse
import time

from astropy import log

from spherex_data import TEST_TARGETS, best, frames, get_cutouts

log.setLevel("WARNING")   # SPHEREx headers trigger a long, harmless SIP note per file


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("targets", nargs="*", help="names or 'ra dec'; default = the 5 test targets")
    ap.add_argument("--detectors", default="2",
                    help="e.g. 2 or 5,6; 'all' = every detector, combined in noise units; "
                         "'auto' = choose like the website does and remember the choice")
    ap.add_argument("--fov", type=float, default=None, help="field of view, deg (default 0.1)")
    ap.add_argument("--out", default="frames")
    ap.add_argument("--max-images", type=int, default=None,
                    help="cap per target, spread evenly in time (default as the website: "
                         "150 for one detector, 240 for several)")
    a = ap.parse_args()

    fov = a.fov or frames.DEFAULT_FOV_DEG
    names = a.targets or list(TEST_TARGETS.values())
    failed = []
    for name in names:
        t0 = time.time()
        for attempt in range(4):           # IRSA sometimes answers 502 for a minute or two
            try:
                if a.detectors == "auto":
                    choice = best.remembered_choice(name, f"{a.out}/_auto")
                    if choice["method"] == "fallback":
                        raise RuntimeError(choice["reason"])
                    dets = choice["detectors"]
                    print(f"{name}: detectors {dets} ({choice['reason']})", flush=True)
                else:
                    dets = None if a.detectors in ("", "all") else [int(d) for d in a.detectors.split(",")]
                cap = a.max_images or (150 if dets and len(dets) == 1 else 240)
                cs = get_cutouts(name, size_deg=max(fov, frames.DEFAULT_FOV_DEG), detectors=dets,
                                 max_images=cap)
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
