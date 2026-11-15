"""Name suggestions: offline, from spherex_data/star_names.json."""
from fastapi.testclient import TestClient

from spherex_data import names


def first(q):
    s = names.suggest(q)
    return s[0]["name"] if s else None


def test_prefix_and_typos():
    assert first("barn") == "Barnard's Star"
    assert first("Barnards Str") == "Barnard's Star"
    assert first("betelguese") == "Betelgeuse"
    assert first("sirus") == "Sirius"
    assert first("vega") == "Vega"


def test_aliases_and_greek():
    assert first("wise 0855") == "WISE J085510.83-071442.5"
    assert "Rigil Kentaurus" in [s["name"] for s in names.suggest("alpha cen")]
    assert "Rigil Kentaurus" in [s["name"] for s in names.suggest("α Cen")]
    assert first("gliese 229") == "Gliese 229 B"


def test_main_name_preferred_over_alias():
    assert "matched" not in names.suggest("proxima")[0]


def test_nothing_for_nonsense_and_empty():
    assert names.suggest("xyzzy") == []
    assert names.suggest("  ") == []


def test_did_you_mean():
    assert names.did_you_mean("Barnards Str")[0]["name"] == "Barnard's Star"
    assert names.did_you_mean("Siruis")[0]["name"] == "Sirius"


def test_famous_list_resolves():
    fam = names.famous()
    assert len(fam) == len(names.FAMOUS)
    assert all(f["ra"] is not None for f in fam)
    assert "Alpha Centauri" in [f["name"] for f in fam]


def test_api_endpoints():
    import server
    c = TestClient(server.app)
    assert c.get("/api/suggest", params={"q": "barn"}).json()[0]["name"] == "Barnard's Star"
    assert len(c.get("/api/famous").json()) == len(names.FAMOUS)
