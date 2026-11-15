import pytest

from spherex_data import query


@pytest.fixture(autouse=True)
def _irsa_not_marked_down(monkeypatch):
    """Each test starts with IRSA's search not remembered as down (query._tap_down_until)."""
    monkeypatch.setattr(query, "_tap_down_until", 0.0)
