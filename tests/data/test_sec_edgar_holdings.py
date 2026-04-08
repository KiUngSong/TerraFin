import json

import pytest

from TerraFin.data.providers.corporate.filings.sec_edgar import holdings


def test_load_guru_cik_registry_includes_known_gurus() -> None:
    registry = holdings.load_guru_cik_registry()

    assert registry["Warren Buffett"] == 1067983
    assert registry["Bill Ackman"] == 1336528
    assert registry["Seth Klarman"] == 1061768


def test_load_guru_cik_registry_rejects_duplicate_names(tmp_path) -> None:
    registry_path = tmp_path / "guru_cik.json"
    registry_path.write_text(
        json.dumps(
            {
                "gurus": [
                    {"name": "Example Guru", "cik": 123456},
                    {"name": "Example Guru", "cik": 654321},
                ]
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Duplicate guru name"):
        holdings.load_guru_cik_registry(registry_path)


def test_get_available_gurus_returns_sorted_names(monkeypatch) -> None:
    monkeypatch.setattr(
        holdings,
        "GURU_CIK",
        {
            "Zulu Manager": 3,
            "Alpha Manager": 1,
            "Mike Manager": 2,
        },
    )

    assert holdings.get_available_gurus() == ["Alpha Manager", "Mike Manager", "Zulu Manager"]
