"""HTTP adapter for the external realtime signal monitor.

## What "monitor" means here

A *monitor* is an external service (currently DataFactory's
``datafactory.monitor``) that holds a live broker WebSocket open, runs
intraday detectors (5m / 30m / 1h timeframes) over the tick stream, and
emits *signals* — discrete, time-stamped events such as
``CAPITULATION_BOTTOM``, ``DONCHIAN50_UP``, ``MACD_BULL_CROSS``. TerraFin
itself does not run a WebSocket; it delegates realtime signal generation
to the monitor and consumes the emitted events.

## What a "signal" is in this package

A signal here is a *push notification of a market event*: ticker, name,
severity, snapshot of the indicator state at fire time. It is the
output of the monitor's detectors, NOT something computed locally inside
TerraFin. (Local, dataframe-native detectors live in
``analytics/analysis/patterns/`` and produce the same ``Signal`` shape
on demand — but they are pull-driven, not push-driven, and serve the
agent / report flows.)

## Two roles in this package

This package owns the HTTP boundary in both directions:

1. **Inbound (receive)** — the monitor POSTs each fired signal to
   ``/signals/api/signal``. ``routes.py`` accepts the request,
   ``webhook.py`` verifies the HMAC signature, dedups by signal_id, and
   forwards to the user's Telegram via ``interface/channels/``.

2. **Outbound (control)** — TerraFin tells the monitor which tickers to
   watch. ``http_provider.py`` is the HTTP client (``HttpSignalProvider``)
   that POSTs register / unregister calls. ``heartbeat.py`` runs a
   periodic reconciliation: anything tagged ``"monitor"`` in the
   watchlist must be subscribed on the provider; anything subscribed but
   no longer tagged is unregistered. The watchlist is the single source
   of truth.

## Why this lives in ``interface/`` and not ``analytics/``

This package is system-to-system glue (two HTTP endpoints + their
auth/dedup/heartbeat plumbing), not analytics. It carries no signal
*logic* — the math lives in the monitor on one side and in
``analytics/analysis/patterns/`` on the other.

## Configuration

All env vars use the ``TERRAFIN_SIGNALS_*`` prefix. See ``http_provider.py``
and ``webhook.py`` for the exact names.
"""
