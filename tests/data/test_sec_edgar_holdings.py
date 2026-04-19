import json

import pytest
from defusedxml.common import EntitiesForbidden

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


_NS = "http://www.sec.gov/edgar/document/thirteenf/informationtable"


def _infotable_xml(rows: list[dict]) -> str:
    entries = "".join(
        f"""
        <infoTable>
            <nameOfIssuer>{row["name"]}</nameOfIssuer>
            <value>{row["value"]}</value>
            <shrsOrPrnAmt>
                <sshPrnamt>{row["shares"]}</sshPrnamt>
            </shrsOrPrnAmt>
        </infoTable>
        """.strip()
        for row in rows
    )
    return f'<?xml version="1.0"?><informationTable xmlns="{_NS}">{entries}</informationTable>'


def test_parse_13f_xml_aggregates_positions() -> None:
    xml = _infotable_xml(
        [
            {"name": "Apple Inc", "value": 1000, "shares": 50},
            {"name": "Apple Inc", "value": 500, "shares": 25},
            {"name": "Nvidia", "value": 2000, "shares": 10},
        ]
    )

    result = holdings._parse_13f_xml(xml)

    assert result["Apple Inc"] == {"value": 1500, "shares": 75}
    assert result["Nvidia"] == {"value": 2000, "shares": 10}


def test_parse_13f_xml_rejects_external_entity_expansion() -> None:
    evil = """<?xml version="1.0"?>
<!DOCTYPE lolz [
  <!ENTITY lol "lol">
  <!ENTITY lol2 "&lol;&lol;&lol;&lol;">
]>
<informationTable xmlns="http://www.sec.gov/edgar/document/thirteenf/informationtable">
  <infoTable><nameOfIssuer>&lol2;</nameOfIssuer><value>1</value>
    <shrsOrPrnAmt><sshPrnamt>1</sshPrnamt></shrsOrPrnAmt>
  </infoTable>
</informationTable>"""

    with pytest.raises(EntitiesForbidden):
        holdings._parse_13f_xml(evil)


def test_parse_13f_xml_skips_malformed_entries(caplog) -> None:
    xml = f"""<?xml version="1.0"?>
<informationTable xmlns="{_NS}">
  <infoTable>
    <nameOfIssuer>Good Co</nameOfIssuer>
    <value>42</value>
    <shrsOrPrnAmt><sshPrnamt>7</sshPrnamt></shrsOrPrnAmt>
  </infoTable>
  <infoTable>
    <nameOfIssuer>Bad Co</nameOfIssuer>
    <value>not-a-number</value>
    <shrsOrPrnAmt><sshPrnamt>7</sshPrnamt></shrsOrPrnAmt>
  </infoTable>
  <infoTable>
    <nameOfIssuer></nameOfIssuer>
    <value>100</value>
    <shrsOrPrnAmt><sshPrnamt>1</sshPrnamt></shrsOrPrnAmt>
  </infoTable>
</informationTable>"""

    with caplog.at_level("WARNING", logger=holdings.log.name):
        result = holdings._parse_13f_xml(xml)

    assert result == {"Good Co": {"value": 42, "shares": 7}}
    assert any("Skipped 2" in record.message for record in caplog.records)


def test_parse_13f_xml_raises_on_malformed_xml() -> None:
    with pytest.raises(ValueError, match="Malformed 13F XML"):
        holdings._parse_13f_xml("<not xml>")


def test_iter_13f_from_block_handles_misaligned_columns(caplog) -> None:
    block = {
        "form": ["13F-HR", "10-K", "13F-HR", "13F-HR/A"],
        "accessionNumber": ["a1", "a2", "a3"],  # one short
        "filingDate": ["2025-01-01", "2025-02-01", "2025-03-01", "2025-04-01"],
    }

    with caplog.at_level("WARNING", logger=holdings.log.name):
        pairs = holdings._iter_13f_from_block(block)

    assert pairs == [("a1", "2025-01-01"), ("a3", "2025-03-01")]
    assert any("misaligned" in record.message for record in caplog.records)


def test_iter_13f_from_block_tolerates_missing_keys() -> None:
    assert holdings._iter_13f_from_block({}) == []
