import importlib
import math


lppl_mod = importlib.import_module("TerraFin.analytics.analysis.technical.lppl")


def _dummy_fit(window_len: int) -> lppl_mod.LPPLFit:
    return lppl_mod.LPPLFit(
        tc=float(window_len) + 1.0,
        m=0.5,
        omega=8.0,
        a=0.0,
        b=-1.0,
        c=0.1,
        phi=0.0,
        residual=0.0,
        fitted=[math.log(100.0)] * window_len,
    )


def test_lppl_default_scan_uses_exact_legacy_window_count(monkeypatch):
    lengths: list[int] = []

    def fake_fit(closes, **kwargs):
        lengths.append(len(closes))
        return _dummy_fit(len(closes))

    monkeypatch.setattr(lppl_mod, "_fit_bubble", fake_fit)
    monkeypatch.setattr(lppl_mod, "_is_bubble", lambda fit, closes_window: False)

    closes = [100.0] * 474
    result = lppl_mod.lppl(closes)

    assert result.total_windows == 33
    assert lengths[0] == len(closes)
    assert lengths[1:] == lppl_mod._legacy_window_lengths(len(closes), 50, 33)


def test_lppl_article_ladder_uses_descending_fixed_step(monkeypatch):
    lengths: list[int] = []

    def fake_fit(closes, **kwargs):
        lengths.append(len(closes))
        return _dummy_fit(len(closes))

    monkeypatch.setattr(lppl_mod, "_fit_bubble", fake_fit)
    monkeypatch.setattr(lppl_mod, "_is_bubble", lambda fit, closes_window: False)

    closes = [100.0] * 120
    result = lppl_mod.lppl(
        closes,
        n_windows=None,
        min_window=50,
        max_window=65,
        window_step=5,
    )

    assert result.total_windows == 4
    assert lengths[1:] == [65, 60, 55, 50]


def test_lppl_confidence_is_fraction_of_qualifying_windows(monkeypatch):
    def fake_fit(closes, **kwargs):
        return _dummy_fit(len(closes))

    monkeypatch.setattr(lppl_mod, "_fit_bubble", fake_fit)
    monkeypatch.setattr(lppl_mod, "_is_bubble", lambda fit, closes_window: len(closes_window) in {60, 50})

    closes = [100.0] * 120
    result = lppl_mod.lppl(
        closes,
        n_windows=None,
        min_window=50,
        max_window=65,
        window_step=5,
    )

    assert result.total_windows == 4
    assert len(result.qualifying_fits) == 2
    assert result.confidence == 0.5
