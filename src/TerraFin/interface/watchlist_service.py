from dataclasses import dataclass
from threading import Lock

from TerraFin.configuration import WatchlistConfig, load_terrafin_config


try:
    from pymongo import MongoClient
except ImportError:  # pragma: no cover - optional dependency at runtime
    MongoClient = None

from TerraFin.data.providers.market.yfinance import get_yf_data
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


@dataclass(frozen=True)
class WatchlistItemRecord:
    symbol: str
    name: str
    move: str

    def to_dict(self) -> dict[str, str]:
        return {"symbol": self.symbol, "name": self.name, "move": self.move}


WatchlistMongoConfig = WatchlistConfig


def _load_watchlist_mongo_config() -> WatchlistMongoConfig:
    return load_terrafin_config().watchlist


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


def _format_move_from_history(symbol: str) -> str:
    data = get_yf_data(symbol)
    closes = data["close"].dropna().tolist() if "close" in data.columns else []
    if len(closes) < 2:
        return "--"
    prev_close = float(closes[-2])
    last_close = float(closes[-1])
    if prev_close == 0:
        return "--"
    move_pct = ((last_close / prev_close) - 1.0) * 100.0
    return f"{move_pct:+.2f}%"


class WatchlistService:
    def __init__(self, config: WatchlistMongoConfig) -> None:
        self.config = config
        self._lock = Lock()
        self._client = None
        self._items: list[dict[str, str]] | None = None
        self._backend_unavailable = False

    def get_watchlist_snapshot(self) -> list[dict[str, str]]:
        if self._items is None:
            self.refresh_snapshot()
        return [dict(item) for item in (self._items or [])]

    def is_backend_configured(self) -> bool:
        return self._is_backend_available()

    def refresh_snapshot(self) -> None:
        with self._lock:
            self._items = self._load_items_locked()

    def clear_cache(self) -> None:
        with self._lock:
            self._items = None

    def add_symbol(self, symbol: str) -> list[dict[str, str]]:
        normalized = _normalize_symbol(symbol)
        if not normalized:
            raise WatchlistValidationError("Ticker symbol is required.")
        self._require_backend_configured()

        item = self._build_item(normalized)
        with self._lock:
            items = self._load_items_locked()
            if any(existing["symbol"] == normalized for existing in items):
                raise WatchlistConflictError(f"{normalized} is already in the watchlist.")
            items.append(item)
            self._write_items_locked(items)
            self._items = items
            return [dict(entry) for entry in items]

    def replace_symbols(self, symbols: list[str]) -> list[dict[str, str]]:
        self._require_backend_configured()
        normalized_symbols: list[str] = []
        seen: set[str] = set()
        for symbol in symbols:
            normalized = _normalize_symbol(symbol)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            normalized_symbols.append(normalized)

        items = [self._build_item(symbol) for symbol in normalized_symbols]
        with self._lock:
            self._write_items_locked(items)
            self._items = items
            return [dict(entry) for entry in items]

    def remove_symbol(self, symbol: str) -> list[dict[str, str]]:
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

    def _build_item(self, symbol: str) -> dict[str, str]:
        try:
            move = _format_move_from_history(symbol)
        except Exception as exc:
            raise WatchlistValidationError(f"Unable to load market data for ticker '{symbol}'.") from exc

        name = _resolve_company_name(symbol)
        record = WatchlistItemRecord(
            symbol=symbol,
            name=_normalize_name(name, symbol=symbol),
            move=_normalize_move(move),
        )
        return record.to_dict()

    def _load_items_locked(self) -> list[dict[str, str]]:
        document = self._read_document_locked()
        if document is None:
            if self.is_backend_configured():
                try:
                    self._write_items_locked([])
                    return []
                except WatchlistConfigurationError:
                    return self._fallback_items()
            return self._fallback_items()

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

    def _write_items_locked(self, items: list[dict[str, str]]) -> None:
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
    def _normalize_items(raw_items: list[object]) -> list[dict[str, str]] | None:
        normalized: list[dict[str, str]] = []
        seen: set[str] = set()
        for raw_item in raw_items:
            if not isinstance(raw_item, dict):
                continue
            symbol = _normalize_symbol(str(raw_item.get("symbol") or ""))
            if not symbol or symbol in seen:
                continue
            seen.add(symbol)
            normalized.append(
                WatchlistItemRecord(
                    symbol=symbol,
                    name=_normalize_name(raw_item.get("name"), symbol=symbol),
                    move=_normalize_move(raw_item.get("move")),
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
    def _fallback_items() -> list[dict[str, str]]:
        return [item.model_dump() for item in get_watchlist_fallback().items]


_watchlist_service: WatchlistService | None = None


def get_watchlist_service() -> WatchlistService:
    global _watchlist_service
    if _watchlist_service is None:
        _watchlist_service = WatchlistService(_load_watchlist_mongo_config())
    return _watchlist_service


def reset_watchlist_service() -> None:
    global _watchlist_service
    _watchlist_service = None
