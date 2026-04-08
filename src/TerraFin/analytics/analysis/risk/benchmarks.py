from .models import BenchmarkSelection


_DEFAULT_BENCHMARK = ("^SPX", "S&P 500")
_SUFFIX_BENCHMARKS = {
    ".KS": ("^KS11", "Kospi"),
    ".KQ": ("^KQ11", "Kosdaq"),
    ".T": ("^N225", "Nikkei 225"),
}


def normalize_symbol(symbol: str) -> str:
    return symbol.strip().upper()


def select_default_benchmark(symbol: str) -> BenchmarkSelection:
    normalized = normalize_symbol(symbol)
    if not normalized:
        return BenchmarkSelection(
            input_symbol=normalized,
            benchmark_symbol=None,
            benchmark_label=None,
            status="unsupported_benchmark",
            warnings=["Ticker is required to determine a benchmark."],
        )

    if "." not in normalized:
        benchmark_symbol, benchmark_label = _DEFAULT_BENCHMARK
        return BenchmarkSelection(
            input_symbol=normalized,
            benchmark_symbol=benchmark_symbol,
            benchmark_label=benchmark_label,
            status="ready",
        )

    suffix = f".{normalized.rsplit('.', 1)[1]}"
    if suffix in _SUFFIX_BENCHMARKS:
        benchmark_symbol, benchmark_label = _SUFFIX_BENCHMARKS[suffix]
        return BenchmarkSelection(
            input_symbol=normalized,
            benchmark_symbol=benchmark_symbol,
            benchmark_label=benchmark_label,
            status="ready",
        )

    return BenchmarkSelection(
        input_symbol=normalized,
        benchmark_symbol=None,
        benchmark_label=None,
        status="unsupported_benchmark",
        warnings=[
            f"No default benchmark mapping is defined for {suffix}. "
            "Support currently covers U.S., Korea (.KS/.KQ), and Japan (.T)."
        ],
    )
