"""Build spherex_data/star_names.json, the list the search box suggests names from.

    python build_names.py

Sources:
  * The IAU Catalog of Star Names (WGSN, CC BY 4.0), ~450 proper names such as
    Vega, Polaris and Proxima Centauri, with their catalogue designations.
    https://www.pas.rochester.edu/~emamajek/WGSN/IAU-CSN.txt
  * EXTRAS below: nearby fast-moving stars, brown dwarfs, variable stars and a few
    other objects that are good to blink but have no IAU proper name.

Every name is checked with CDS Sesame, so each suggestion is one the search can
actually find; names Sesame doesn't know are dropped with a warning. The output is
committed to the repository, so the site needs no network to make suggestions.
"""
from __future__ import annotations

import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

from spherex_data.targets import _sesame

IAU_URL = "https://www.pas.rochester.edu/~emamajek/WGSN/IAU-CSN.txt"
OUT = Path(__file__).parent / "spherex_data" / "star_names.json"

# (name to search with, kind, aliases people might type)
EXTRAS = [
    # The challenge's test targets
    ("Barnard's Star", "moving", ["GJ 699", "V2500 Oph"]),
    ("eps Ind B", "moving", ["Epsilon Indi B"]),
    ("WISE J085510.83-071442.5", "moving", ["WISE 0855-0714", "WISE 0855"]),
    ("RW Aur", "variable", ["RW Aurigae"]),
    ("R Dra", "variable", ["R Draconis"]),
    # Nearby stars with large proper motion
    ("Wolf 359", "moving", ["CN Leo", "GJ 406"]),
    ("Lalande 21185", "moving", ["GJ 411"]),
    ("Luyten's Star", "moving", ["GJ 273"]),
    ("Ross 128", "moving", ["GJ 447"]),
    ("Ross 154", "moving", ["V1216 Sgr"]),
    ("Ross 248", "moving", ["HH And"]),
    ("Kapteyn's Star", "moving", ["GJ 191"]),
    ("Van Maanen's Star", "moving", ["GJ 35"]),
    ("Teegarden's Star", "moving", []),
    ("Lacaille 9352", "moving", ["GJ 887"]),
    ("Lacaille 8760", "moving", ["AX Mic"]),
    ("Groombridge 34", "moving", ["GJ 15"]),
    ("Groombridge 1830", "moving", ["GJ 451"]),
    ("61 Cyg A", "moving", ["61 Cygni"]),
    ("Struve 2398", "moving", ["GJ 725"]),
    ("eps Ind A", "moving", ["Epsilon Indi"]),
    ("eps Eri", "moving", ["Epsilon Eridani"]),
    ("tau Cet", "moving", ["Tau Ceti"]),
    ("alf Cen A", "moving", ["Alpha Centauri"]),
    ("YZ Cet", "moving", []),
    ("UV Cet", "moving", ["Luyten 726-8"]),
    ("GJ 1061", "moving", []),
    ("SCR J1845-6357", "moving", []),
    ("LHS 1140", "moving", []),
    ("TRAPPIST-1", "moving", ["2MASS J23062928-0502285"]),
    ("GJ 436", "moving", []),
    ("GJ 1214", "moving", []),
    ("LP 944-20", "moving", []),
    ("Gliese 229 B", "moving", ["GJ 229 B"]),
    ("Gliese 570 D", "moving", ["GJ 570 D"]),
    ("Luhman 16", "moving", ["WISE J104915.57-531906.1", "WISE 1049-5319"]),
    ("2MASS J04151954-0935066", "moving", ["2MASS 0415-0935"]),
    ("Proxima Centauri", "moving", ["Proxima Cen"]),
    # Variable stars
    ("Mira", "variable", ["omi Cet"]),
    ("R Leo", "variable", ["R Leonis"]),
    ("chi Cyg", "variable", ["Chi Cygni"]),
    ("R Hya", "variable", ["R Hydrae"]),
    ("R Cas", "variable", ["R Cassiopeiae"]),
    ("R Aqr", "variable", ["R Aquarii"]),
    ("T Cep", "variable", ["T Cephei"]),
    ("U Ori", "variable", ["U Orionis"]),
    ("W Hya", "variable", ["W Hydrae"]),
    ("R CrB", "variable", ["R Coronae Borealis"]),
    ("RR Lyr", "variable", ["RR Lyrae"]),
    ("del Cep", "variable", ["Delta Cephei"]),
    ("T Tau", "variable", ["T Tauri"]),
    ("FU Ori", "variable", ["FU Orionis"]),
    ("V1057 Cyg", "variable", []),
    ("EX Lup", "variable", ["EX Lupi"]),
    ("DG Tau", "variable", []),
    ("AB Aur", "variable", []),
    ("V838 Mon", "variable", []),
    ("eta Car", "variable", ["Eta Carinae"]),
    ("VY CMa", "variable", ["VY Canis Majoris"]),
    ("CW Leo", "variable", ["IRC +10216"]),
    ("Tabby's Star", "variable", ["KIC 8462852", "Boyajian's Star"]),
    ("V1298 Tau", "variable", []),
    # Other things worth a look
    ("Sgr A*", "other", ["Galactic Centre", "Galactic Center"]),
    ("M42", "other", ["Orion Nebula"]),
    ("M1", "other", ["Crab Nebula"]),
    ("M31", "other", ["Andromeda Galaxy"]),
    ("M45", "other", ["Pleiades"]),
    ("M57", "other", ["Ring Nebula"]),
    ("3C 273", "variable", []),
    ("Cyg X-1", "other", ["Cygnus X-1"]),
]

GREEK = {"alf": "Alpha", "bet": "Beta", "gam": "Gamma", "del": "Delta", "eps": "Epsilon",
         "zet": "Zeta", "eta": "Eta", "tet": "Theta", "iot": "Iota", "kap": "Kappa",
         "lam": "Lambda", "mu": "Mu", "nu": "Nu", "ksi": "Xi", "omi": "Omicron", "pi": "Pi",
         "rho": "Rho", "sig": "Sigma", "tau": "Tau", "ups": "Upsilon", "phi": "Phi",
         "chi": "Chi", "psi": "Psi", "ome": "Omega"}
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def iau_names() -> list[dict]:
    r = requests.get(IAU_URL, timeout=30)
    r.encoding = "utf-8"            # the server doesn't say; columns only line up as UTF-8
    text = r.text
    out = []
    for line in text.splitlines():
        if not line.strip() or line.startswith(("#", "$")):
            continue
        name = line[0:18].strip()
        designation = line[36:49].strip()
        bayer = line[49:55].strip()
        rest = line[61:].split()
        con = rest[0]
        i = next(k for k, t in enumerate(rest) if DATE.match(t))
        ra, dec = float(rest[i - 2]), float(rest[i - 1])
        aliases = [designation] if designation not in ("", "_") else []
        if bayer not in ("", "_"):
            m = re.match(r"([a-z]+)\.?(\d*)$", bayer)          # "tet01" -> "tet", "1"
            letter, num = (m.group(1), m.group(2).lstrip("0")) if m else (bayer, "")
            aliases.append(f"{letter}{num} {con}")
            if letter in GREEK:
                aliases.append(f"{GREEK[letter]}{num} {con}")
        out.append({"name": name, "aliases": aliases, "kind": "star", "ra": ra, "dec": dec,
                    "source": "IAU"})
    return out


def check(entry: dict) -> dict | None:
    """Fill in the position from Sesame; None if Sesame can't find the name (or an alias)."""
    for query in [entry["name"], *entry["aliases"]]:
        try:
            t = _sesame(query)
        except LookupError:
            continue
        except Exception as e:
            print(f"  ! Sesame error for {query!r}: {e}", file=sys.stderr)
            continue
        entry = dict(entry, ra=round(t.coord.ra.deg, 6), dec=round(t.coord.dec.deg, 6))
        if query != entry["name"]:
            entry["query"] = query      # what to search for, when the display name isn't found
        return entry
    return None


def main():
    # Extras first, so their kind ("moving", "variable") wins when the IAU list has the
    # same star (e.g. Barnard's Star); the IAU entry's aliases are merged in.
    entries = [{"name": n, "aliases": a, "kind": k, "source": "extra"} for n, k, a in EXTRAS]
    entries += iau_names()
    by_key: dict[str, dict] = {}
    for e in entries:
        key = e["name"].lower()
        if key in by_key:
            have = by_key[key]
            have["aliases"] += [a for a in e["aliases"] if a not in have["aliases"]]
        else:
            by_key[key] = e
    unique = list(by_key.values())
    print(f"Checking {len(unique)} names with Sesame...")
    with ThreadPoolExecutor(8) as pool:
        checked = list(pool.map(check, unique))
    kept = [c for c in checked if c]
    for e, c in zip(unique, checked):
        if c is None:
            print("  dropped (Sesame doesn't know it):", e["name"])
    # Test targets and extras keep their kinds; sort by name for a stable file.
    kept.sort(key=lambda e: e["name"].lower())
    OUT.write_text(json.dumps(kept, ensure_ascii=False, indent=0), encoding="utf-8")
    print(f"Wrote {len(kept)} names to {OUT}")


if __name__ == "__main__":
    main()
