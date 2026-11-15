"""Turn a name or coordinates into a position, moved forward for proper motion.

Fast-moving targets like Barnard's Star (~10 arcsec/yr) have travelled several
arcminutes since their J2000 catalogue position. A cutout centred on the
catalogue position can miss them, so we move the centre to the date of the
SPHEREx observations.
"""
from __future__ import annotations

from dataclasses import dataclass

import astropy.units as u
from astropy.coordinates import Distance, SkyCoord
from astropy.time import Time

# The challenge's required test targets. Coordinates come from SIMBAD at runtime.
TEST_TARGETS = {
    "barnards-star": "Barnard's Star",
    "eps-ind-b": "eps Ind B",
    "wise-0855": "WISE J085510.83-071442.5",
    "rw-aur": "RW Aur",
    "r-dra": "R Dra",
}

# Built-in positions for the test targets, so the demo never depends on SIMBAD.
# (ra, dec, coordinate epoch, pmRA*cos(dec) mas/yr, pmDec mas/yr, parallax mas)
# Values are from SIMBAD/Gaia/literature and good to a few arcsec, far smaller than
# a cutout. WISE 0855's position is the one given in the challenge (WISE epoch ~2010.5).
BUILTIN = {
    "Barnard's Star": ("17h57m48.4998s", "+04d41m36.113s", 2000.0, -801.55, 10362.39, 546.98),
    "eps Ind B": ("22h04m10.52s", "-56d46m57.7s", 2000.0, 3982.0, -2466.0, 270.7),
    "WISE J085510.83-071442.5": ("08h55m10.831s", "-07d14m42.53s", 2010.5, -8118.0, 680.0, 439.0),
    "RW Aur": ("05h07m49.54s", "+30d24m05.1s", 2000.0, None, None, None),
    "R Dra": ("16h32m40.18s", "+66d45m18.4s", 2000.0, None, None, None),
}


def builtin(name: str) -> "Target":
    ra, dec, ep, pmra, pmdec, plx = BUILTIN[name]
    if pmra is None:
        return Target(name, SkyCoord(ra, dec, frame="icrs"), has_motion=False)
    c = SkyCoord(ra, dec, frame="icrs", pm_ra_cosdec=pmra * u.mas / u.yr,
                 pm_dec=pmdec * u.mas / u.yr, distance=Distance(parallax=plx * u.mas),
                 obstime=Time(ep, format="jyear"))
    return Target(name, c, has_motion=True)


@dataclass
class Target:
    name: str
    coord: SkyCoord            # catalogue position, with proper motion if known
    has_motion: bool

    def position_at(self, when: Time) -> SkyCoord:
        """Where the object is at `when` (falls back to the catalogue position)."""
        if not self.has_motion:
            return self.coord
        return self.coord.apply_space_motion(new_obstime=when)


# "S" = ask Sesame for SIMBAD only. Adding NED and VizieR ("SNV") finds the same stars
# but takes ~5 s to report a name it doesn't know, versus ~1 s for SIMBAD alone.
SESAME_URL = "https://cds.unistra.fr/cgi-bin/nph-sesame/-oxp/S?"


def _sesame(name: str) -> Target:
    """Look a name up with CDS Sesame (SIMBAD's data over plain HTTP), with proper motion.

    Positions are ICRS at epoch J2000, as SIMBAD gives them.
    """
    import urllib.parse
    import xml.etree.ElementTree as ET

    import requests

    r = requests.get(SESAME_URL + urllib.parse.quote(name), timeout=15)
    r.raise_for_status()
    res = ET.fromstring(r.content).find(".//Resolver")
    if res is None or res.find("jradeg") is None:
        raise LookupError(f"Sesame has no object called {name!r}")

    def num(path):
        el = res.find(path)
        try:
            return float(el.text) if el is not None and el.text else None
        except ValueError:
            return None

    ra, dec = num("jradeg"), num("jdedeg")
    pmra, pmdec, plx, rv = num("pm/pmRA"), num("pm/pmDE"), num("plx/v"), num("Vel/v")
    label = name
    if pmra is None or pmdec is None:
        return Target(label, SkyCoord(ra * u.deg, dec * u.deg), has_motion=False)
    kw = {}
    if plx and plx > 0:
        kw["distance"] = Distance(parallax=plx * u.mas)
        if rv is not None:
            kw["radial_velocity"] = rv * u.km / u.s
    c = SkyCoord(ra=ra * u.deg, dec=dec * u.deg, pm_ra_cosdec=pmra * u.mas / u.yr,
                 pm_dec=pmdec * u.mas / u.yr, obstime=Time("J2000"), frame="icrs", **kw)
    return Target(label, c, has_motion=True)


def resolve(name: str) -> Target:
    """Look up a name (Sesame first, then astroquery's SIMBAD), with proper motion if known."""
    try:
        return _sesame(name)
    except LookupError:
        # Sesame answered and doesn't know the name: SIMBAD (same database) won't either.
        if name in BUILTIN:
            return builtin(name)
        # A name from our suggestion list that SIMBAD spells differently ("Ain" is
        # "HR 1409" there): search with the alias that works.
        from .names import lookup
        entry = lookup(name)
        if entry and entry.get("query") and entry["query"] != name:
            t = _sesame(entry["query"])
            t.name = entry["name"]
            return t
        raise LookupError(f"No object called {name!r} was found. Check the spelling, "
                          "or give coordinates instead, e.g. \"269.452 4.693\".") from None
    except Exception as e:                       # Sesame unreachable: try SIMBAD directly
        sesame_error = str(e).splitlines()[0]
    try:
        return _simbad(name)
    except Exception as e:
        if name in BUILTIN:
            return builtin(name)
        raise LookupError(f"Couldn't find {name!r} (Sesame: {sesame_error}; "
                          f"SIMBAD: {str(e).splitlines()[0]}). "
                          "Try giving coordinates instead, e.g. \"269.452 4.693\".") from None


def _simbad(name: str) -> Target:
    """Look up a name with astroquery's SIMBAD, including proper motion, parallax and RV."""
    from astroquery.simbad import Simbad
    s = Simbad()
    s.add_votable_fields("pmra", "pmdec", "plx_value", "rvz_radvel")
    t = s.query_object(name)
    if t is None or len(t) == 0:
        raise LookupError(f"SIMBAD has no object called {name!r}")
    row = t[0]
    cols = {c.lower(): c for c in t.colnames}
    ra, dec = float(row[cols["ra"]]), float(row[cols["dec"]])

    def val(key):
        c = cols.get(key)
        v = row[c] if c else None
        try:
            return None if v is None or getattr(v, "mask", False) else float(v)
        except (TypeError, ValueError):
            return None

    pmra, pmdec, plx, rv = val("pmra"), val("pmdec"), val("plx_value"), val("rvz_radvel")
    if pmra is None or pmdec is None:
        return Target(name, SkyCoord(ra * u.deg, dec * u.deg), has_motion=False)
    kw = {}
    if plx and plx > 0:
        kw["distance"] = Distance(parallax=plx * u.mas)
    if rv is not None and "distance" in kw:
        kw["radial_velocity"] = rv * u.km / u.s
    c = SkyCoord(ra=ra * u.deg, dec=dec * u.deg, pm_ra_cosdec=pmra * u.mas / u.yr,
                 pm_dec=pmdec * u.mas / u.yr, obstime=Time("J2000"), frame="icrs", **kw)
    return Target(name, c, has_motion=True)


def from_coords(ra_deg: float, dec_deg: float) -> Target:
    return Target(f"{ra_deg:.5f} {dec_deg:+.5f}", SkyCoord(ra_deg * u.deg, dec_deg * u.deg),
                  has_motion=False)


def parse(text: str) -> Target:
    """Accept '269.45 4.69', '17h57m48s +04d41m36s', or a name like 'Barnard's Star'."""
    text = text.strip()
    key = text.lower().replace(" ", "-").replace("'", "")
    if key in TEST_TARGETS:
        return builtin(TEST_TARGETS[key])
    for name in BUILTIN:          # "Barnard's Star", "R Dra" etc. typed in full
        if text.lower() == name.lower():
            return builtin(name)
    try:
        parts = text.replace(",", " ").split()
        if len(parts) == 2:
            unit = (u.deg, u.deg) if all(_is_float(p) for p in parts) else (u.hourangle, u.deg)
            c = SkyCoord(parts[0], parts[1], unit=unit, frame="icrs")
            return from_coords(c.ra.deg, c.dec.deg)
    except ValueError:
        pass
    return resolve(text)


def _is_float(s: str) -> bool:
    try:
        float(s)
        return True
    except ValueError:
        return False
