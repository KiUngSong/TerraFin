"""Custom chart indicators — spec registry + generic executor.

A spec is one JSON dict; specs merge by name (later wins) from a local
``default_indicators.json`` < Mongo ``market_data.indicator_specs`` < local
``indicators.json``. See docs/chart-architecture.md → "Custom indicators".
"""

import json
import logging
import os
import re
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from TerraFin.env import resolve_state_dir


log = logging.getLogger(__name__)

try:
    from pymongo import MongoClient
except ImportError:  # pragma: no cover - optional dependency at runtime
    MongoClient = None


INDICATORS_PATH_ENV = "TERRAFIN_INDICATORS_PATH"
DEFAULT_INDICATORS_FILENAME = "indicators.json"

# Mongo meta-collection holding user-defined specs (one doc per spec).
_SPECS_DATABASE = "market_data"
_SPECS_COLLECTION = "indicator_specs"

# Lazily-built shared client, cached process-wide. A fresh MongoClient per
# read pays the full Atlas mongodb+srv cost every time (SRV DNS + TLS
# handshake + server selection ~1-2s) — the watchlist / market-voices stores
# avoid this by reusing one client, and so do we.
_client = None

# Mongo spec-layer cache: (fetched_at_monotonic, docs). Specs change rarely,
# but the chart search endpoint calls the loader per keystroke — an uncached
# read would pay one Atlas round trip (or a 3s server-selection timeout when
# the cluster is unreachable) on every request.
_MONGO_SPECS_TTL_SECONDS = 60.0
_mongo_specs_cache = None


def _get_client():
    global _client
    if _client is not None:
        return _client
    if MongoClient is None:
        return None
    from TerraFin.configuration import load_terrafin_config

    # Shared cluster URI (TERRAFIN_MONGODB_URI or MONGODB_URI), same as the stores.
    uri = load_terrafin_config().market_voices.uri
    if not uri:
        return None
    _client = MongoClient(uri, serverSelectionTimeoutMS=3000)
    return _client


@dataclass(frozen=True)
class MongoSource:
    """Where a spec's rows live and how they map onto chart points."""

    database: str
    collection: str
    time_field: str
    value_field: str | None  # line specs: the single value column
    fields: dict[str, str] | None  # band specs: output key -> source field
    filter: dict


@dataclass(frozen=True)
class IndicatorSpec:
    name: str
    description: str
    group: str
    series_type: str  # "line" | "band"
    source: MongoSource
    price_scale_id: str


def _load_default_specs() -> list[dict]:
    # No shipped defaults in the open-core repo; a user may drop one in locally.
    path = Path(__file__).parent / "default_indicators.json"
    if not path.is_file():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, list) else []
    except Exception:
        log.warning("indicator specs: failed to read %s", path, exc_info=True)
        return []


DEFAULT_SPECS: list[dict] = _load_default_specs()


def _derived_price_scale_id(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _parse_spec(raw) -> IndicatorSpec:
    """Validate one raw spec dict; raises ValueError on any contract violation."""
    if not isinstance(raw, dict):
        raise ValueError(f"spec must be a dict, got {type(raw).__name__}")
    name = str(raw.get("name") or "").strip()
    if not name:
        raise ValueError("spec is missing a name")
    if "::" in name:
        # The frontend expands band items into layers keyed "<name>::pos|neu|neg"
        # and routes tooltips on that separator — a literal "::" in a spec name
        # would silently break tooltip attribution.
        raise ValueError(f"{name}: spec names must not contain '::'")
    # NOTE: spec names take precedence over ticker symbols in the add path — a
    # spec named "SPY" would shadow the ticker. Intentional (registry override),
    # but pick distinctive names.
    series_type = raw.get("series_type")
    if series_type not in ("line", "band"):
        raise ValueError(f"{name}: series_type must be 'line' or 'band', got {series_type!r}")
    source = raw.get("source")
    if not isinstance(source, dict):
        raise ValueError(f"{name}: source must be a dict")
    if source.get("kind") != "mongo":
        raise ValueError(f"{name}: unsupported source kind {source.get('kind')!r}")
    database = str(source.get("database") or "").strip()
    collection = str(source.get("collection") or "").strip()
    time_field = str(source.get("time_field") or "").strip()
    if not (database and collection and time_field):
        raise ValueError(f"{name}: source requires database, collection and time_field")
    value_field = source.get("value_field")
    fields = source.get("fields")
    if series_type == "line":
        if not value_field or fields:
            raise ValueError(f"{name}: line specs require value_field (and no fields)")
        value_field = str(value_field)
        fields = None
    else:
        if not fields or value_field:
            raise ValueError(f"{name}: band specs require fields (and no value_field)")
        if not isinstance(fields, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in fields.items()
        ):
            raise ValueError(f"{name}: fields must map output keys to source field names")
        # The whole band pipeline (backend _resample_band, frontend bandAreaSpecs)
        # is keyed to exactly pos/neu/neg — any other keys would load "valid" and
        # then break rendering. Reject at parse time so a bad user spec degrades
        # to a skipped spec instead of a blank chart. Relax if/when the frontend
        # generalizes band keys.
        if set(fields.keys()) != {"pos", "neu", "neg"}:
            raise ValueError(f"{name}: band fields keys must be exactly pos/neu/neg")
        value_field = None
    spec_filter = source.get("filter") or {}
    if not isinstance(spec_filter, dict):
        raise ValueError(f"{name}: filter must be a dict")
    price_scale_id = str(raw.get("price_scale_id") or "").strip() or _derived_price_scale_id(name)
    return IndicatorSpec(
        name=name,
        description=str(raw.get("description") or ""),
        group=str(raw.get("group") or "Custom"),
        series_type=series_type,
        source=MongoSource(
            database=database,
            collection=collection,
            time_field=time_field,
            value_field=value_field,
            fields=fields,
            filter=spec_filter,
        ),
        price_scale_id=price_scale_id,
    )


def _mongo_spec_docs() -> list[dict]:
    """Specs from the Mongo meta-collection; [] when unconfigured/unreachable."""
    global _client, _mongo_specs_cache
    now = time.monotonic()
    if _mongo_specs_cache is not None and now - _mongo_specs_cache[0] < _MONGO_SPECS_TTL_SECONDS:
        return _mongo_specs_cache[1]
    client = _get_client()
    if client is None:
        docs: list[dict] = []
    else:
        try:
            docs = list(client[_SPECS_DATABASE][_SPECS_COLLECTION].find({}, {"_id": 0}))
        except Exception:
            log.warning("indicator specs: Mongo read failed", exc_info=True)
            _client = None  # drop a broken client so the next call rebuilds it
            docs = []
    _mongo_specs_cache = (now, docs)
    return docs


def resolve_indicators_path(env: Mapping[str, str] | None = None) -> Path:
    source = env if env is not None else os.environ
    explicit = str(source.get(INDICATORS_PATH_ENV, "") or "").strip()
    if explicit:
        return Path(explicit).expanduser()
    return resolve_state_dir(env) / DEFAULT_INDICATORS_FILENAME


def _local_spec_docs(env: Mapping[str, str] | None = None) -> list:
    """Specs from the local JSON file; [] when missing or unreadable."""
    path = resolve_indicators_path(env)
    if not path.is_file():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        log.warning("indicator specs: failed to read %s", path, exc_info=True)
        return []
    if not isinstance(raw, list):
        log.warning("indicator specs: %s must contain a JSON list; ignoring it", path)
        return []
    return raw


def load_custom_indicators(env: Mapping[str, str] | None = None) -> dict[str, IndicatorSpec]:
    """The merged spec registry: defaults < Mongo < local JSON, later wins by name.

    Invalid specs are skipped with a warning; loading never raises.
    """
    specs: dict[str, IndicatorSpec] = {}
    for layer, raws in (
        ("default", DEFAULT_SPECS),
        ("mongo", _mongo_spec_docs()),
        ("local", _local_spec_docs(env)),
    ):
        for raw in raws:
            try:
                spec = _parse_spec(raw)
            except ValueError:
                log.warning("indicator specs: skipping invalid %s-layer spec", layer, exc_info=True)
                continue
            specs[spec.name] = spec
    return specs


def _spec_rows(spec: IndicatorSpec) -> list[dict]:
    """Run the spec's Mongo query. Returns [] on any failure so an add
    degrades to an empty series rather than erroring."""
    global _client
    client = _get_client()
    if client is None:
        return []
    src = spec.source
    projection = {"_id": 0, src.time_field: 1}
    if src.value_field is not None:
        projection[src.value_field] = 1
    else:
        for field_name in (src.fields or {}).values():
            projection[field_name] = 1
    try:
        coll = client[src.database][src.collection]
        return list(coll.find(src.filter, projection).sort(src.time_field, 1))
    except Exception:
        log.warning("custom indicator %r: Mongo read failed", spec.name, exc_info=True)
        _client = None  # drop a broken client so the next call rebuilds it
        return []


def build_custom_indicator(spec: IndicatorSpec) -> dict:
    """Build the formatted ChartSeries item for one spec.

    Line: ``{"time", "value"}`` points (overlay-scale line, like any indicator).
    Band: ``{"time", <fields keys>}`` points on its own pane; the renderer stacks
    them into cumulative [0,1] areas (band layers are keyed pos/neu/neg).
    """
    src = spec.source
    rows = _spec_rows(spec)
    if src.value_field is not None:
        data = [{"time": str(r[src.time_field]), "value": float(r[src.value_field])} for r in rows]
    else:
        data = [
            {"time": str(r[src.time_field]), **{key: float(r[f]) for key, f in (src.fields or {}).items()}}
            for r in rows
        ]
    item = {
        "id": spec.name,
        "seriesType": spec.series_type,
        "data": data,
        # indicator:True would need an indicatorGroup or the ChartCanvas filter drops it.
        "indicator": False,
        "description": spec.description,  # feeds the legend info button
    }
    if spec.series_type == "band":
        # Only the band earns its own pane/scale (ownScale). A line leaves its
        # scale unset so the layout pass gives it a hidden overlay, like any
        # other line indicator.
        item["priceScaleId"] = spec.price_scale_id
        item["ownScale"] = True
    return item
