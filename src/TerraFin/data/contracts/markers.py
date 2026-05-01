import logging
from functools import wraps
from collections.abc import Callable
from typing import Any

from .dataframes import TimeSeriesDataFrame


logger = logging.getLogger(__name__)


def chart_output(source_name: str, query_arg: str) -> Callable:
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(self: Any, *args: Any, **kwargs: Any) -> TimeSeriesDataFrame:
            query_value = kwargs.get(query_arg)
            if query_value is None and args:
                query_value = args[0]
            source = f"{source_name}:{query_value}" if query_value is not None else source_name

            # Do not silently swallow source errors here. If loading fails,
            # callers should see the exception instead of a hidden empty frame.
            try:
                raw = func(self, *args, **kwargs)
            except Exception:
                logger.exception("Failed to load chart data for %s", source)
                raise

            return self._to_timeseries(raw, source_name=source)

        setattr(wrapper, "__chart_output__", True)
        setattr(wrapper, "__chart_source__", source_name)
        return wrapper

    return decorator
