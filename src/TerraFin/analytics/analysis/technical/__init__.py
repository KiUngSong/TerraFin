"""Technical analysis for financial data.

Pure computation functions for indicators and risk metrics.
"""

from .bollinger import bollinger_bands
from .lppl import LPPLFit, LPPLResult, lppl
from .ma import moving_average
from .macd import ema, macd
from .mandelbrot import DEFAULT_MFD_WINDOWS, mandelbrot_fractal_dimension
from .rsi import rsi
from .spectral import amplitude_phase, dominant_cycles, power_spectrum, spectral_filter, spectrogram
from .trend_signal import trend_signal, trend_signal_composite
from .vol_regime import percentile_rank, vol_regime
from .volatility import range_vol, range_volatility, realized_vol, realized_volatility
