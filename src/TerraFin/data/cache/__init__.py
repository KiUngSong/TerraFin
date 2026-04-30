"""Cache orchestration layer."""

from TerraFin.data.contracts import HistoryChunk, TimeSeriesDataFrame

from .manager import CacheManager, CacheSourceSpec
from .policy import CachePolicy, get_default_cache_policies
from .registry import (
    clear_all_cache,
    get_cache_manager,
    reset_cache_manager,
    refresh_all_due,
)
from .serializers import ColumnarTimeSeriesSerializer, HistoryChunkSerializer


CacheManager.register_serializer(TimeSeriesDataFrame, ColumnarTimeSeriesSerializer())
CacheManager.register_serializer(HistoryChunk, HistoryChunkSerializer())


__all__ = [
    "CacheManager",
    "CacheSourceSpec",
    "CachePolicy",
    "get_default_cache_policies",
    "get_cache_manager",
    "reset_cache_manager",
    "clear_all_cache",
    "refresh_all_due",
]
