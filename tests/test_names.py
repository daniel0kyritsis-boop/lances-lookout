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
    fam = c.get("/api/famous").json()                  # only stars whose frames are built
    assert len(fam) <= len(names.FAMOUS)
    assert all(server._ready(s["query"]) for s in fam)


def test_breaker_skips_irsa_after_a_failure(tmp_path, monkeypatch):
    import json
    import pytest
    from spherex_data import config, query
    monkeypatch.setattr(config, "CACHE_DIR", tmp_path)
    calls = []

    def down(_):
        calls.append(1)
        raise RuntimeError("502")

    with pytest.raises(RuntimeError):
        query.find_images(5, 6, [2], _tap=down)
    with pytest.raises(ConnectionError):               # not asked again straight away
        query.find_images(5, 6, [2], _tap=down)
    assert len(calls) == 1
    p = query._cache_path(5, 6, [5])
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps([{"uri": "u", "mjd": 1.0, "bandpass": "SPHEREx-D5", "detector": 5}]))
    got = query.find_images(5, 6, None, _tap=down, partial_ok=True)   # partial cache accepted
    assert [r.detector for r in got] == [5]
