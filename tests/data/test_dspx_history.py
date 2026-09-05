"""Dispersion Index is a searchable private-series market indicator (DSPX)."""

from TerraFin.interface.infra.ticker_search.routes import _search_indicators


def test_search_indicators_finds_dispersion_and_dspx():
    by_dispersion = _search_indicators("dispersion")
    by_dspx = _search_indicators("dspx")
    assert any(entry["symbol"] == "Dispersion Index" for entry in by_dispersion)
    assert any(entry["symbol"] == "Dispersion Index" for entry in by_dspx)
    match = next(entry for entry in by_dspx if entry["symbol"] == "Dispersion Index")
    assert match["group"] == "Market"
    assert "DSPX" in match["name"]
