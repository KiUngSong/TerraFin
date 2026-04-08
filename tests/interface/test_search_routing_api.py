from fastapi.testclient import TestClient

from TerraFin.interface.server import create_app


def test_resolve_ticker_routes_lowercase_index_to_market_insights() -> None:
    client = TestClient(create_app())

    response = client.get("/resolve-ticker?q=kospi")
    assert response.status_code == 200
    payload = response.json()

    assert payload == {
        "type": "macro",
        "name": "Kospi",
        "path": "/market-insights?ticker=Kospi",
    }


def test_resolve_ticker_routes_indicator_to_market_insights() -> None:
    client = TestClient(create_app())

    response = client.get("/resolve-ticker?q=fear%20%26%20greed")
    assert response.status_code == 200
    payload = response.json()

    assert payload == {
        "type": "macro",
        "name": "Fear & Greed",
        "path": "/market-insights?ticker=Fear & Greed",
    }


def test_resolve_ticker_routes_net_breadth_to_market_insights() -> None:
    client = TestClient(create_app())

    response = client.get("/resolve-ticker?q=net%20breadth")
    assert response.status_code == 200
    payload = response.json()

    assert payload == {
        "type": "macro",
        "name": "Net Breadth",
        "path": "/market-insights?ticker=Net Breadth",
    }
