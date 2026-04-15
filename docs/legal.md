---
title: License & Data Rights
summary: TerraFin's MIT license applies to the software only; upstream data remains governed by provider-specific terms.
---

# License & Data Rights

TerraFin is MIT-licensed open-source software, and the MIT license applies to
the software only.

It does **not** grant any right to third-party data, content, trademarks, or
services accessed through this project. TerraFin is not affiliated with or
endorsed by any upstream data provider unless explicitly stated.

## What This Means In Practice

TerraFin may access multiple source families, including:

- Yahoo-derived data via `yfinance`
- SEC EDGAR
- FRED
- news headlines
- user-operated private endpoints

Rights to the actual data remain subject to the applicable provider terms,
licenses, and law. Depending on the source, personal, public, automated,
cached, redistributed, or commercial use of upstream data may be restricted or
prohibited.

## Operator Responsibility

Anyone operating a public deployment of TerraFin is responsible for:

- the sources they enable
- any connected private API
- the privacy and compliance posture of that service

Authentication, caching, or proxying do not create rights to upstream data.
End users are responsible only for their own downstream copying, scraping,
caching, redistribution, or other reuse of displayed data.

## Public Demo Note

The maintainer-operated public demo Space at
`https://huggingface.co/spaces/sk851/TerraFin` is a public TerraFin deployment.
Access to that demo does not create any right to upstream data.

## Related Docs

- [Data Layer](data-layer.md)
- [Deployment & Operations](deployment.md)
- [README on GitHub](https://github.com/KiUngSong/TerraFin/blob/main/README.md)
