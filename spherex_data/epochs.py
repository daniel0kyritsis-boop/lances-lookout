"""Group observations into epochs (one per ~6-month sky survey pass)."""
from __future__ import annotations

from astropy.time import Time

from . import config


def group_into_epochs(mjds: list[float], gap_days: float | None = None,
                      max_span_days: float | None = None, bin_days: float | None = None) -> list[int]:
    """Give each observation an epoch number (0, 1, 2...), in time order.

    Step 1: a new epoch starts whenever the gap since the previous observation
    is more than gap_days (separates the ~6-month survey passes).
    Step 2: near the ecliptic poles SPHEREx sees the same spot almost daily, so
    there are no gaps. Only a run longer than max_span_days is treated as
    continuous coverage and cut into bins of bin_days, so the animation still
    has frames. Ordinary passes (a few stragglers included) stay whole.
    Returns one label per input, in the input's order.
    """
    gap = config.EPOCH_GAP_DAYS if gap_days is None else gap_days
    span = config.EPOCH_MAX_SPAN_DAYS if max_span_days is None else max_span_days
    binw = config.EPOCH_BIN_DAYS if bin_days is None else bin_days
    order = sorted(range(len(mjds)), key=lambda i: mjds[i])

    runs, cur = [], []
    for i in order:
        if cur and mjds[i] - mjds[cur[-1]] > gap:
            runs.append(cur)
            cur = []
        cur.append(i)
    if cur:
        runs.append(cur)

    labels = [0] * len(mjds)
    epoch = 0
    for run in runs:
        t0 = mjds[run[0]]
        if mjds[run[-1]] - t0 <= span:
            for i in run:
                labels[i] = epoch
            epoch += 1
        else:
            # Equal-width bins, about bin_days each. Using the run's own length (not
            # fixed 30-day steps from t0) means the last image joins the final bin
            # instead of becoming a one-image epoch of its own.
            length = mjds[run[-1]] - t0
            n = max(1, round(length / binw))
            width = length / n
            bin_of = {i: min(int((mjds[i] - t0) / width), n - 1) for i in run}
            used = sorted(set(bin_of.values()))
            remap = {b: epoch + k for k, b in enumerate(used)}
            for i in run:
                labels[i] = remap[bin_of[i]]
            epoch += len(used)
    return labels


def mjd_to_iso(mjd: float) -> str:
    return Time(mjd, format="mjd").isot[:19] + "Z"


def mjd_to_decimal_year(mjd: float) -> float:
    return float(Time(mjd, format="mjd").decimalyear)
