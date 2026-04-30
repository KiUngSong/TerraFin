---
title: Private Data Wire Spec
summary: HTTP wire format spoken between TerraFin and the sibling DataFactory server, contract by contract.
read_when:
  - Adding or modifying a sibling DataFactory endpoint that TerraFin consumes
  - Removing a provider-specific normalizer from `private_access/client.py`
  - Debugging a payload mismatch between TerraFin and DataFactory
  - Bumping the wire-format version
---

# Private Data Wire Spec

This document fixes the JSON shape exchanged between the sibling DataFactory
server and TerraFin's `private_access` client. Each section maps one TerraFin
contract (see [Data Acquisition Layer](./data-layer.md)) to its canonical wire
form.

The goal is a 1:1 mapping: the sibling server emits payloads that TerraFin can
deserialize directly into a contract object, with no provider-specific
normalization on the client side.

## Versioning

Clients send `Accept-Version: 1` on every request. The sibling echoes the
version it served back in the `Content-Version` response header. Future
breaking changes bump this integer; additive changes (new optional fields)
stay on the current version.

## Error format

Errors use FastAPI's default shape:

```json
{ "detail": "Unknown private series: foo" }
```

HTTP status codes carry the semantic (404 for unknown series, 502 for
upstream-fetch failures, etc.).

## TimeSeriesDataFrame

Used for every chartable scalar series (CAPE, fear/greed history, net breadth
history, P/E spread history).

```json
{
  "series_name": "CAPE",
  "records": [
    {"time": "2025-01-01", "close": 31.2},
    {"time": "2025-02-01", "close": 31.5}
  ]
}
```

- `time` is ISO 8601 — date (`YYYY-MM-DD`) or datetime. Month-only data
  uses `YYYY-MM-01` (canonical first-of-month).
- `close` is the canonical numeric value. Provider-specific column names
  (`cape`, `score`, `value`, `breadth_pct`, …) are not emitted under those
  names on this contract.
- Optional per-record fields: `open`, `high`, `low`, `volume` for OHLCV
  series. Omit when not applicable; do not send `null`.

### Transition compatibility

Legacy provider-shaped keys (`date`, `cape`, `score`, `as_of_date`,
`breadth_pct`, `value`, plus envelope keys `key`, `name`, `data`, `count`) are
no longer emitted. Each record carries `time` + `close` only; the envelope is
`{series_name, records}`. TerraFin's `private_access` client deserializes the
canonical shape directly with no normalizer callbacks.

## IndicatorSnapshot

Used for "current value" cards (fear/greed current, breadth latest, etc.). The
sibling derives `change`, `change_pct`, and `rating` server-side from the data
it already has.

```json
{
  "name": "Fear & Greed",
  "value": 42,
  "as_of": "2026-04-29",
  "rating": "Fear",
  "change": -3.2,
  "change_pct": -7.1,
  "unit": null,
  "metadata": {}
}
```

- `value` is numeric.
- `as_of` is ISO 8601 date or datetime.
- `rating`, `change`, `change_pct`, `unit` are optional (`null` when not
  available).
- `metadata` is a free-form object for non-canonical extras.

Endpoint convention: `/private-series/<key>/current`.

## EventList

Used for calendar / earnings / FOMC-style streams.

```json
{
  "events": [
    {
      "id": "macro-1-2026-04-29-1",
      "title": "FOMC Statement",
      "start": "2026-04-29T18:00:00+00:00",
      "category": "fed",
      "importance": "high",
      "display_time": "14:00 ET",
      "description": null,
      "source": "FRED",
      "metadata": {}
    }
  ]
}
```

- `start` MUST be timezone-aware ISO 8601. Fall back to UTC if no tz is
  available upstream.
- `display_time` is a human-presentation string and is always separate from
  `start`.
- `importance`, `description`, `metadata` are optional.

## FilingDocument, FinancialStatementFrame, PortfolioOutput

These contracts are served by TerraFin's own providers (SEC EDGAR, yfinance
fundamentals, 13F holdings) and do **not** flow over the sibling HTTP boundary
today. They are documented here so a future sibling endpoint that exposes them
ships in the canonical shape from day one.

### FilingDocument

```json
{
  "accession": "0000320193-25-000010",
  "form": "10-K",
  "filed": "2025-11-02",
  "period_end": "2025-09-28",
  "title": "Apple Inc. annual report",
  "url": "https://www.sec.gov/...",
  "metadata": {}
}
```

### FinancialStatementFrame

```json
{
  "statement": "income",
  "ticker": "AAPL",
  "currency": "USD",
  "rows": [
    {"period": "2025-09-28", "metric": "revenue", "value": 391000000000}
  ],
  "metadata": {}
}
```

`period` is ISO 8601, `metric` is the canonical TerraFin metric key, `value`
is numeric in `currency`.

### PortfolioOutput

```json
{
  "filer_cik": "0001067983",
  "as_of": "2025-09-30",
  "holdings": [
    {"ticker": "AAPL", "shares": 915560382, "value_usd": 178473128000.0}
  ],
  "metadata": {}
}
```
