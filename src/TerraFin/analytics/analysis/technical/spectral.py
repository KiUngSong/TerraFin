"""FFT spectral analysis functions for financial time series."""

import math

import numpy as np


# ── Pure computation (list in, structured out) ────────────────────────────


def power_spectrum(
    closes: list[float],
    window_func: str = "hanning",
) -> tuple[list[float], list[float]]:
    """Compute the power spectrum (periodogram) of log returns via FFT.

    Decomposes the return series into frequency components and returns
    the power at each period, revealing dominant cycles in the data.

    Args:
        closes: List of close prices (minimum 32 data points).
        window_func: Window function to reduce spectral leakage.
            One of ``"hanning"``, ``"blackman"``, or ``"none"``.

    Returns:
        ``(periods, power)`` where *periods* is in units of candles
        and *power* is the squared magnitude at each frequency.
    """
    n = len(closes)
    if n < 32:
        return ([], [])

    log_returns = [math.log(closes[i] / closes[i - 1]) for i in range(1, n)]
    arr = np.array(log_returns)

    # Apply window to reduce spectral leakage
    if window_func == "hanning":
        arr = arr * np.hanning(len(arr))
    elif window_func == "blackman":
        arr = arr * np.blackman(len(arr))

    fft_result = np.fft.rfft(arr)
    power_vals = np.abs(fft_result) ** 2

    freqs = np.fft.rfftfreq(len(arr), d=1.0)

    # Skip DC component (k=0)
    periods = (1.0 / freqs[1:]).tolist()
    power_out = power_vals[1:].tolist()

    return (periods, power_out)


def dominant_cycles(
    closes: list[float],
    top_n: int = 5,
    window_func: str = "hanning",
) -> list[tuple[float, float, float]]:
    """Find the dominant periodic cycles in a price series.

    Runs ``power_spectrum`` and returns the top *N* peaks ranked by
    signal-to-noise ratio against the median noise floor.

    Args:
        closes: List of close prices (minimum 32 data points).
        top_n: Number of top cycles to return.
        window_func: Window function (see :func:`power_spectrum`).

    Returns:
        List of ``(period, power, snr)`` tuples sorted by SNR descending.
        *period* is in candles, *snr* is the ratio to the median power.
    """
    periods, power = power_spectrum(closes, window_func=window_func)
    if not power:
        return []

    power_arr = np.array(power)
    noise_floor = float(np.median(power_arr))
    if noise_floor == 0:
        noise_floor = 1e-12

    snr = power_arr / noise_floor
    top_n = min(top_n, len(power))
    top_indices = np.argsort(power_arr)[-top_n:][::-1]

    return [(periods[i], power[i], float(snr[i])) for i in top_indices]


def amplitude_phase(
    closes: list[float],
    window_func: str = "hanning",
) -> tuple[list[float], list[float], list[float]]:
    """Compute amplitude and phase at each frequency from log returns.

    Amplitude tells how large each cycle's contribution is (in return
    magnitude), and phase tells the current position within the cycle.

    Args:
        closes: List of close prices (minimum 32 data points).
        window_func: Window function (see :func:`power_spectrum`).

    Returns:
        ``(periods, amplitudes, phases_deg)`` where *amplitudes* are
        scaled to return units and *phases_deg* are in degrees (-180 to 180).
    """
    n = len(closes)
    if n < 32:
        return ([], [], [])

    log_returns = [math.log(closes[i] / closes[i - 1]) for i in range(1, n)]
    arr = np.array(log_returns)

    if window_func == "hanning":
        arr = arr * np.hanning(len(arr))
    elif window_func == "blackman":
        arr = arr * np.blackman(len(arr))

    fft_result = np.fft.rfft(arr)
    freqs = np.fft.rfftfreq(len(arr), d=1.0)

    # Scale amplitude to real return units
    amplitudes = (2.0 / len(arr)) * np.abs(fft_result)
    phases = np.degrees(np.angle(fft_result))

    # Skip DC component
    periods = (1.0 / freqs[1:]).tolist()
    amp_out = amplitudes[1:].tolist()
    phase_out = phases[1:].tolist()

    return (periods, amp_out, phase_out)


def spectral_filter(
    closes: list[float],
    min_period: float = 2.0,
    max_period: float = float("inf"),
) -> list[float]:
    """Band-pass filter: reconstruct returns keeping only selected frequencies.

    Zeroes out frequency components outside the specified period range,
    then inverse-FFTs back to the time domain.

    Args:
        closes: List of close prices (minimum 32 data points).
        min_period: Minimum period to keep (in candles). Frequencies faster
            than this are removed (noise filtering).
        max_period: Maximum period to keep (in candles). Frequencies slower
            than this are removed (trend removal).

    Returns:
        Filtered log-return series (same length as ``len(closes) - 1``).
        Empty list if fewer than 32 data points.
    """
    n = len(closes)
    if n < 32:
        return []

    log_returns = [math.log(closes[i] / closes[i - 1]) for i in range(1, n)]
    arr = np.array(log_returns)
    m = len(arr)

    fft_result = np.fft.rfft(arr)
    freqs = np.fft.rfftfreq(m, d=1.0)

    # Zero out frequencies outside the band
    for k in range(len(freqs)):
        if freqs[k] == 0:
            fft_result[k] = 0  # remove DC
            continue
        period = 1.0 / freqs[k]
        if period < min_period or period > max_period:
            fft_result[k] = 0

    return np.fft.irfft(fft_result, n=m).tolist()


def spectrogram(
    closes: list[float],
    segment_size: int = 64,
    overlap: int = 48,
) -> tuple[list[float], list[int], list[list[float]]]:
    """Compute a time-frequency spectrogram via sliding-window FFT.

    Reveals how dominant cycles evolve over time (regime detection).

    Args:
        closes: List of close prices.
        segment_size: Number of candles per FFT window.
        overlap: Number of overlapping candles between consecutive windows.

    Returns:
        ``(periods, time_indices, power_matrix)`` where *power_matrix[t][f]*
        is the power at time segment *t* and frequency index *f*.
        *time_indices* gives the center candle index of each segment.
    """
    n = len(closes)
    if n < segment_size + 1:
        return ([], [], [])

    log_returns = [math.log(closes[i] / closes[i - 1]) for i in range(1, n)]

    step = segment_size - overlap
    if step < 1:
        step = 1

    time_indices: list[int] = []
    power_matrix: list[list[float]] = []
    periods: list[float] = []

    for start in range(0, len(log_returns) - segment_size + 1, step):
        segment = np.array(log_returns[start : start + segment_size])
        segment = segment * np.hanning(segment_size)

        fft_result = np.fft.rfft(segment)
        power_vals = (np.abs(fft_result) ** 2).tolist()

        freqs = np.fft.rfftfreq(segment_size, d=1.0)

        # Set periods on first iteration (same for all segments)
        if not periods:
            periods = (1.0 / freqs[1:]).tolist()

        power_matrix.append(power_vals[1:])  # skip DC
        time_indices.append(start + segment_size // 2)

    return (periods, time_indices, power_matrix)
