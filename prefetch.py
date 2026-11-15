"""Pre-download the test targets (and pick up new data releases).

Run before the demo so it works even if IRSA is slow:
    python prefetch.py                    # all five test targets
    python prefetch.py "Barnard's Star"   # just one
    python prefetch.py --refresh          # ignore cached image lists (new weekly data)

Schedule it daily (cron / GitHub Action) to keep the cache current.
"""
import argparse
import json
import sys
import time

from spherex_data import TEST_TARGETS, config, get_cutouts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("targets", nargs="*", help="names or 'ra dec'; default = the 5 test targets")
    ap.add_argument("--size", type=float, default=config.DEFAULT_SIZE_DEG)
    ap.add_argument("--detectors", default="", help="e.g. 1,2,3 (default all)")
    ap.add_argument("--refresh", action="store_true", help="re-query IRSA for new images")
    ap.add_argument("--out", default="prefetch_summary.json")
    a = ap.parse_args()

    if a.refresh:
        config.QUERY_TTL_HOURS = 0
    dets = [int(d) for d in a.detectors.split(",") if d] or None
    names = a.targets or list(TEST_TARGETS.values())

    summary = {}
    for name in names:
        t0 = time.time()
        print(f"== {name}", flush=True)
        try:
            cs = get_cutouts(name, size_deg=a.size, detectors=dets,
                             progress=lambda i, n: print(f"\r  {i}/{n} cutouts", end="", flush=True))
            meta = cs.metadata()
            print(f"\n  {meta['n_images']} images, {meta['n_epochs']} epochs, "
                  f"{len(meta['failed'])} failed, {time.time() - t0:.0f}s")
            summary[name] = {k: meta[k] for k in ("ra", "dec", "n_images", "n_epochs", "epochs")}
            summary[name]["n_failed"] = len(meta["failed"])
        except Exception as e:
            print(f"\n  ERROR: {e}", file=sys.stderr)
            summary[name] = {"error": str(e)}
    with open(a.out, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"Summary written to {a.out}")


if __name__ == "__main__":
    main()
