import logging

import pandas as pd
import plotly.express as px


logger = logging.getLogger(__name__)


class TimeSeriesDataFrame(pd.DataFrame):
    """
    A pandas DataFrame subclass that automatically applies postprocessing and validation
    for time series data. Works exactly like a regular DataFrame but ensures data
    conforms to the TimeSeriesDataFrame format.
    """

    # Pandas subclassing requires this to preserve custom attributes
    _metadata = ["_is_processed", "_name", "_chart_meta"]
    _desired_columns = ["time", "open", "high", "low", "close", "volume"]
    _column_aliases = {
        "time": "time",
        "date": "time",
        "datetime": "time",
        "timestamp": "time",
        "open": "open",
        "high": "high",
        "low": "low",
        "close": "close",
        "volume": "volume",
    }

    def __init__(self, data=None, *args, **kwargs):
        """
        Initializes the TimeSeriesDataFrame.

        If the data is not already processed (i.e., this is the first time
        it's being passed to the class), it undergoes processing and validation.
        If it's already processed (e.g., during a slicing operation),
        it bypasses this step.
        """
        # Pop our custom flag to prevent it from being passed to pd.DataFrame
        is_processed = kwargs.pop("_is_processed", False)
        frame_name = kwargs.pop("name", None)
        chart_meta = kwargs.pop("chart_meta", None)

        if is_processed:
            # Path for internal pandas operations: data is already processed.
            # Simply initialize the parent DataFrame.
            super().__init__(data, *args, **kwargs)
            self._chart_meta = dict(chart_meta) if isinstance(chart_meta, dict) else {}
            if frame_name is not None:
                self._name = frame_name
            return

        try:
            # Create a temporary DataFrame for processing, preserving original kwargs
            if not isinstance(data, pd.DataFrame):
                temp_df = pd.DataFrame(data, *args, **kwargs)
            else:
                temp_df = data.copy()
                if isinstance(data, TimeSeriesDataFrame):
                    if frame_name is None:
                        frame_name = data.name
                    if chart_meta is None:
                        chart_meta = data.chart_meta

            # Apply postprocessing and validation
            processed_data = self._postprocess(temp_df)
            self._validate_data(processed_data)
        except Exception as exc:
            logger.warning("Failed to normalize time series data. Returning empty frame. error=%s", exc)
            processed_data = self._empty_frame()

        # Initialize the parent DataFrame with the clean, processed data
        super().__init__(processed_data)
        self._is_processed = True
        self._name = frame_name
        self._chart_meta = dict(chart_meta) if isinstance(chart_meta, dict) else {}

    @property
    def _constructor(self):
        """
        This property is used by pandas operations to create a new instance
        of the same class. For example, `df[...]` or `df.loc[...]` will call this.
        """

        def constructor(*args, **kwargs):
            # When creating a new instance from an existing one, the data
            # is already processed. We pass a flag to __init__ to skip reprocessing.
            kwargs["_is_processed"] = True
            return TimeSeriesDataFrame(*args, **kwargs)

        # IMPORTANT: The property must return the inner function
        return constructor

    @property
    def name(self) -> str | None:
        return getattr(self, "_name", None)

    @name.setter
    def name(self, value: str | None) -> None:
        self._name = value

    @property
    def chart_meta(self) -> dict:
        value = getattr(self, "_chart_meta", None)
        return dict(value) if isinstance(value, dict) else {}

    @chart_meta.setter
    def chart_meta(self, value: dict | None) -> None:
        self._chart_meta = dict(value) if isinstance(value, dict) else {}

    @classmethod
    def _empty_frame(cls) -> pd.DataFrame:
        """Create an empty frame with the canonical chart column order."""
        return pd.DataFrame(columns=cls._desired_columns)

    @classmethod
    def make_empty(cls) -> "TimeSeriesDataFrame":
        """Create an empty TimeSeriesDataFrame instance."""
        return cls(cls._empty_frame(), _is_processed=True)

    @staticmethod
    def _normalize_col_name(col: str) -> str:
        return col.strip().lower().replace(" ", "_").replace("-", "_")

    def _postprocess(self, data: pd.DataFrame) -> pd.DataFrame:
        """Apply postprocessing to convert data to standard time series format"""
        if data is None:
            raise ValueError("Data must be provided")

        data = data.copy()
        if data.empty:
            return self._empty_frame()

        rename_map = {}
        for col in data.columns:
            normalized = self._normalize_col_name(str(col))
            if normalized in self._column_aliases:
                rename_map[col] = self._column_aliases[normalized]
        if rename_map:
            data = data.rename(columns=rename_map)

        if "time" in data.columns:
            parsed_time = pd.to_datetime(data["time"], errors="coerce")
        else:
            parsed_time = pd.to_datetime(data.index, errors="coerce")
        data["time"] = parsed_time

        # Only keep the columns we need, in the correct order
        final_columns = [col for col in self._desired_columns if col in data.columns]
        if "close" not in final_columns:
            raise ValueError("Data must have a 'close' column")

        data = data[final_columns]
        data = data.dropna(subset=["time", "close"])
        price_cols = [c for c in ("open", "high", "low", "close") if c in data.columns]
        data = data[(data[price_cols] > 0).all(axis=1)]
        data = data.sort_values("time")
        data = data.drop_duplicates(subset=["time"], keep="last")

        if data.empty:
            return self._empty_frame()

        return data.reset_index(drop=True)

    def _validate_data(self, data: pd.DataFrame) -> bool:
        """Validate the data structure"""
        if not isinstance(data, pd.DataFrame):
            raise TypeError("Data must be a pandas DataFrame")
        if data.empty:
            return True
        if "close" not in data.columns:
            raise ValueError("Data must have a 'close' column")
        if "time" in data.columns and not pd.api.types.is_datetime64_any_dtype(data["time"]):
            raise ValueError("Column 'time' must be datetime-like")
        return True


class PortfolioDataFrame(pd.DataFrame):
    """
    A pandas DataFrame subclass that has visualization methods attached to it.
    """

    # Pandas subclassing requires these properties
    _metadata = ["_is_processed"]

    def __init__(self, data: pd.DataFrame = None, index=None, columns=None, dtype=None, copy=None):
        """
        Initialize PortfolioDataFrame.

        Usage: PortfolioDataFrame(get_portfolio_data(...))
        """

        assert data is not None, "Data must be provided"

        # Initialize the parent DataFrame with processed data
        super().__init__(
            data=data.values,
            index=data.index,
            columns=data.columns,
            dtype=data.dtypes if len(data.dtypes.unique()) == 1 else None,
            copy=False,
        )

        # Set metadata
        self._is_processed = True

    def make_figure(self):
        df = self.copy()
        # Holdings now carry a CUSIP-resolved `Ticker` column out of
        # `_format_rows`. When that's absent (legacy callers) fall back to the
        # historical "TICKER - Company" split. When `Ticker` is null for a
        # given row (closed-end fund / unit trust without an exchange ticker)
        # use the issuer name so the treemap still has a non-null path key.
        if "Ticker" not in df.columns:
            df[["Ticker", "Company"]] = df["Stock"].str.split(" - ", expand=True)
        else:
            if "Company" not in df.columns:
                df["Company"] = df["Stock"]
            df["Ticker"] = df["Ticker"].fillna(df["Stock"])

        # Color labels: dark red, medium red, light red, light gray, light green, medium green, dark green
        labels = [
            "#8d2b2d",  # dark red
            "#df484c",  # medium red
            "#e78383",  # light red
            "#808080",  # light gray
            "#8bca84",  # light green
            "#5bb450",  # medium green
            "#276221",  # dark green
        ]

        # Define the color mapping function
        def maps_to_label(update_value, recent_activity, bins=[-10, -5, -2.5, 0, 2.5, 5, 10]):
            if recent_activity == "Buy":
                return labels[6]

            if update_value <= bins[0]:
                return labels[0]
            elif update_value > bins[0] and update_value <= bins[1]:
                return labels[1]
            elif update_value > bins[1] and update_value <= bins[2]:
                return labels[2]
            elif update_value > bins[2] and update_value < bins[4]:
                return labels[3]
            elif update_value >= bins[4] and update_value < bins[5]:
                return labels[4]
            elif update_value >= bins[5] and update_value < bins[6]:
                return labels[5]
            elif update_value >= bins[6]:
                return labels[6]

        df["colors"] = list(map(maps_to_label, df["Updated"], df["Recent Activity"]))

        # Create a treemap
        fig = px.treemap(
            df,
            path=["Ticker"],
            values="% of Portfolio",
            color="colors",
            color_discrete_map={label: label for label in labels},
            custom_data=["Company", "Updated"],
        )

        # Update layout for better aesthetics
        fig.update_layout(
            margin={"t": 0, "b": 0},
            autosize=True,
            font={"family": "Arial", "size": 15, "color": "black"},
            hovermode=False,
        )

        # Update trace for custom text
        fig.update_traces(
            texttemplate="<b>%{label}</b><br>%{customdata[0]}<br>% of Portfolio: %{value}%<br>Position Change: %{customdata[1]}%",
            textinfo="label+text+value",
            textfont={"color": "white"},
        )

        # Update traces for aesthetics and disable hover info
        fig.update_traces(
            marker={"cornerradius": 5},
            pathbar_visible=False,
            textposition="middle center",
        )

        return fig
