"""Tests for markdown→Telegram-HTML conversion + chunk splitting."""
from __future__ import annotations

from TerraFin.signals.channels.telegram import _markdown_to_telegram_html


def test_headings_become_bold():
    chunks = _markdown_to_telegram_html("# Title\n\nbody")
    assert any("<b>Title</b>" in c for c in chunks)


def test_bullets_become_unicode():
    chunks = _markdown_to_telegram_html("- one\n- two")
    out = "\n".join(chunks)
    assert "• one" in out and "• two" in out


def test_inline_bold_italic_code():
    chunks = _markdown_to_telegram_html("a **b** c *d* e `f`")
    out = "\n".join(chunks)
    assert "<b>b</b>" in out
    assert "<i>d</i>" in out
    assert "<code>f</code>" in out


def test_html_special_chars_escaped():
    chunks = _markdown_to_telegram_html("plain <script>alert(1)</script>")
    out = "\n".join(chunks)
    assert "&lt;script&gt;" in out
    assert "<script>" not in out


def test_long_input_splits_into_chunks_under_limit():
    paragraph = "word " * 200  # ~1000 chars
    md = "\n\n".join([paragraph] * 6)  # ~6000 chars total
    chunks = _markdown_to_telegram_html(md)
    assert len(chunks) >= 2
    for c in chunks:
        assert len(c) <= 3800


def test_oversized_single_paragraph_is_split():
    # One paragraph with no blank lines, way over 3800 chars.
    huge = "- item line " * 500  # ~6000 chars, no \n\n
    chunks = _markdown_to_telegram_html(huge)
    assert len(chunks) >= 2
    for c in chunks:
        assert len(c) <= 3800


def test_oversized_single_line_hard_cut():
    # No newlines at all — one giant line. Hard-cut path.
    line = "x" * 9000
    chunks = _markdown_to_telegram_html(line)
    assert len(chunks) >= 3
    for c in chunks:
        assert len(c) <= 3800


def test_chunks_balanced_tags_per_line():
    # Each emitted line emits balanced tags. A paragraph break cannot bisect a tag.
    md = "# H1\n\n**bold** text\n\n## H2\n\n*ital* text"
    chunks = _markdown_to_telegram_html(md)
    for c in chunks:
        assert c.count("<b>") == c.count("</b>")
        assert c.count("<i>") == c.count("</i>")
