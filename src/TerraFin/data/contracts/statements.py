"""Financial statement contract for income, balance, and cashflow data."""

from typing import Literal

import pandas as pd


StatementType = Literal["income", "balance", "cashflow"]
PeriodType = Literal["annual", "quarterly"]


class FinancialStatementFrame(pd.DataFrame):
    """A pandas DataFrame subclass for financial statements.

    Columns are reporting period dates (ISO date strings or pd.Timestamp).
    Rows are line items.
    """

    _metadata = ["_is_processed", "_statement_type", "_period", "_ticker"]

    def __init__(
        self,
        data=None,
        *args,
        statement_type: StatementType | None = None,
        period: PeriodType | None = None,
        ticker: str | None = None,
        _is_processed: bool = False,
        **kwargs,
    ):
        if _is_processed:
            super().__init__(data, *args, **kwargs)
            self._is_processed = True
            self._statement_type = statement_type
            self._period = period
            self._ticker = ticker
            return

        if statement_type is None or period is None or ticker is None:
            raise ValueError("statement_type, period, and ticker are required")
        if statement_type not in ("income", "balance", "cashflow"):
            raise ValueError(f"invalid statement_type: {statement_type}")
        if period not in ("annual", "quarterly"):
            raise ValueError(f"invalid period: {period}")

        if data is None:
            frame = pd.DataFrame()
        elif isinstance(data, pd.DataFrame):
            frame = data.copy()
        else:
            frame = pd.DataFrame(data, *args, **kwargs)

        self._validate_columns(frame)

        super().__init__(frame)
        self._is_processed = True
        self._statement_type = statement_type
        self._period = period
        self._ticker = ticker

    @property
    def _constructor(self):
        statement_type = getattr(self, "_statement_type", None)
        period = getattr(self, "_period", None)
        ticker = getattr(self, "_ticker", None)

        def constructor(*args, **kwargs):
            kwargs["_is_processed"] = True
            kwargs.setdefault("statement_type", statement_type)
            kwargs.setdefault("period", period)
            kwargs.setdefault("ticker", ticker)
            return FinancialStatementFrame(*args, **kwargs)

        return constructor

    @property
    def statement_type(self) -> StatementType | None:
        return getattr(self, "_statement_type", None)

    @property
    def period(self) -> PeriodType | None:
        return getattr(self, "_period", None)

    @property
    def ticker(self) -> str | None:
        return getattr(self, "_ticker", None)

    @staticmethod
    def _validate_columns(frame: pd.DataFrame) -> None:
        if frame.empty and len(frame.columns) == 0:
            return
        for col in frame.columns:
            if isinstance(col, pd.Timestamp):
                continue
            if isinstance(col, str):
                try:
                    pd.Timestamp(col)
                except (ValueError, TypeError) as exc:
                    raise ValueError(
                        f"column {col!r} is not an ISO date string or pd.Timestamp"
                    ) from exc
                continue
            raise ValueError(
                f"column {col!r} is not an ISO date string or pd.Timestamp"
            )

    @classmethod
    def make_empty(
        cls,
        statement_type: StatementType,
        period: PeriodType,
        ticker: str,
    ) -> "FinancialStatementFrame":
        return cls(
            pd.DataFrame(),
            statement_type=statement_type,
            period=period,
            ticker=ticker,
            _is_processed=True,
        )
