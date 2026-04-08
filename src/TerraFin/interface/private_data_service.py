from datetime import datetime

from TerraFin.data.cache.manager import CachePayloadSpec
from TerraFin.data.cache.registry import get_cache_manager
from TerraFin.data.providers.economic.macro_calendar import get_macro_events_all
from TerraFin.data.providers.economic.macro_values import enrich_macro_events_all
from TerraFin.data.providers.private_access import PrivateAccessClient, load_private_access_config
from TerraFin.data.providers.private_access.cape import clear_cape_cache, get_cape_current
from TerraFin.data.providers.private_access.fallbacks import get_calendar_fallback, get_market_breadth_fallback
from TerraFin.data.providers.private_access.fear_greed import clear_fear_greed_cache, get_fear_greed_current
from TerraFin.data.providers.private_access.models import CalendarEvent
from TerraFin.data.providers.private_access.trailing_forward_pe import clear_trailing_forward_pe_cache


_NS_BREADTH = "private_breadth"
_NS_PE_SPREAD = "private_pe_spread"
_NS_CAPE = "private_cape"
_NS_CALENDAR = "private_calendar"
_NS_MACRO = "private_macro"
_NS_FEAR_GREED = "private_fear_greed_current"
_NS_TOP_COMPANIES = "private_top_companies"
_TTL_HOURLY = 86_400  # 24h for hourly-refresh sources
_TTL_DAILY = 7 * 86_400  # 7d for daily-refresh sources

_SRC_BREADTH = "private.market_breadth"
_SRC_PE_SPREAD = "private.trailing_forward_pe"
_SRC_CAPE = "private.cape"
_SRC_CALENDAR = "private.calendar"
_SRC_MACRO = "private.macro"
_SRC_FEAR_GREED = "private.fear_greed"
_SRC_TOP_COMPANIES = "private.top_companies"


class PrivateDataService:
    def __init__(self, client: PrivateAccessClient) -> None:
        self.client = client
        self._cache_manager = get_cache_manager()
        self._register_payload_sources()

    def get_cape(self) -> dict:
        return dict(self._get_payload(_SRC_CAPE))

    def get_market_breadth(self) -> list[dict]:
        return list(self._get_payload(_SRC_BREADTH))

    def get_trailing_forward_pe(self) -> dict:
        return dict(self._get_payload(_SRC_PE_SPREAD))

    def get_calendar_events(
        self,
        *,
        year: int,
        month: int,
        categories: set[str] | None = None,
        limit: int | None = None,
    ) -> list[dict]:
        source_events = [CalendarEvent.model_validate(event) for event in self._get_payload(_SRC_CALENDAR)]
        filtered = self._filter_calendar_events(source_events, year=year, month=month, categories=categories)
        result = [event.model_dump() for event in filtered]

        if categories is None or "macro" in categories:
            for event in self._get_payload(_SRC_MACRO):
                try:
                    dt_str = event.get("start", "")[:10]
                    dt = datetime.strptime(dt_str, "%Y-%m-%d")
                except (ValueError, IndexError):
                    continue
                if dt.year == year and dt.month == month:
                    if categories and event.get("category") not in categories:
                        continue
                    result.append(event)

        result.sort(key=lambda e: e.get("start", ""))
        if limit is not None:
            result = result[:limit]
        return result

    def get_fear_greed_current(self) -> dict:
        return dict(self._get_payload(_SRC_FEAR_GREED))

    def get_top_companies(self) -> list[dict]:
        return list(self._get_payload(_SRC_TOP_COMPANIES))

    def refresh_market_breadth(self) -> None:
        self._cache_manager.refresh_payload(_SRC_BREADTH)

    def refresh_trailing_forward_pe(self) -> None:
        self._cache_manager.refresh_payload(_SRC_PE_SPREAD)

    def refresh_cape(self) -> None:
        self._cache_manager.refresh_payload(_SRC_CAPE)

    def refresh_calendar(self) -> None:
        self._cache_manager.refresh_payload(_SRC_CALENDAR)

    def refresh_macro(self) -> None:
        self._cache_manager.refresh_payload(_SRC_MACRO)

    def refresh_fear_greed(self) -> None:
        self._cache_manager.refresh_payload(_SRC_FEAR_GREED)

    def refresh_top_companies(self) -> None:
        self._cache_manager.refresh_payload(_SRC_TOP_COMPANIES)

    def set_calendar_events(self, events: list[dict]) -> None:
        self._cache_manager.set_payload(_SRC_CALENDAR, list(events))

    def clear_cache(self) -> None:
        clear_cape_cache()
        clear_fear_greed_cache()
        clear_trailing_forward_pe_cache()
        for source in (
            _SRC_BREADTH,
            _SRC_PE_SPREAD,
            _SRC_CAPE,
            _SRC_CALENDAR,
            _SRC_MACRO,
            _SRC_FEAR_GREED,
            _SRC_TOP_COMPANIES,
        ):
            self._cache_manager.clear_payload(source)

    @staticmethod
    def _parse_event_start(start: str) -> datetime | None:
        text = start.strip()
        if not text:
            return None
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            try:
                return datetime.strptime(text, "%Y/%m/%d")
            except ValueError:
                return None

    def _filter_calendar_events(
        self,
        events: list[CalendarEvent],
        *,
        year: int,
        month: int,
        categories: set[str] | None,
    ) -> list[CalendarEvent]:
        filtered: list[CalendarEvent] = []
        for event in events:
            parsed = self._parse_event_start(event.start)
            if parsed is None:
                continue
            if parsed.year != year or parsed.month != month:
                continue
            if categories and event.category not in categories:
                continue
            filtered.append(event)
        filtered.sort(key=lambda item: item.start)
        return filtered

    def _register_payload_sources(self) -> None:
        self._cache_manager.register_payload(
            CachePayloadSpec(
                source=_SRC_BREADTH,
                namespace=_NS_BREADTH,
                key="metrics",
                ttl_seconds=_TTL_HOURLY,
                fetch_fn=self._fetch_market_breadth,
                fallback_fn=lambda: [metric.model_dump() for metric in get_market_breadth_fallback().metrics],
            )
        )
        self._cache_manager.register_payload(
            CachePayloadSpec(
                source=_SRC_PE_SPREAD,
                namespace=_NS_PE_SPREAD,
                key="spread",
                ttl_seconds=_TTL_HOURLY,
                fetch_fn=self._fetch_trailing_forward_pe,
                fallback_fn=lambda: {
                    "date": "",
                    "summary": {},
                    "coverage": {},
                    "history": [],
                },
            )
        )
        self._cache_manager.register_payload(
            CachePayloadSpec(
                source=_SRC_CAPE,
                namespace=_NS_CAPE,
                key="current",
                ttl_seconds=_TTL_DAILY,
                fetch_fn=lambda: get_cape_current(force_refresh=True),
                fallback_fn=lambda: {"date": None, "cape": None},
            )
        )
        self._cache_manager.register_payload(
            CachePayloadSpec(
                source=_SRC_CALENDAR,
                namespace=_NS_CALENDAR,
                key="events",
                ttl_seconds=_TTL_DAILY,
                fetch_fn=self._fetch_calendar_events,
                fallback_fn=lambda: [event.model_dump() for event in get_calendar_fallback().events],
            )
        )
        self._cache_manager.register_payload(
            CachePayloadSpec(
                source=_SRC_MACRO,
                namespace=_NS_MACRO,
                key="events",
                ttl_seconds=_TTL_DAILY,
                fetch_fn=self._fetch_macro_events,
                fallback_fn=lambda: [],
            )
        )
        self._cache_manager.register_payload(
            CachePayloadSpec(
                source=_SRC_FEAR_GREED,
                namespace=_NS_FEAR_GREED,
                key="current",
                ttl_seconds=_TTL_HOURLY,
                fetch_fn=lambda: get_fear_greed_current(force_refresh=True),
                fallback_fn=lambda: {
                    "score": None,
                    "rating": "Unavailable",
                    "timestamp": "",
                    "previous_close": None,
                    "previous_1_week": None,
                    "previous_1_month": None,
                },
            )
        )
        self._cache_manager.register_payload(
            CachePayloadSpec(
                source=_SRC_TOP_COMPANIES,
                namespace=_NS_TOP_COMPANIES,
                key="companies",
                ttl_seconds=_TTL_DAILY,
                fetch_fn=self._fetch_top_companies,
                fallback_fn=lambda: [],
            )
        )

    def _get_payload(self, source: str) -> dict | list:
        return self._cache_manager.get_payload(source).payload

    def _fetch_market_breadth(self) -> list[dict]:
        response = self.client.fetch_market_breadth()
        return [metric.model_dump() for metric in response.metrics]

    def _fetch_trailing_forward_pe(self) -> dict:
        return self.client.fetch_trailing_forward_pe_spread().model_dump()

    def _fetch_calendar_events(self) -> list[dict]:
        response = self.client.fetch_calendar_events()
        return [event.model_dump() for event in response.events]

    @staticmethod
    def _fetch_macro_events() -> list[dict]:
        return enrich_macro_events_all(get_macro_events_all())

    def _fetch_top_companies(self) -> list[dict]:
        response = self.client.fetch_top_companies()
        return [company.model_dump(exclude_none=True) for company in response.companies]


_private_data_service: PrivateDataService | None = None


def get_private_data_service() -> PrivateDataService:
    global _private_data_service
    if _private_data_service is None:
        _private_data_service = PrivateDataService(PrivateAccessClient(load_private_access_config()))
    return _private_data_service


def reset_private_data_service() -> None:
    global _private_data_service
    if _private_data_service is not None:
        _private_data_service.clear_cache()
    _private_data_service = None
