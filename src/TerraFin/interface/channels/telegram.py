"""Telegram channel for TerraFin signals.

Config stored at ~/.terrafin/telegram.json:
  {"token": "123:AAH...", "chat_id": "987654321"}

Setup flow:
  terrafin-signals telegram setup <token>
  terrafin-signals telegram pair
  terrafin-signals telegram test
"""

import json
import logging
import time
from pathlib import Path


log = logging.getLogger(__name__)

_CONFIG_PATH = Path.home() / ".terrafin" / "telegram.json"
_TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"


def _api_url(token: str, method: str) -> str:
    return _TELEGRAM_API.format(token=token, method=method)


def load_config(path: Path = _CONFIG_PATH) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Telegram config not found at {path}.\nRun: terrafin-signals telegram setup <token>")
    return json.loads(path.read_text())


def save_config(data: dict, path: Path = _CONFIG_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))


class TelegramChannel:
    def __init__(self, token: str, chat_id: str) -> None:
        self.token = token
        self.chat_id = chat_id

    def send(self, title: str, body_md: str, payload: dict) -> None:
        try:
            import httpx
        except ImportError as exc:
            raise RuntimeError("httpx is required: pip install httpx") from exc

        # Reports carry a `markdown` key — render styled. Signals use the
        # `signals` shape and stay on the legacy plain Markdown path.
        if payload.get("markdown") or body_md and "##" in body_md:
            md = payload.get("markdown") or body_md
            # If body lacks a top-level heading, prepend the title as one
            if not md.lstrip().startswith("# "):
                md = f"# {title}\n\n{md}"
            chunks = _markdown_to_telegram_html(md)
        else:
            text = _format_signal_payload(title, payload.get("signals", []))
            httpx.post(
                _api_url(self.token, "sendMessage"),
                json={
                    "chat_id": self.chat_id,
                    "text": text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
                timeout=10,
            ).raise_for_status()
            return

        for chunk in chunks:
            httpx.post(
                _api_url(self.token, "sendMessage"),
                json={
                    "chat_id": self.chat_id,
                    "text": chunk,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
                timeout=10,
            ).raise_for_status()

    def send_text(self, text: str, parse_mode: str = "HTML") -> None:
        """Send a single pre-formatted message. Bypasses the signal formatter.

        Use for one-off operational notices (e.g. monitor toggle confirmation)
        where the full signal grouping/severity rendering is not appropriate.
        """
        try:
            import httpx
        except ImportError as exc:
            raise RuntimeError("httpx is required: pip install httpx") from exc
        httpx.post(
            _api_url(self.token, "sendMessage"),
            json={
                "chat_id": self.chat_id,
                "text": text,
                "parse_mode": parse_mode,
                "disable_web_page_preview": True,
            },
            timeout=10,
        ).raise_for_status()

    @classmethod
    def from_config(cls, path: Path = _CONFIG_PATH) -> "TelegramChannel":
        cfg = load_config(path)
        token = cfg.get("token", "")
        chat_id = cfg.get("chat_id", "")
        if not token:
            raise RuntimeError("Telegram token not set. Run: terrafin-signals telegram setup <token>")
        if not chat_id:
            raise RuntimeError("Telegram chat_id not set. Run: terrafin-signals telegram pair")
        return cls(token=token, chat_id=chat_id)


def _html_escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# Severity → emoji. Wire still carries 3 levels (low/med/high) for downstream
# consumers; rendering is bucketed because most signals fire as "high" anyway.
_SEVERITY_EMOJI = {"high": "🔴", "med": "🟡", "medium": "🟡", "low": "🟢"}

_BULLISH_KEYWORDS = ("bull", "golden", " buy", "↑", "breakout", "bounce", "coppock", "above", "long")
_BEARISH_KEYWORDS = ("bear", "death", " sell", "↓", "breakdown", "below", "short")


def _signal_direction(signal_dict: dict) -> str:
    """Return ▲/▼/— based on snapshot.side first, then keyword heuristic on signal text."""
    snapshot = signal_dict.get("snapshot") or {}
    side = snapshot.get("side")
    if side == 1:
        return "▲"
    if side == -1:
        return "▼"
    text = (signal_dict.get("message") or signal_dict.get("signal") or "").lower()
    if any(k in text for k in _BULLISH_KEYWORDS):
        return "▲"
    if any(k in text for k in _BEARISH_KEYWORDS):
        return "▼"
    return "—"


def _format_signal_payload(title: str, signals: list[dict]) -> str:
    """Group signals by ticker, render as ticker-led bullet list with direction + severity.

    Wire shape per signal: ``{"ticker": str, "severity"?: str, "message"|"signal"?: str, "snapshot"?: dict}``.
    """
    ts = time.strftime("%H:%M %Z", time.localtime())
    lines = [f"<b>{_html_escape(title)}</b>  <i>{_html_escape(ts)}</i>", ""]

    by_ticker: dict[str, list[dict]] = {}
    for s in signals:
        by_ticker.setdefault(s.get("ticker") or "?", []).append(s)

    for ticker, group in by_ticker.items():
        name = (group[0].get("name") or "").strip()
        if name and name != ticker:
            header = f"<b>{_html_escape(name)}</b>  <code>{_html_escape(ticker)}</code>"
        else:
            header = f"<b>{_html_escape(ticker)}</b>"
        lines.append(header)
        for s in group:
            sev = (s.get("severity") or "").lower()
            emoji = _SEVERITY_EMOJI.get(sev, "⚪")
            msg = s.get("message") or s.get("signal") or ""
            direction = _signal_direction(s)
            lines.append(f"  {direction} {_html_escape(msg)} {emoji}")
        lines.append("")
    return "\n".join(lines).rstrip()


def _markdown_to_telegram_html(md: str) -> list[str]:
    """Convert TerraFin report markdown to Telegram-flavored HTML chunks.

    Telegram only supports a small tag set (b/i/u/s/a/code/pre/blockquote/tg-spoiler).
    Headings/lists are mapped to bold + Unicode bullets. Output is split into
    chunks under the 4096-char per-message limit, breaking on blank lines.
    """
    import re

    out_lines: list[str] = []
    for raw in md.splitlines():
        line = raw
        if line.startswith("# "):
            line = f"<b>{_html_escape(line[2:].strip())}</b>"
        elif line.startswith("## "):
            line = f"<b>{_html_escape(line[3:].strip())}</b>"
        elif line.startswith("> "):
            inner = line[2:].strip()
            inner = _inline_md(inner)
            line = f"<i>{inner}</i>"
        else:
            indent = len(line) - len(line.lstrip(" "))
            stripped = line.lstrip(" ")
            if stripped.startswith("- "):
                bullet = "•" if indent < 2 else "◦"
                line = " " * indent + f"{bullet} " + _inline_md(stripped[2:])
            else:
                line = _inline_md(line)
        out_lines.append(line)

    full = "\n".join(out_lines)

    LIMIT = 3800  # safety margin under 4096
    if len(full) <= LIMIT:
        return [full]

    def _split_oversized(p: str) -> list[str]:
        """Split a single paragraph that exceeds LIMIT — line breaks first, then hard cut."""
        if len(p) <= LIMIT:
            return [p]
        out: list[str] = []
        cur_lines: list[str] = []
        cur_len = 0
        for line in p.split("\n"):
            llen = len(line) + 1
            if cur_len + llen > LIMIT and cur_lines:
                out.append("\n".join(cur_lines))
                cur_lines, cur_len = [], 0
            if len(line) > LIMIT:
                # Single line longer than LIMIT: hard cut.
                if cur_lines:
                    out.append("\n".join(cur_lines))
                    cur_lines, cur_len = [], 0
                for i in range(0, len(line), LIMIT):
                    out.append(line[i : i + LIMIT])
                continue
            cur_lines.append(line)
            cur_len += llen
        if cur_lines:
            out.append("\n".join(cur_lines))
        return out

    chunks: list[str] = []
    paragraphs = full.split("\n\n")
    cur: list[str] = []
    cur_len = 0
    for p in paragraphs:
        # If the paragraph alone exceeds LIMIT, flush current and split it.
        if len(p) > LIMIT:
            if cur:
                chunks.append("\n\n".join(cur))
                cur, cur_len = [], 0
            chunks.extend(_split_oversized(p))
            continue
        plen = len(p) + 2
        if cur_len + plen > LIMIT and cur:
            chunks.append("\n\n".join(cur))
            cur, cur_len = [p], len(p)
        else:
            cur.append(p)
            cur_len += plen
    if cur:
        chunks.append("\n\n".join(cur))
    return chunks


_BOLD_RE = __import__("re").compile(r"\*\*(.+?)\*\*")
_ITALIC_RE = __import__("re").compile(r"(?<![*])\*(?!\s)(.+?)(?<!\s)\*(?![*])")
_CODE_RE = __import__("re").compile(r"`([^`]+)`")
_LINK_RE = __import__("re").compile(r"\[([^\]]+)\]\(([^)]+)\)")


def _inline_md(text: str) -> str:
    """Apply inline markdown → Telegram HTML, with proper escaping order."""
    # 1. Pull out code spans first, replace with placeholders, escape rest.
    placeholders: list[str] = []

    def _stash(m):
        placeholders.append(f"<code>{_html_escape(m.group(1))}</code>")
        return f"\x00{len(placeholders) - 1}\x00"

    text = _CODE_RE.sub(_stash, text)
    text = _html_escape(text)
    text = _BOLD_RE.sub(r"<b>\1</b>", text)
    text = _ITALIC_RE.sub(r"<i>\1</i>", text)
    text = _LINK_RE.sub(r'<a href="\2">\1</a>', text)

    # Restore code placeholders
    def _restore(m):
        return placeholders[int(m.group(1))]

    text = __import__("re").sub(r"\x00(\d+)\x00", _restore, text)
    return text


def cmd_setup(token: str) -> None:
    """Save BotFather token."""
    token = token.strip()
    if not token or ":" not in token:
        raise ValueError("Invalid token format. Expected: 123456789:AAHfiqksKZ8...")

    existing: dict = {}
    if _CONFIG_PATH.exists():
        try:
            existing = json.loads(_CONFIG_PATH.read_text())
        except Exception:
            pass

    existing["token"] = token
    save_config(existing)
    print(f"Token saved to {_CONFIG_PATH}")
    print("Next step: terrafin-signals telegram pair")


def cmd_pair(timeout: int = 60) -> None:
    """Poll getUpdates until the user sends a message, then save chat_id."""
    try:
        import httpx
    except ImportError as exc:
        raise RuntimeError("httpx is required: pip install httpx") from exc

    cfg = load_config()
    token = cfg.get("token", "")
    if not token:
        raise RuntimeError("Token not set. Run: terrafin-signals telegram setup <token>")

    bot_info = httpx.get(_api_url(token, "getMe"), timeout=10).json()
    username = bot_info.get("result", {}).get("username", "your_bot")
    print(f"Bot ready: @{username}")
    print(f"Open Telegram, DM @{username} anything. Waiting {timeout}s...")

    offset = 0
    deadline = time.time() + timeout
    while time.time() < deadline:
        resp = httpx.get(
            _api_url(token, "getUpdates"),
            params={"offset": offset, "timeout": 5, "limit": 1},
            timeout=15,
        ).json()
        updates = resp.get("result", [])
        for update in updates:
            offset = update["update_id"] + 1
            msg = update.get("message") or update.get("channel_post")
            if msg:
                chat_id = str(msg["chat"]["id"])
                sender = msg.get("from", {}).get("username") or msg.get("from", {}).get("first_name", "?")
                cfg["chat_id"] = chat_id
                save_config(cfg)
                print(f"Paired! chat_id={chat_id} (from @{sender})")
                print("Test with: terrafin-signals telegram test")
                return

    print("Timeout — no message received. Try again.")


def cmd_test() -> None:
    """Send a test signal to verify the setup."""
    ch = TelegramChannel.from_config()
    ch.send(
        title="TerraFin Signal Test",
        body_md="Test message from TerraFin signals.",
        payload={"signals": [{"severity": "low", "ticker": "TEST", "message": "Setup is working."}]},
    )
    print("Test message sent.")
