"""Star name suggestions for the search box, and "did you mean" for misspellings.

Works offline from star_names.json (built by build_names.py): ~500 IAU star names
plus nearby moving stars, brown dwarfs and variable stars, each with aliases.
"""
from __future__ import annotations

import json
import re
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path

NAMES_FILE = Path(__file__).with_name("star_names.json")

# People type "alpha centauri" or "α Cen"; the list says "alf Cen". Map all to one form.
GREEK = {"alpha": "alf", "beta": "bet", "gamma": "gam", "delta": "del", "epsilon": "eps",
         "zeta": "zet", "theta": "tet", "iota": "iot", "kappa": "kap", "lambda": "lam",
         "xi": "ksi", "omicron": "omi", "upsilon": "ups", "omega": "ome",
         "α": "alf", "β": "bet", "γ": "gam", "δ": "del", "ε": "eps", "ζ": "zet", "η": "eta",
         "θ": "tet", "ι": "iot", "κ": "kap", "λ": "lam", "μ": "mu", "ν": "nu", "ξ": "ksi",
         "ο": "omi", "π": "pi", "ρ": "rho", "σ": "sig", "τ": "tau", "υ": "ups", "φ": "phi",
         "χ": "chi", "ψ": "psi", "ω": "ome"}


def normalize(text: str) -> str:
    """Lower case, Greek letters spelled the catalogue way, punctuation dropped."""
    text = text.lower()
    for k, v in GREEK.items():
        if not k.isascii():
            text = text.replace(k, v + " ")
    words = re.findall(r"[a-z0-9]+", text.replace("'", ""))
    words = [GREEK.get(w, w) for w in words]
    # "gliese 229" and "gj 229" are the same catalogue
    words = ["gj" if w == "gliese" else w for w in words]
    return " ".join(words)


@lru_cache(maxsize=1)
def _entries() -> list[dict]:
    entries = json.loads(NAMES_FILE.read_text(encoding="utf-8"))
    for e in entries:
        e["_keys"] = [normalize(k) for k in [e["name"], *e.get("aliases", [])]]
    return entries


def _score(q: str, key: str) -> float | None:
    """Lower is better. None means no match."""
    if key == q:
        return 0.0
    if key.startswith(q):
        return 1.0 + len(key) / 100            # shorter completions first
    if any(w.startswith(q) for w in key.split()) or (" " + q) in (" " + key):
        return 2.0 + len(key) / 100
    if len(q) >= 3 and q in key.replace(" ", ""):
        return 3.0 + len(key) / 100
    if len(q) >= 3:                            # typo tolerance
        # compare against the start of the key as long as the query, and the whole key
        r = max(SequenceMatcher(None, q, key[:len(q) + 1]).ratio(),
                SequenceMatcher(None, q, key).ratio())
        if r >= 0.75:
            return 5.0 - r
    return None


def _public(e: dict, matched: str | None) -> dict:
    out = {"name": e["name"], "query": e.get("query", e["name"]), "kind": e.get("kind", "star"),
           "ra": e.get("ra"), "dec": e.get("dec")}
    if matched and normalize(matched) != normalize(e["name"]):
        out["matched"] = matched              # the alias the user's text matched
    return out


def suggest(text: str, limit: int = 8) -> list[dict]:
    """Names that start with, contain, or nearly match `text`, best first."""
    q = normalize(text)
    if not q:
        return []
    ranked = []
    for e in _entries():
        labels = [e["name"], *e.get("aliases", [])]
        best = None
        for label, key in zip(labels, e["_keys"]):
            s = _score(q, key)
            # within the same kind of match, prefer the main name over an alias
            if s is not None and (best is None or int(s) < int(best[0])):
                best = (s, label)
        if best:
            ranked.append((best[0], e["name"].lower(), e, best[1]))
    ranked.sort(key=lambda r: r[:2])
    return [_public(e, label) for _, _, e, label in ranked[:limit]]


def did_you_mean(text: str, limit: int = 3) -> list[dict]:
    """Close spellings only (for a name that wasn't found)."""
    q = normalize(text)
    if len(q) < 3:
        return []
    scored = []
    for e in _entries():
        r = max(SequenceMatcher(None, q, k).ratio() for k in e["_keys"])
        if r >= 0.6:
            scored.append((-r, e["name"].lower(), e))
    scored.sort(key=lambda s: s[:2])
    return [_public(e, None) for _, _, e in scored[:limit]]


# Quick-access buttons on the page: well-known stars, plus a few that are good to blink.
# The very bright ones saturate SPHEREx, so they show as large blank-cored discs.
FAMOUS = ["Sirius", "Betelgeuse", "Vega", "Polaris", "Rigil Kentaurus", "Proxima Centauri",
          "Arcturus", "Antares", "Rigel", "Aldebaran", "Mira", "Algol", "eta Car",
          "Wolf 359", "61 Cyg A", "TRAPPIST-1", "Tabby's Star"]


# Button labels where the familiar name isn't the IAU one.
FAMOUS_LABELS = {"Rigil Kentaurus": "Alpha Centauri", "eta Car": "Eta Carinae", "61 Cyg A": "61 Cygni"}


def famous() -> list[dict]:
    by_name = {e["name"]: e for e in _entries()}
    out = []
    for n in FAMOUS:
        if n in by_name:
            item = _public(by_name[n], None)
            item["name"] = FAMOUS_LABELS.get(n, n)
            out.append(item)
    return out


def lookup(text: str) -> dict | None:
    """The list entry whose name or alias is exactly `text` (ignoring case/punctuation)."""
    q = normalize(text)
    for e in _entries():
        if q in e["_keys"]:
            return e
    return None
