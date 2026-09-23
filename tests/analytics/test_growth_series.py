from TerraFin.analytics.analysis.fundamental.growth import TURNAROUND, build_growth_series


def _payload(columns: list[str], rows: dict[str, list[float | None]]) -> dict:
    """A `financials` payload: columns newest first, as yfinance returns them."""
    return {
        "columns": columns,
        "rows": [{"label": label, "values": dict(zip(columns, values))} for label, values in rows.items()],
    }


ANNUAL = _payload(
    ["2024-12-31", "2023-12-31", "2022-12-31", "2021-12-31"],
    {
        "Total Revenue": [150.0, 120.0, 100.0, 80.0],
        "Diluted EPS": [2.0, 1.0, -0.5, 0.4],
    },
)

QUARTERLY = _payload(
    ["2025-03-31", "2024-12-31", "2024-09-30", "2024-06-30", "2024-03-31", "2023-12-31"],
    {
        "Total Revenue": [44.0, 40.0, 36.0, 32.0, 40.0, 32.0],
        "Net Income": [5.0, -1.0, 3.0, 2.0, 4.0, 2.0],
    },
)


def test_yoy_counts_follow_the_columns():
    result = build_growth_series("TEST", annual=ANNUAL, quarterly=QUARTERLY)

    assert result["counts"] == {
        "annual_columns": 4,
        "annual_revenue_yoy": 3,
        "annual_eps_yoy": 3,
        "quarterly_columns": 6,
        "quarterly_revenue_yoy": 2,
        "quarterly_eps_yoy": 2,
    }


def test_series_run_oldest_first():
    result = build_growth_series("TEST", annual=ANNUAL, quarterly=QUARTERLY)

    assert [p["date"] for p in result["annual_revenue"]] == ["2021-12-31", "2022-12-31", "2023-12-31", "2024-12-31"]
    assert [p["value"] for p in result["annual_revenue_yoy"]] == [25.0, 20.0, 25.0]
    assert [p["date"] for p in result["quarterly_revenue_yoy"]] == ["2024-12-31", "2025-03-31"]
    assert [p["value"] for p in result["quarterly_revenue_yoy"]] == [25.0, 10.0]


def test_loss_to_profit_is_turnaround_and_two_losses_have_no_change():
    result = build_growth_series("TEST", annual=ANNUAL, quarterly=QUARTERLY)

    # 0.4 -> -0.5 is a percent change, -0.5 -> 1.0 is a turnaround, 1.0 -> 2.0 is +100%.
    assert [p["value"] for p in result["annual_eps_yoy"]] == [-225.0, TURNAROUND, 100.0]

    both_losses = _payload(["2025-12-31", "2024-12-31"], {"Diluted EPS": [-1.0, -2.0]})
    assert build_growth_series("TEST", annual=both_losses, quarterly={})["annual_eps_yoy"] == [
        {"date": "2025-12-31", "value": None}
    ]


def test_eps_falls_back_to_net_income_per_table():
    result = build_growth_series("TEST", annual=ANNUAL, quarterly=QUARTERLY)

    assert result["annual_eps_row"] == "Diluted EPS"
    assert result["quarterly_eps_row"] == "Net Income"
    assert [p["value"] for p in result["quarterly_eps_yoy"]] == [-150.0, 25.0]


def test_eps_falls_back_when_diluted_eps_has_no_year_ago_pair():
    partial = _payload(
        QUARTERLY["columns"],
        {
            "Diluted EPS": [0.5, 0.4, 0.3, 0.2, None, None],
            "Net Income": [5.0, 4.0, 3.0, 2.0, 4.0, 2.0],
        },
    )
    result = build_growth_series("TEST", annual={}, quarterly=partial)

    assert result["quarterly_eps_row"] == "Net Income"
    assert result["counts"]["quarterly_eps_yoy"] == 2


def test_a_missing_quarter_is_matched_by_date_not_position():
    # 2024-06-30 is absent, so the column four places back from 2025-03-31 is 2023-12-31.
    gapped = _payload(
        ["2025-03-31", "2024-12-31", "2024-09-30", "2024-03-31", "2023-12-31"],
        {"Total Revenue": [44.0, 40.0, 36.0, 40.0, 32.0]},
    )
    result = build_growth_series("TEST", annual={}, quarterly=gapped)

    assert result["quarterly_revenue_yoy"] == [
        {"date": "2024-12-31", "value": 25.0},
        {"date": "2025-03-31", "value": 10.0},
    ]


def test_missing_tables_give_empty_series():
    result = build_growth_series("TEST", annual={}, quarterly={})

    assert result["annual_revenue"] == []
    assert result["quarterly_eps_yoy"] == []
    assert result["annual_eps_row"] is None
    assert result["counts"]["annual_columns"] == 0
