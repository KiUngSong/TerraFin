"""Market Voices contract — one Mongo doc = one person's market view on one date.

Collection: ``terrafin_status_db.terrafin_market_voices`` (append-only; no
upserts — a correction is a new doc, later ``ingested_at`` wins). Producers
(any repo, any means) write conforming docs; TerraFin renders whatever
conforms and stays dormant for a slug with no data (read-if-present, the
Fear & Greed model). Duplicate ``(slug, as_of)`` docs are legal — readers
dedupe, writers never coordinate.

Fields — nothing else is contract:

==============  ========  =====================================================
``slug``        REQUIRED  stable lowercase id ("mike_wilson"); groups history
``name``        REQUIRED  display name (put the firm here if wanted:
                          "Tom Lee (Fundstrat)")
``as_of``       REQUIRED  source publication date, STRICT "YYYY-MM-DD" STRING —
                          never a BSON Date (the #1 producer trap)
``stance``      REQUIRED  "bullish" | "bearish" | "neutral" (no directional
                          read published -> write no doc)
``thesis``      REQUIRED  the opinion, plain text
``source_url``  optional  http(s) provenance link
``ingested_at`` optional  ISO datetime string; insertion ordering only,
                          never displayed
==============  ========  =====================================================

Unknown extra keys on a doc are ignored by readers, never rendered. The read
path stays dict-defensive and does not construct this class; it exists for
producers (write-time validation) and as the single written statement of the
contract.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Literal


Stance = Literal["bullish", "bearish", "neutral"]

STANCES = ("bullish", "bearish", "neutral")

# Read-gate sanity caps (shared with the panel so producer and reader agree).
NAME_MAX_CHARS = 120
THESIS_MAX_CHARS = 2000


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class MarketView:
    slug: str
    name: str
    as_of: str  # "YYYY-MM-DD"
    stance: str
    thesis: str
    source_url: str = ""
    ingested_at: str = field(default_factory=_now_iso)

    def __post_init__(self) -> None:
        slug = str(self.slug or "").strip().lower()
        if not slug:
            raise ValueError("MarketView.slug must be a non-empty string")
        object.__setattr__(self, "slug", slug)
        name = str(self.name or "").strip()
        if not name or len(name) > NAME_MAX_CHARS:
            raise ValueError(f"MarketView.name must be 1..{NAME_MAX_CHARS} chars")
        object.__setattr__(self, "name", name)
        thesis = str(self.thesis or "").strip()
        if not thesis or len(thesis) > THESIS_MAX_CHARS:
            raise ValueError(f"MarketView.thesis must be 1..{THESIS_MAX_CHARS} chars")
        object.__setattr__(self, "thesis", thesis)
        stance = str(self.stance or "").strip().lower()
        if stance not in STANCES:
            raise ValueError(f"MarketView.stance must be one of {STANCES}, got {self.stance!r}")
        object.__setattr__(self, "stance", stance)
        # Strict 10-char calendar date; a bogus/lexically-large as_of would pin
        # "latest" forever. Producers a timezone ahead of UTC may legitimately
        # stamp "tomorrow" — allow exactly one day of slack, reject beyond.
        as_of = str(self.as_of or "").strip()
        try:
            parsed = date.fromisoformat(as_of)
        except ValueError:
            raise ValueError(f"MarketView.as_of must be a 'YYYY-MM-DD' string, got {self.as_of!r}") from None
        if len(as_of) != 10:
            raise ValueError(f"MarketView.as_of must be exactly 'YYYY-MM-DD', got {self.as_of!r}")
        today = datetime.now(timezone.utc).date()
        if (parsed - today).days > 1:
            raise ValueError(f"MarketView.as_of must not be in the future, got {as_of}")
        object.__setattr__(self, "as_of", as_of)
        url = str(self.source_url or "").strip()
        if url and not url.startswith(("http://", "https://")):
            raise ValueError("MarketView.source_url must be an http(s) URL when present")
        object.__setattr__(self, "source_url", url)
        if not isinstance(self.ingested_at, str) or not self.ingested_at.strip():
            raise ValueError("MarketView.ingested_at must be an ISO datetime string")

    def to_doc(self) -> dict:
        """The persisted document. ``as_of``/``ingested_at`` stay ISO strings so
        lexical recency comparisons never mix types."""
        return {
            "slug": self.slug,
            "name": self.name,
            "as_of": self.as_of,
            "stance": self.stance,
            "thesis": self.thesis,
            "source_url": self.source_url,
            "ingested_at": self.ingested_at,
        }
