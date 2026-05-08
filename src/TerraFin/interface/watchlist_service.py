import logging
import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import Lock
from zoneinfo import ZoneInfo

from TerraFin.configuration import WatchlistConfig, load_terrafin_config


log = logging.getLogger(__name__)


# Per-region close + post-close buffer for the watchlist move-% refresh.
# The scheduler converts each (close_hour, close_minute, tz) → next UTC
# fire on every loop iteration so DST flips fall out for free. The hour
# of "close + 1h" gives yfinance time to publish the EOD bar.
_REFRESH_REGIONS = [
    {"label": "KRX", "tz": "Asia/Seoul", "close_hour": 15, "close_minute": 30, "buffer_minutes": 60},
    {"label": "NYSE", "tz": "America/New_York", "close_hour": 16, "close_minute": 0, "buffer_minutes": 60},
]


def _enabled() -> bool:
    return os.environ.get("TERRAFIN_WATCHLIST_REFRESH_ENABLED", "1") not in ("0", "false", "False")


def _per_symbol_sleep_seconds() -> float:
    raw = os.environ.get("TERRAFIN_WATCHLIST_PER_SYMBOL_SLEEP_SEC")
    if not raw:
        return 0.2
    try:
        return max(float(raw), 0.0)
    except ValueError:
        return 0.2


def _next_fire_at_utc(now_utc: datetime) -> tuple[datetime, str]:
    """Compute the next refresh fire time across all regions, returning
    (fire_at_utc, region_label). Each region's fire time is "close +
    buffer" expressed in its own tz; if today's slot already passed,
    advance to tomorrow's. Pick the earliest across regions."""
    candidates: list[tuple[datetime, str]] = []
    for region in _REFRESH_REGIONS:
        tz = ZoneInfo(region["tz"])
        now_local = now_utc.astimezone(tz)
        target_local = now_local.replace(
            hour=region["close_hour"],
            minute=region["close_minute"],
            second=0,
            microsecond=0,
        ) + timedelta(minutes=region["buffer_minutes"])
        if target_local <= now_local:
            target_local = target_local + timedelta(days=1)
        candidates.append((target_local.astimezone(timezone.utc), region["label"]))
    return min(candidates, key=lambda c: c[0])


def _previous_fire_at_utc(now_utc: datetime) -> datetime:
    """Most recent passed slot across all regions — used at boot to
    decide whether a catch-up fire is needed (we missed a slot while
    the process was down)."""
    passed: list[datetime] = []
    for region in _REFRESH_REGIONS:
        tz = ZoneInfo(region["tz"])
        now_local = now_utc.astimezone(tz)
        target_local = now_local.replace(
            hour=region["close_hour"],
            minute=region["close_minute"],
            second=0,
            microsecond=0,
        ) + timedelta(minutes=region["buffer_minutes"])
        if target_local > now_local:
            target_local = target_local - timedelta(days=1)
        passed.append(target_local.astimezone(timezone.utc))
    return max(passed)


try:
    from pymongo import MongoClient
except ImportError:  # pragma: no cover - optional dependency at runtime
    MongoClient = None

from TerraFin.data.providers.private_access.fallbacks import get_watchlist_fallback


class WatchlistError(ValueError):
    """Base error for local watchlist operations."""


class WatchlistValidationError(WatchlistError):
    """Raised when a ticker symbol is invalid."""


class WatchlistConfigurationError(WatchlistError):
    """Raised when the MongoDB backend is not configured."""


class WatchlistConflictError(WatchlistError):
    """Raised when a symbol already exists in the watchlist."""


class WatchlistNotFoundError(WatchlistError):
    """Raised when a symbol is missing from the watchlist."""


@dataclass
class WatchlistItemRecord:
    symbol: str
    name: str
    move: str
    tags: list[str] = None  # type: ignore[assignment]
    move_refreshed_at: str | None = None

    def __post_init__(self) -> None:
        if self.tags is None:
            self.tags = []

    def to_dict(self) -> dict:
        out: dict = {"symbol": self.symbol, "name": self.name, "move": self.move, "tags": list(self.tags)}
        if self.move_refreshed_at:
            out["move_refreshed_at"] = self.move_refreshed_at
        return out


WatchlistMongoConfig = WatchlistConfig


def _load_watchlist_mongo_config() -> WatchlistMongoConfig:
    return load_terrafin_config().watchlist


# Reserved tags carry behavior, not group membership. They are stored as
# regular tag strings so we don't add a new schema field, but the groups
# API filters them out so they never appear as user-managed groups.
_RESERVED_TAGS: set[str] = {"monitor"}


def is_reserved_tag(tag: str) -> bool:
    return str(tag or "").strip().lower() in _RESERVED_TAGS


def _normalize_tags(tags: list) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for t in tags:
        text = str(t or "").strip()
        key = text.lower()
        if key and key not in seen:
            seen.add(key)
            result.append(text)
    return result


def _normalize_symbol(symbol: str) -> str:
    text = str(symbol or "").strip().upper()
    return "".join(char for char in text if char not in {" ", "\t", "\n", "\r"})


def _normalize_move(move: object) -> str:
    text = str(move or "").strip()
    return text or "--"


def _normalize_name(name: object, *, symbol: str) -> str:
    text = str(name or "").strip()
    return text or symbol


def _resolve_company_name(symbol: str) -> str:
    from TerraFin.data.providers.market.ticker_info import get_ticker_info

    info = get_ticker_info(symbol)
    return str(info.get("shortName") or info.get("longName") or symbol).strip() or symbol


def _bust_ticker_info_cache(symbol: str) -> None:
    try:
        from TerraFin.data.cache.registry import get_cache_manager
        get_cache_manager().refresh_payload(f"market.ticker_info.{symbol}")
    except Exception:
        pass


def _format_move_from_history(symbol: str) -> str:
    from TerraFin.data.providers.market.ticker_info import get_ticker_info
    info = get_ticker_info(symbol) or {}
    current = info.get("currentPrice") or info.get("regularMarketPrice")
    prev_close = info.get("previousClose") or info.get("regularMarketPreviousClose")
    if not current or not prev_close or prev_close == 0:
        return "--"
    move_pct = ((current / prev_close) - 1.0) * 100.0
    return f"{move_pct:+.2f}%"


class WatchlistService:
    def __init__(self, config: WatchlistMongoConfig) -> None:
        self.config = config
        self._lock = Lock()
        self._client = None
        self._items: list[dict] | None = None
        self._explicit_groups: list[str] | None = None
        self._group_order: list[str] | None = None
        self._item_order: dict[str, list[str]] | None = None
        self._backend_unavailable = False

    def get_watchlist_snapshot(self, group: str | None = None) -> list[dict]:
        if self._items is None:
            self.refresh_snapshot()
        items = [dict(item) for item in (self._items or [])]
        if group:
            tag = group.strip().lower()
            items = [item for item in items if tag in [t.lower() for t in item.get("tags", [])]]
            # Apply per-group item ordering (lazy: items not in order appended at end).
            order = (self._item_order or {}).get(group) or (self._item_order or {}).get(tag) or []
            if order:
                sym_map = {i["symbol"]: i for i in items}
                ordered = [sym_map.pop(s) for s in order if s in sym_map]
                ordered.extend(sym_map.values())
                items = ordered
        return items

    def refresh_all_moves(self) -> int:
        """Recompute the daily move % for every stored symbol and
        persist back to Mongo. Returns the count of items whose move
        actually changed (skip-write-if-unchanged).

        Each item gets ``move_refreshed_at`` set to the current UTC
        ISO timestamp on EVERY successful fetch — even when the value
        didn't change — so the UI can surface "data verified at HH:MM
        local". The Mongo doc is rewritten only when at least one
        ``move`` flipped, but the in-memory ``_items`` cache always
        gets the new timestamps so reads see them.
        """
        if not self._is_backend_available():
            return 0
        sleep_between = _per_symbol_sleep_seconds()
        with self._lock:
            items = self._load_items_locked()
            if not items:
                return 0
            updated = 0
            now_iso = datetime.now(timezone.utc).isoformat()
            for idx, item in enumerate(items):
                symbol = item.get("symbol")
                if not symbol:
                    continue
                try:
                    _bust_ticker_info_cache(symbol)
                    fresh = _format_move_from_history(symbol)
                except Exception:
                    log.exception("watchlist move recompute failed for %s", symbol)
                    continue
                item["move_refreshed_at"] = now_iso
                if item.get("move") != fresh:
                    item["move"] = fresh
                    updated += 1
                if sleep_between and idx < len(items) - 1:
                    time.sleep(sleep_between)
            self._write_items_locked(items)
            self._items = items
            log.info(
                "watchlist move refresh: %d/%d move-flipped, %d total verified",
                updated, len(items), len(items),
            )
            return updated

    def latest_refresh_at_utc(self) -> datetime | None:
        """Most recent ``move_refreshed_at`` across all stored items.
        ``None`` if the field is missing everywhere — used by the boot
        catch-up path to decide if a fire is overdue.
        """
        if self._items is None:
            self.refresh_snapshot()
        latest: datetime | None = None
        for item in self._items or []:
            stamp = item.get("move_refreshed_at")
            if not stamp:
                continue
            try:
                parsed = datetime.fromisoformat(stamp)
            except ValueError:
                continue
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            if latest is None or parsed > latest:
                latest = parsed
        return latest


    def is_backend_configured(self) -> bool:
        return self._is_backend_available()

    def refresh_snapshot(self) -> None:
        with self._lock:
            self._items = self._load_items_locked()

    def clear_cache(self) -> None:
        with self._lock:
            self._items = None

    def add_symbol(self, symbol: str, tags: list[str] | None = None) -> list[dict]:
        normalized = _normalize_symbol(symbol)
        if not normalized:
            raise WatchlistValidationError("Ticker symbol is required.")
        self._require_backend_configured()

        item = self._build_item(normalized, tags=tags)
        with self._lock:
            items = self._load_items_locked()
            if any(existing["symbol"] == normalized for existing in items):
                raise WatchlistConflictError(f"{normalized} is already in the watchlist.")
            items.append(item)
            self._write_items_locked(items)
            self._items = items
            return [dict(entry) for entry in items]

    def replace_symbols(self, symbols: list[str] | list[dict]) -> list[dict]:
        self._require_backend_configured()
        seen: set[str] = set()
        normalized_entries: list[tuple[str, list[str]]] = []
        for entry in symbols:
            if isinstance(entry, dict):
                symbol = _normalize_symbol(str(entry.get("symbol") or ""))
                tags = _normalize_tags(entry.get("tags") or [])
            else:
                symbol = _normalize_symbol(str(entry))
                tags = []
            if not symbol or symbol in seen:
                continue
            seen.add(symbol)
            normalized_entries.append((symbol, tags))

        items = [self._build_item(symbol, tags=tags) for symbol, tags in normalized_entries]
        with self._lock:
            self._write_items_locked(items)
            self._items = items
            return [dict(entry) for entry in items]

    def remove_symbol(self, symbol: str) -> list[dict]:
        normalized = _normalize_symbol(symbol)
        if not normalized:
            raise WatchlistValidationError("Ticker symbol is required.")
        self._require_backend_configured()

        with self._lock:
            items = self._load_items_locked()
            filtered = [item for item in items if item["symbol"] != normalized]
            if len(filtered) == len(items):
                raise WatchlistNotFoundError(f"{normalized} is not in the watchlist.")
            self._write_items_locked(filtered)
            self._items = filtered
            return [dict(entry) for entry in filtered]

    def set_tags(self, symbol: str, tags: list[str]) -> list[dict]:
        normalized = _normalize_symbol(symbol)
        if not normalized:
            raise WatchlistValidationError("Ticker symbol is required.")
        self._require_backend_configured()

        normalized_tags = _normalize_tags(tags)
        with self._lock:
            items = self._load_items_locked()
            found = False
            for item in items:
                if item["symbol"] == normalized:
                    item["tags"] = normalized_tags
                    found = True
                    break
            if not found:
                raise WatchlistNotFoundError(f"{normalized} is not in the watchlist.")
            self._write_items_locked(items)
            self._items = items
            return [dict(entry) for entry in items]

    def add_tags(self, symbol: str, tags: list[str]) -> list[dict]:
        normalized = _normalize_symbol(symbol)
        if not normalized:
            raise WatchlistValidationError("Ticker symbol is required.")
        self._require_backend_configured()

        with self._lock:
            items = self._load_items_locked()
            found = False
            for item in items:
                if item["symbol"] == normalized:
                    existing = item.get("tags") or []
                    item["tags"] = _normalize_tags(existing + list(tags))
                    found = True
                    break
            if not found:
                raise WatchlistNotFoundError(f"{normalized} is not in the watchlist.")
            self._write_items_locked(items)
            self._items = items
            return [dict(entry) for entry in items]

    def remove_tags(self, symbol: str, tags: list[str]) -> list[dict]:
        normalized = _normalize_symbol(symbol)
        if not normalized:
            raise WatchlistValidationError("Ticker symbol is required.")
        self._require_backend_configured()

        drop = {t.strip().lower() for t in tags if t}
        with self._lock:
            items = self._load_items_locked()
            found = False
            for item in items:
                if item["symbol"] == normalized:
                    item["tags"] = [t for t in (item.get("tags") or []) if t.lower() not in drop]
                    found = True
                    break
            if not found:
                raise WatchlistNotFoundError(f"{normalized} is not in the watchlist.")
            self._write_items_locked(items)
            self._items = items
            return [dict(entry) for entry in items]

    def rename_group(self, old: str, new: str) -> list[dict]:
        old_key = old.strip().lower()
        new_tag = new.strip()
        if not old_key or not new_tag:
            raise WatchlistValidationError("Group name is required.")
        self._require_backend_configured()

        with self._lock:
            items = self._load_items_locked()
            for item in items:
                existing = item.get("tags") or []
                if old_key in [t.lower() for t in existing]:
                    updated = [new_tag if t.lower() == old_key else t for t in existing]
                    item["tags"] = _normalize_tags(updated)
            eg = list(self._explicit_groups or [])
            self._explicit_groups = [new_tag if e.lower() == old_key else e for e in eg]
            self._group_order = [new_tag if g.lower() == old_key else g for g in (self._group_order or [])]
            io = dict(self._item_order or {})
            if old_key in io:
                io[new_tag] = io.pop(old_key)
            else:
                # Try case-insensitive key match
                for k in list(io):
                    if k.lower() == old_key:
                        io[new_tag] = io.pop(k)
                        break
            self._item_order = io
            self._write_items_locked(items)
            self._items = items
            return [dict(entry) for entry in items]

    def list_groups(self) -> list[dict]:
        # Hold the lock for the full read so _items, _explicit_groups, and
        # _group_order are always observed from the same consistent write.
        with self._lock:
            items = self._load_items_locked()
            counts: dict[str, int] = {}
            for item in items:
                for tag in item.get("tags") or []:
                    if is_reserved_tag(tag):
                        continue
                    counts[tag] = counts.get(tag, 0) + 1
            for eg in (self._explicit_groups or []):
                if not is_reserved_tag(eg) and eg not in counts:
                    counts[eg] = 0
            # Apply group_order; unordered groups appended alphabetically at end.
            go = [g for g in (self._group_order or []) if g in counts]
            remaining = sorted(k for k in counts if k not in go)
            ordered_keys = go + remaining
            return [{"tag": tag, "count": counts[tag]} for tag in ordered_keys]

    def reorder_groups(self, group_names: list[str]) -> list[dict]:
        self._require_backend_configured()
        with self._lock:
            items = self._load_items_locked()
            self._group_order = [g.strip() for g in group_names if g.strip()]
            self._write_items_locked(items)
            self._items = items
            return [dict(i) for i in items]

    def reorder_items(self, group: str, symbol_order: list[str]) -> list[dict]:
        self._require_backend_configured()
        with self._lock:
            items = self._load_items_locked()
            io = dict(self._item_order or {})
            io[group] = [s.strip() for s in symbol_order if s.strip()]
            self._item_order = io
            self._write_items_locked(items)
            self._items = items
            return [dict(i) for i in items]

    def create_group(self, name: str) -> list[dict]:
        tag = name.strip()
        if not tag:
            raise WatchlistValidationError("Group name is required.")
        if is_reserved_tag(tag):
            raise WatchlistValidationError(f"'{tag}' is a reserved name.")
        self._require_backend_configured()
        with self._lock:
            items = self._load_items_locked()
            eg = list(self._explicit_groups or [])
            if tag.lower() not in [e.lower() for e in eg]:
                eg.append(tag)
                self._explicit_groups = eg
            self._write_items_locked(items)
            self._items = items
            return [dict(i) for i in items]

    def delete_group(self, name: str) -> list[dict]:
        tag_key = name.strip().lower()
        if not tag_key:
            raise WatchlistValidationError("Group name is required.")
        if is_reserved_tag(tag_key):
            raise WatchlistValidationError(f"'{name}' is a reserved group.")
        self._require_backend_configured()
        with self._lock:
            items = self._load_items_locked()
            for item in items:
                item["tags"] = [t for t in (item.get("tags") or []) if t.lower() != tag_key]
            self._explicit_groups = [e for e in (self._explicit_groups or []) if e.lower() != tag_key]
            self._group_order = [g for g in (self._group_order or []) if g.lower() != tag_key]
            self._item_order = {k: v for k, v in (self._item_order or {}).items() if k.lower() != tag_key}
            self._write_items_locked(items)
            self._items = items
            return [dict(i) for i in items]

    def _build_item(self, symbol: str, tags: list[str] | None = None) -> dict:
        try:
            move = _format_move_from_history(symbol)
        except Exception as exc:
            raise WatchlistValidationError(f"Unable to load market data for ticker '{symbol}'.") from exc

        name = _resolve_company_name(symbol)
        record = WatchlistItemRecord(
            symbol=symbol,
            name=_normalize_name(name, symbol=symbol),
            move=_normalize_move(move),
            tags=_normalize_tags(tags) if tags else [],
        )
        return record.to_dict()

    def _load_items_locked(self) -> list[dict]:
        document = self._read_document_locked()
        if document is None:
            if self._explicit_groups is None:
                self._explicit_groups = []
            if self.is_backend_configured():
                try:
                    self._write_items_locked([])
                    return []
                except WatchlistConfigurationError:
                    return self._fallback_items()
            return self._fallback_items()

        raw_eg = document.get("explicit_groups")
        self._explicit_groups = [str(g).strip() for g in raw_eg if isinstance(g, str) and str(g).strip()] if isinstance(raw_eg, list) else []

        raw_go = document.get("group_order")
        self._group_order = [str(g).strip() for g in raw_go if isinstance(g, str) and str(g).strip()] if isinstance(raw_go, list) else []

        raw_io = document.get("item_order")
        self._item_order = (
            {k: [str(s) for s in v if s] for k, v in raw_io.items() if isinstance(v, list)}
            if isinstance(raw_io, dict) else {}
        )

        raw_items = document.get("items")
        if isinstance(raw_items, list):
            normalized = self._normalize_items(raw_items)
            if normalized is not None:
                return normalized

        company_list_items = document.get("Company List")
        if isinstance(company_list_items, list):
            normalized_symbols = self._normalize_symbols_only(company_list_items)
            return [
                WatchlistItemRecord(symbol=symbol, name=symbol, move="").to_dict() for symbol in normalized_symbols
            ]

        return self._fallback_items()

    def _read_document_locked(self) -> dict | None:
        try:
            collection = self._get_collection_locked()
        except WatchlistConfigurationError:
            return None
        if collection is None:
            return None
        try:
            document = collection.find_one({"_id": self.config.document_id})
            self._backend_unavailable = False
            return document
        except Exception:
            self._backend_unavailable = True
            return None

    def _write_items_locked(self, items: list[dict]) -> None:
        collection = self._get_collection_locked()
        if collection is None:
            raise WatchlistConfigurationError("MongoDB watchlist backend is not configured.")
        try:
            collection.update_one(
                {"_id": self.config.document_id},
                {
                    "$set": {
                        "Company List": [item["symbol"] for item in items],
                        "items": items,
                        "explicit_groups": self._explicit_groups or [],
                        "group_order": self._group_order or [],
                        "item_order": self._item_order or {},
                    }
                },
                upsert=True,
            )
            self._backend_unavailable = False
        except Exception as exc:
            self._backend_unavailable = True
            raise WatchlistConfigurationError("MongoDB watchlist backend is configured but unavailable.") from exc

    def _get_collection_locked(self):
        if not self._is_backend_configured():
            return None
        if self._client is None:
            try:
                self._client = MongoClient(self.config.uri, serverSelectionTimeoutMS=2000)
            except Exception as exc:
                self._backend_unavailable = True
                raise WatchlistConfigurationError("MongoDB watchlist backend is configured but unavailable.") from exc
        return self._client[self.config.database][self.config.collection]

    def _is_backend_configured(self) -> bool:
        return bool(self.config.uri and MongoClient is not None)

    def _is_backend_available(self) -> bool:
        return self._is_backend_configured() and not self._backend_unavailable

    def _require_backend_configured(self) -> None:
        if not self.config.uri:
            raise WatchlistConfigurationError("MongoDB watchlist backend is not configured.")
        if MongoClient is None:
            raise WatchlistConfigurationError("pymongo is required for TerraFin watchlist CRUD.")

    @staticmethod
    def _normalize_items(raw_items: list[object]) -> list[dict] | None:
        normalized: list[dict] = []
        seen: set[str] = set()
        for raw_item in raw_items:
            if not isinstance(raw_item, dict):
                continue
            symbol = _normalize_symbol(str(raw_item.get("symbol") or ""))
            if not symbol or symbol in seen:
                continue
            seen.add(symbol)
            stamp = raw_item.get("move_refreshed_at")
            normalized.append(
                WatchlistItemRecord(
                    symbol=symbol,
                    name=_normalize_name(raw_item.get("name"), symbol=symbol),
                    move=_normalize_move(raw_item.get("move")),
                    tags=_normalize_tags(raw_item.get("tags") or []),
                    move_refreshed_at=str(stamp) if stamp else None,
                ).to_dict()
            )
        return normalized

    @staticmethod
    def _normalize_symbols_only(raw_items: list[object]) -> list[str]:
        symbols: list[str] = []
        seen: set[str] = set()
        for raw_item in raw_items:
            symbol = _normalize_symbol(str(raw_item or ""))
            if not symbol or symbol in seen:
                continue
            seen.add(symbol)
            symbols.append(symbol)
        return symbols

    @staticmethod
    def _fallback_items() -> list[dict]:
        return [item.model_dump() for item in get_watchlist_fallback().items]


_watchlist_service: WatchlistService | None = None


def start_watchlist_refresh_loop() -> threading.Thread | None:
    """Daemon thread that fires ``refresh_all_moves`` at each region's
    market close + buffer. Boot-time catch-up: if the latest stored
    ``move_refreshed_at`` is older than the most recently passed slot,
    fire once immediately before entering the schedule loop.
    Returns the started thread (daemon) or ``None`` if disabled.
    """
    if not _enabled():
        log.info("watchlist refresh loop disabled via TERRAFIN_WATCHLIST_REFRESH_ENABLED=0")
        return None

    def _loop() -> None:
        try:
            svc = get_watchlist_service()
        except Exception:
            log.exception("watchlist refresh loop: cannot resolve service")
            return
        if not svc.is_backend_configured():
            log.info("watchlist refresh loop: Mongo backend not configured, exiting")
            return
        # Boot catch-up
        try:
            latest = svc.latest_refresh_at_utc()
            now = datetime.now(timezone.utc)
            previous_slot = _previous_fire_at_utc(now)
            if latest is None or latest < previous_slot:
                log.info(
                    "watchlist refresh loop: catch-up fire (latest=%s, previous_slot=%s)",
                    latest, previous_slot,
                )
                svc.refresh_all_moves()
        except Exception:
            log.exception("watchlist refresh loop: catch-up fire failed")
        # Steady-state schedule
        while True:
            try:
                now = datetime.now(timezone.utc)
                fire_at, label = _next_fire_at_utc(now)
                wait = max((fire_at - now).total_seconds(), 1.0)
                log.info("watchlist refresh loop: next fire %s (%s, in %.0fs)", fire_at.isoformat(), label, wait)
                time.sleep(wait)
                svc = get_watchlist_service()
                svc.refresh_all_moves()
            except Exception:
                log.exception("watchlist refresh loop: iteration failed")
                time.sleep(60)

    thread = threading.Thread(target=_loop, name="watchlist-move-refresh", daemon=True)
    thread.start()
    return thread


def get_watchlist_service() -> WatchlistService:
    global _watchlist_service
    if _watchlist_service is None:
        _watchlist_service = WatchlistService(_load_watchlist_mongo_config())
    return _watchlist_service


def reset_watchlist_service() -> None:
    global _watchlist_service
    _watchlist_service = None
