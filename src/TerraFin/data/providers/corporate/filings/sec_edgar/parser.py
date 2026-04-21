"""SEC 10-K / 10-Q HTML → markdown conversion for LLM consumption."""

import logging
import re

import sec_parser as sp
from bs4 import BeautifulSoup
from sec_parser.semantic_elements import (
    ImageElement,
    SupplementaryText,
    TableElement,
    TextElement,
    TitleElement,
    TopSectionTitle,
)

log = logging.getLogger(__name__)

_ALT_MAX = 120
_DATA_URI_RE = re.compile(r"^data:([^;,]+)", re.IGNORECASE)
_WHITESPACE_RE = re.compile(r"\s+")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_SLUG_STRIP_RE = re.compile(r"[^\w\s-]")
_SLUG_COLLAPSE_RE = re.compile(r"[\s-]+")
_SLUG_MAX_LEN = 80

# Canonical SEC 10-K / 10-Q section-heading pattern. Matches `Part I`,
# `PART II`, `Item 7.`, `Item 7A — MD&A`, etc. — any leading Part/Item
# marker. sec_parser's Edgar10QParser frequently misses Item 7 / Item 8
# in 10-Ks because its heuristics are 10-Q-tuned, so we fall back to a
# text-level scan over raw element text.
_SECTION_HEADING_RE = re.compile(
    r"^\s*(part\s+[ivx]+|item\s+\d+[a-z]?)\b",
    re.IGNORECASE | re.MULTILINE,
)

# sec_parser occasionally splits a heading mid-word when the source HTML wraps
# the title text in nested spans or stray <br> tags — ZETA's 10-K produces
# `TopSectionTitle("Item 1. Bus")` + `TitleElement("iness.")`, which we emit
# as `## Item 1. Bus\n\n### iness.` and then display as a broken accordion
# entry. Heal the pattern in post-processing: splice the broken fragments
# back together (no space — it's the same word). `re.MULTILINE` so `^`
# matches every line start.
#
# False-positive guard: the parent line's trailing word must be exactly
# three characters, title-case (one uppercase + two lowercase). This is
# narrow enough to exclude:
#   - all-caps acronyms like `## RISKS` + `### related` (no lowercase)
#   - possessives like `## Company's` + `### own` (word too long)
#   - complete standalone words like `## Note` + `### overview`
#     (four chars, wouldn't match three-char limit)
# while still catching the real sec_parser splits we've seen in the wild
# (`Bus` + `iness`, and similar 3-char prefixes that look incomplete).
#
# Word-continuation branch: continuation starts with a lowercase letter
# (word rest). Uses the narrow parent guard.
_BROKEN_TITLE_WORD_RE = re.compile(
    r"^(## [^\n]*?\b[A-Z][a-z]{2})\n+### ([a-z][^\n]*)\n",
    re.MULTILINE,
)
# Punctuation-only branch: a standalone `### .` (or `,` / `;` / `:` / `!` /
# `?`) line is never a legitimate sub-heading — it's always sec_parser
# emitting the terminator as its own element. Safe to splice onto any
# letter-ending parent, so chains like `## Bus\n### iness\n### .` heal
# cleanly: pass 1 merges the word, pass 2 merges the terminator.
_BROKEN_TITLE_TERMINATOR_RE = re.compile(
    r"^(## [^\n]*?[A-Za-z])\n+### ([.,;:!?])\n",
    re.MULTILINE,
)

# sec_parser Edgar10QParser often mis-classifies 10-K top-level sections
# (ITEM 1A, ITEM 7, etc.) as TitleElement (###) instead of TopSectionTitle (##).
# These patterns heal the hierarchy by merging the Item label and its title
# into a single level 2 heading.
#
# The first line can be either ``## ITEM 9B.`` (correctly classified as
# TopSectionTitle) or ``### ITEM 9B.`` (mis-classified as TitleElement) —
# both observed across GOOGL / MSFT / JPM 10-K filings where the bare
# Item label is rendered in its own element separate from the descriptive
# title. The continuation must be ``### TITLE`` and the title must NOT
# itself start with another ITEM/PART marker (guards against merging
# `## ITEM 9.\n### ITEM 10.` on adjacent items).
#
# Require the Item token to be `\d+[A-Z]?` (a digit + optional single
# letter suffix like 7A) and the trailing `.` optional. Bare `\w+` from
# the previous version matched ambiguous body text like `"item 1 was"`
# — legitimate `### item foo` H3 sub-sections would be promoted to a
# bogus `## ITEM foo` top-level entry.
_MERGE_ITEM_HEADING_RE = re.compile(
    r"^##+\s+(ITEM\s+\d+[A-Z]?\.?)\s*\n+###\s+(?!ITEM\b|PART\b)([A-Z][^\n]+)$",
    re.MULTILINE | re.IGNORECASE,
)
_PROMOTE_ITEM_HEADING_RE = re.compile(
    r"^###\s+(ITEM\s+\d+[A-Z]?\.?)\s*$",
    re.MULTILINE | re.IGNORECASE,
)

# A second flavour of title fragmentation: the Item label + part of the
# title sit on the same line, but the rest of the title spills into a
# following `###` element. MSFT 10-K shows
#   `## ITEM 9B. OTHER` + `### INFORMATION`            (phrase split)
#   `## ITEM 9C. DISCLOSURE REGARDING FOREIGN J` + `### URISDICTIONS …`
#                                                       (mid-word split)
# Both heal to a single `## ITEM XX. <full title>` line. The continuation
# must NOT itself look like a new Item/Part marker, otherwise we'd glue
# adjacent items together.
# Both parent and continuation must be UPPERCASE-only (apart from
# punctuation / digits / brackets / smart-quotes) — sub-sections like
# ``### Insider Trading Arrangements`` (mixed case) must not be sucked
# into the title. Char class covers MSFT 10-K's ``[Reserved]`` brackets
# and Microsoft / Google's ``MANAGEMENT'S`` U+2019 right single quote.
_UPPER_TITLE_BODY = r"[A-Z0-9 ,&'‘’“”\-\/\(\)\.\[\]]"
_UPPER_TITLE_START = r"[\[A-Z]"
_UPPER_TITLE_TOKEN = rf"{_UPPER_TITLE_START}{_UPPER_TITLE_BODY}+"
_BROKEN_ITEM_TITLE_SPLIT_RE = re.compile(
    rf"^(##\s+ITEM\s+\d+[A-Z]?\.\s+{_UPPER_TITLE_TOKEN})\n+###\s+(?!ITEM\b|PART\b)({_UPPER_TITLE_TOKEN})\n",
    re.MULTILINE,
)


def _heal_item_title_split(match: "re.Match[str]") -> str:
    parent = match.group(1).rstrip()
    cont = match.group(2).rstrip()
    # Narrow mid-word join: only when parent ends with a single trailing
    # uppercase letter preceded by something that is NOT another letter
    # (space, ``[``, ``(``, etc). That is an unambiguous fragment marker
    # — a single isolated capital letter that nearly always means
    # sec_parser broke a word at an HTML span boundary. Examples healed:
    #   ``… FOREIGN J`` + ``URISDICTIONS …`` -> ``… FOREIGN JURISDICTIONS …``
    #   ``… [R``         + ``ESERVED]``        -> ``… [RESERVED]``
    # Multi-letter trailing fragments (OFF, EXECUTI, OWN) can't be told
    # from real-word endings, so default to a space join — the title
    # remains readable even if not perfect.
    if re.search(r"(?<![A-Za-z])[A-Z]$", parent):
        return parent + cont + "\n"
    return parent + " " + cont + "\n"



def parse_sec_filing(html_content, filing_form="10-Q", *, include_images: bool = False):
    """
    Parse SEC filing HTML content into structured markdown.

    Args:
        html_content: Raw HTML content from SEC filing.
        filing_form: Filing form descriptor (e.g. "10-Q", "10-K", "10-K/A",
            "FORM 10-Q", or anything containing "10-K" / "10-Q").
        include_images: When True, emit markdown image tags for inline images.
            Default is False because a 10-K often embeds many signature/chart
            images whose src URLs the downstream LLM cannot fetch, so enabling
            images burns tokens with little value unless the caller is
            specifically interested in visual content.

    Returns:
        Parsed content as a markdown string.
    """
    form = (filing_form or "").upper()
    if "10-Q" in form:
        return _parse_filing(html_content, include_images=include_images)
    if "10-K" in form:
        # sec_parser only ships Edgar10QParser; the 10-K semantic-title heuristics
        # are 10-Q-biased and may mis-classify some 10-K sections. Surface this
        # via a log so regressions here are at least observable.
        log.info("Parsing 10-K filing with Edgar10QParser (sec_parser has no dedicated 10-K parser)")
        return _parse_filing(html_content, include_images=include_images)
    raise ValueError(f"Filing form '{filing_form}' not supported.")


def _split_into_heading_chunks(text: str) -> list[tuple[str | None, str]]:
    """Split a text blob into `[(heading, body), ...]` chunks whenever a
    line starts with a Part/Item marker.

    sec_parser's Edgar10QParser routinely fuses multiple SEC section
    headings and their bodies into one TextElement — the ZETA 10-K
    case. Splitting only at the FIRST heading (as an earlier version
    did) leaves Items 7A, 8, 9 etc. buried as body prose under
    Item 7's heading; they never appear in the TOC.

    Returns a list of `(heading_line, body)` pairs. A leading preamble
    before the first heading (e.g. `"Table of Contents\\nItem 7. MD&A..."`)
    surfaces as `(None, preamble_text)` so the caller can emit it
    separately.
    """
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = normalized.split("\n")

    chunks: list[tuple[str | None, str]] = []
    current_heading: str | None = None
    current_body: list[str] = []

    def _flush() -> None:
        # Emit the accumulated chunk. Preamble (no heading, no body)
        # is skipped; empty body under a heading is preserved as "".
        body = "\n".join(current_body).strip("\n")
        if current_heading is not None:
            chunks.append((current_heading, body))
        elif body.strip():
            chunks.append((None, body))

    for line in lines:
        if _SECTION_HEADING_RE.match(line):
            _flush()
            current_heading = line.strip()
            current_body = []
        else:
            current_body.append(line)
    _flush()
    return chunks


def _looks_like_section_heading(text: str) -> bool:
    """True when the text starts with a Part/Item section marker
    OR contains an embedded Part/Item line further down.

    sec_parser sometimes emits `"Table of Contents\\nItem 7. MD&A\\n..."`
    (preamble then heading fused). Surface-level `match` would miss
    Item 7 in that case; `search` with MULTILINE catches it so the
    caller's split logic can then promote it.
    """
    if not text:
        return False
    return bool(_SECTION_HEADING_RE.search(text))


def _emit_heading(text: str, *, default_level: int) -> str:
    """Render heading line(s), overriding sec_parser's level when needed.

    When the text contains one or more Part/Item markers (possibly
    embedded below a preamble, possibly multiple fused together),
    split with `_split_into_heading_chunks` and emit each heading as
    level 2 (the canonical TOC level) followed by its body. Any
    preamble before the first heading emits at `default_level` so it
    still surfaces in the document flow but doesn't shadow the Item
    entries in the TOC.
    """
    if _SECTION_HEADING_RE.search(text):
        chunks = _split_into_heading_chunks(text)
        rendered: list[str] = []
        for heading, body in chunks:
            if heading is None:
                # Preamble — emit at the original default level so it
                # stays in the rendered document but only if it looks
                # like a real sub-heading (single short line).
                preamble = body.strip()
                if preamble and "\n" not in preamble and len(preamble) < 200:
                    rendered.append(f"{'#' * default_level} {preamble}\n")
                elif preamble:
                    rendered.append(preamble + "\n")
            else:
                rendered.append(f"## {heading}\n")
                if body.strip():
                    rendered.append(body + "\n")
        return "".join(rendered)
    return f"{'#' * default_level} {text}\n"


def _parse_filing(html_content, *, include_images: bool) -> str:
    elements = sp.Edgar10QParser().parse(html_content)

    parts: list[str] = []
    for element in elements:
        text = (element.text or "").strip()
        if isinstance(element, TopSectionTitle):
            parts.append(_emit_heading(text, default_level=2))
        elif isinstance(element, TitleElement):
            parts.append(_emit_heading(text, default_level=3))
        elif isinstance(element, (TextElement, SupplementaryText)):
            # Promote plain text that contains an SEC Part/Item marker.
            # Edgar10QParser is 10-Q-biased; 10-K Item 7 (MD&A), 7A,
            # and 8 (Financial Statements) are routinely emitted as
            # TextElement blobs that fuse multiple Item headings with
            # their bodies — the ZETA 10-K failure mode. Running the
            # chunk split here surfaces every embedded Item heading,
            # not just the first one.
            if _looks_like_section_heading(text):
                chunks = _split_into_heading_chunks(text)
                for heading, body in chunks:
                    if heading is None:
                        if body.strip():
                            parts.append(body + "\n")
                    else:
                        parts.append(f"## {heading}\n")
                        if body.strip():
                            parts.append(body + "\n")
            else:
                parts.append(text + "\n")
        elif isinstance(element, TableElement):
            parts.append(_table_to_md(element) + "\n")
        elif include_images and isinstance(element, ImageElement):
            rendered = _image_to_md(element)
            if rendered:
                parts.append(rendered + "\n")
        # Other element types (PageHeader, PageNumber, Irrelevant, Empty,
        # NotYetClassified) are intentionally skipped as noise.

    markdown = "\n".join(parts)
    return _heal_broken_titles(markdown)


def _heal_broken_titles(markdown: str) -> str:
    """Merge mid-word title splits that sec_parser occasionally emits.

    Runs the splice repeatedly so chains like
    `## Item 1. Bus / ### iness / ### .` heal one pass at a time until
    nothing more matches.
    """
    previous = None
    current = markdown
    passes = 0
    while previous != current and passes < 5:
        previous = current
        current, word_hits = _BROKEN_TITLE_WORD_RE.subn(r"\1\2\n", current)
        current, term_hits = _BROKEN_TITLE_TERMINATOR_RE.subn(r"\1\2\n", current)
        current, item_split_hits = _BROKEN_ITEM_TITLE_SPLIT_RE.subn(_heal_item_title_split, current)
        current, merge_hits = _MERGE_ITEM_HEADING_RE.subn(r"## \1 \2\n", current)
        current, promote_hits = _PROMOTE_ITEM_HEADING_RE.subn(r"## \1\n", current)
        total = word_hits + term_hits + item_split_hits + merge_hits + promote_hits
        if total:
            log.info("Merged/Promoted %d broken or misclassified SEC heading(s) on pass %d", total, passes + 1)
        passes += 1
    return current


def _image_to_md(element: ImageElement) -> str:
    """Render an ImageElement as sanitized markdown `![alt](src)`.

    - Data URIs are replaced with a `<inline-image:{mime}>` placeholder so a
      100 KB base64 payload doesn't land in the LLM context.
    - `alt` text is whitespace-collapsed and truncated to mitigate prompt
      injection via attacker-crafted alt text in untrusted filings.
    """
    soup = BeautifulSoup(element.get_source_code(), "html.parser")
    img = soup.find("img")
    if img is None:
        return ""

    raw_src = (img.get("src") or "").strip()
    raw_alt = img.get("alt") or ""
    alt = _WHITESPACE_RE.sub(" ", raw_alt).strip()
    if len(alt) > _ALT_MAX:
        alt = alt[: _ALT_MAX - 1] + "\u2026"

    mime_match = _DATA_URI_RE.match(raw_src)
    if mime_match:
        src = f"<inline-image:{mime_match.group(1)}>"
    else:
        src = raw_src or "<inline-image>"

    return f"![{alt}]({src})"


def _table_to_md(element: TableElement) -> str:
    """Rule-based `<table>` HTML → GFM conversion with a sec_parser fallback.

    `sec_parser`'s built-in `TableElement.table_to_markdown()` preserves cells
    verbatim but keeps all of SEC's alignment-spacer `<td>`s and splits every
    currency amount into multiple cells (a bare `$` cell followed by the
    number), so the output is typically unreadable for an LLM: long rows of
    ``| | | $ | 135.0 | | | | $ | 671.0 |`` etc.

    This implementation walks `element.get_source_code()` directly with
    BeautifulSoup and reconstructs a clean GFM table. Fixtures for every
    rule live in ``tests/data/fixtures/sec_edgar_tables/``; the iteration
    loop in ``tests/data/test_sec_edgar_table_rules.py`` is the spec.

    Rules applied in order:
        R1  row = one <tr>; cells = <th> + <td> in document order
        R2  colspan → repeat cell text N times
        R3  rowspan → propagate cell down N rows
        R4  cell-text normalize (<br> → space, &nbsp; / zero-width → space,
            collapse whitespace, strip)
        R5  escape bare ``|`` in cell text
        R6  merge bare-symbol cells forward (``$`` + ``135.0`` → ``$ 135.0``)
        R7  (neg-paren tag only — text unchanged)
        R8  drop columns whose body rows are all whitespace
        R9  collapse multi-row header into a single row joined with newlines
        R10 (units-row tag only — text unchanged; R9 will absorb it)
        R11 footnote markers (1), (2) left attached to preceding token
        R12 nested <table>: flattened to inline text, no recursion
        R13 emit header + GFM separator + body
        R14 on any failure or degenerate shape (<2 columns, 0 body rows)
            fall back to ``element.table_to_markdown()``
    """
    html = getattr(element, "get_source_code", lambda: "")() or ""
    try:
        rebuilt = _rebuild_table_markdown(html)
    except Exception:  # pragma: no cover - safety net keeps the agent working
        log.exception("rule-based table rebuild failed; falling back to sec_parser output")
        rebuilt = None
    if rebuilt is not None:
        return rebuilt
    return element.table_to_markdown()


# ---------------------------------------------------------------------------
# Rule-based table reconstruction
# ---------------------------------------------------------------------------

_TABLE_NBSP_CHARS = "\u00a0\u200b\u200c\u200d\ufeff"
_TABLE_WS_RE = re.compile(r"\s+")
_TABLE_BARE_SYMBOL_RE = re.compile(r"^[\$\(\)%]+$")
_TABLE_UNITS_RE = re.compile(r"^\(in (millions|thousands|billions|ones|\$ millions)[^)]*\)$", re.IGNORECASE)


def _clean_table_cell(cell) -> str:
    for br in cell.find_all("br"):
        br.replace_with(" ")
    # Flatten any nested tables to a single text blob (R12).
    for nested in cell.find_all("table"):
        nested.replace_with(nested.get_text(" ", strip=True))
    text = cell.get_text(" ", strip=True)
    for ch in _TABLE_NBSP_CHARS:
        text = text.replace(ch, " ")
    text = _TABLE_WS_RE.sub(" ", text).strip()
    return text.replace("|", "\\|")


def _extract_rows(table) -> list[list[dict]]:
    """Return a list of rows, each a list of cell dicts: text, colspan, rowspan, tag.

    Empty cells are kept (spacer columns are dropped later by R8).
    """
    rows: list[list[dict]] = []
    for tr in table.find_all("tr"):
        row: list[dict] = []
        for cell in tr.find_all(["th", "td"], recursive=False):
            try:
                colspan = max(1, int(cell.get("colspan") or 1))
            except (TypeError, ValueError):
                colspan = 1
            try:
                rowspan = max(1, int(cell.get("rowspan") or 1))
            except (TypeError, ValueError):
                rowspan = 1
            row.append(
                {
                    "text": _clean_table_cell(cell),
                    "colspan": colspan,
                    "rowspan": rowspan,
                    "tag": cell.name,
                }
            )
        if row:
            rows.append(row)
    return rows


def _expand_to_grid(rows: list[list[dict]]) -> list[list[str]]:
    """Expand rows into a dense text grid, honoring colspan and rowspan (R2, R3)."""
    max_cols = 0
    for row in rows:
        max_cols = max(max_cols, sum(c["colspan"] for c in row))
    if max_cols == 0:
        return []
    grid: list[list[str]] = []
    # `carry[j] = (text, rows_left)` for cells propagated from an earlier row.
    carry: list[tuple[str, int] | None] = [None] * max_cols
    for row in rows:
        line: list[str] = [""] * max_cols
        # Apply rowspan carry first.
        for j in range(max_cols):
            if carry[j] is not None:
                line[j] = carry[j][0]
                carry[j] = (carry[j][0], carry[j][1] - 1) if carry[j][1] > 1 else None
        # Fill remaining columns left-to-right.
        j = 0
        for cell in row:
            # Skip over already-filled (carried) slots.
            while j < max_cols and carry[j] is not None:
                j += 1
            span = min(cell["colspan"], max_cols - j)
            for k in range(span):
                line[j + k] = cell["text"]
            if cell["rowspan"] > 1 and span > 0:
                for k in range(span):
                    carry[j + k] = (cell["text"], cell["rowspan"] - 1)
            j += span
        grid.append(line)
    return grid


def _merge_bare_symbols(row: list[str]) -> list[str]:
    """R6: fuse bare `$` / `(` / `)` / `%` cells with the next non-empty cell."""
    out: list[str] = []
    i = 0
    n = len(row)
    while i < n:
        cell = row[i]
        if _TABLE_BARE_SYMBOL_RE.fullmatch(cell):
            j = i + 1
            while j < n and not row[j].strip():
                j += 1
            if j < n:
                out.append((cell + " " + row[j]).strip())
                # Mark consumed cells empty so column-dropper still sees their slot.
                for _ in range(i + 1, j + 1):
                    out.append("")
                i = j + 1
                continue
        out.append(cell)
        i += 1
    return out


def _drop_empty_columns(rows: list[list[str]], *, preserve_first: bool = True) -> list[list[str]]:
    """R8: drop columns that are empty across every row. Keep first column if asked."""
    if not rows:
        return rows
    width = len(rows[0])
    keep = []
    for c in range(width):
        if preserve_first and c == 0:
            keep.append(c)
            continue
        if any(row[c].strip() for row in rows):
            keep.append(c)
    if len(keep) == width:
        return rows
    return [[row[c] for c in keep] for row in rows]


def _is_width_setter_row(row: list[dict]) -> bool:
    """SEC filings lead with a row of empty ``<td>`` cells whose sole purpose
    is to set column widths via inline ``width:%`` styles. A row is a width-
    setter if every cell is empty — colspan/rowspan vary (some SEC writers
    collapse trailing empties into one colspan=N cell)."""
    if not row:
        return True
    return all(not c["text"] for c in row)


def _is_title_row(row: list[dict]) -> bool:
    """Some SEC tables lead with a one-cell caption row (colspan spans the
    entire table width) — e.g. ``"Selected Consolidated Financial Data"``
    or ``"Equity Compensation Plan Information"``. Using such a row as the
    column ruler collapses everything into one group. Skip it.
    """
    if not row:
        return False
    non_empty = [c for c in row if c["text"]]
    return len(non_empty) == 1 and len(row) == 1


_HEADER_LABEL_RE = re.compile(
    r"^("
    r"\d{4}"                                # 2024, 2025
    r"|\d{1,2}/\d{1,2}/\d{2,4}"             # 6/30/2025
    r"|\w+ \d{1,2},? ?\d{0,4}"              # June 29, 2025
    r"|Level [123]"                          # fair-value hierarchy
    r"|Change"
    r"|Total"
    r"|\$"
    r"|\(in [^)]+\)"                         # (in millions)
    r"|Year ended \w+"
    r"|Q[1-4]"
    r"|[A-Z]{2,5}"                           # OI&E, AOCI, GAAP
    r")$"
)


def _looks_like_body_value(text: str) -> bool:
    """True when a cell *looks like body data*: a dollar amount, percent,
    paren-negative, decimal, comma-thousands magnitude, OR a plain integer
    that is not a 4-digit year. Years stay on the header side.

    Used by ``_row_looks_like_body`` to catch TOC-shaped tables where the
    data column is just page numbers like ``"45"``, ``"53"`` — bare
    integers that ``_looks_numeric`` deliberately rejects because ``"45"``
    could also be a header label in other contexts.
    """
    stripped = text.strip()
    if not stripped:
        return False
    if re.fullmatch(r"(19|20)\d{2}", stripped):
        return False
    if _looks_numeric(stripped):
        return True
    if re.fullmatch(r"\d+", stripped):
        return True
    return False


def _looks_numeric(text: str) -> bool:
    """Rough detector — used to decide whether a row is body-shaped.

    Intentionally conservative: bare 4-digit years (``19xx`` / ``20xx``) are
    excluded because they appear as header labels in SEC period tables, and
    plain integers without punctuation are ambiguous (year, item count,
    page number) so we require a currency / decimal / comma / paren /
    percent marker before calling something numeric.
    """
    stripped = text.strip()
    if not stripped:
        return False
    # Bare year → treated as a label, not a data value.
    if re.fullmatch(r"(19|20)\d{2}", stripped):
        return False
    # Comma-separated magnitude (most SEC dollar amounts).
    if re.search(r"\d{1,3}(?:,\d{3})+", stripped):
        return True
    # Negative in parentheses.
    if re.fullmatch(r"\(\s*\d[\d,\.]*\s*\)", stripped):
        return True
    # Currency, percent, decimal, signed.
    if re.fullmatch(r"[\$\-\+]?\s*\d[\d,\.]*\s*%?", stripped) and (
        "$" in stripped or "%" in stripped or "." in stripped or "," in stripped
    ):
        return True
    return False


def _row_looks_like_body(row: list[str]) -> bool:
    """True for any non-header row: a body data row, a sub-section separator
    row (label-only in column 0), or a totals row.

    Rules (first match wins):
      - col 0 has text AND every later column is empty → body (sub-section).
      - col 0 has text AND ≥ 1 later column is numeric → body (data row).
      - col 0 empty AND ≥ 2 later columns are numeric → body (headerless
        continuation, rare).
      - col 0 is ``Total ``, ``Less:``, ``Plus:`` prefix → body (totals).
    """
    if not row:
        return False
    col0 = row[0].strip()
    others = [c.strip() for c in row[1:]]
    other_with_content = sum(1 for c in others if c)
    other_numeric = sum(1 for c in others if _looks_numeric(c))

    if col0:
        # Descriptive text + any body-value payload = body. Checked FIRST so
        # that a short acronym like "TAC" / "AMD" in col 0 is treated as a
        # row label, not a header token, when the row clearly has data —
        # and so page-number style tables (TOC: "...Balance Sheets | 48")
        # get classified correctly even though plain integers miss the
        # stricter ``_looks_numeric`` check.
        other_body_values = sum(1 for c in others if _looks_like_body_value(c))
        if re.search(r"[A-Za-z]{3,}", col0) and other_body_values >= 1:
            return True
        if other_with_content == 0:
            return True  # sub-section label / date row
        if col0.startswith(("Total ", "Less:", "Plus:")):
            return True
        # Header labels like "2025" / "Change" — no numeric payload anywhere.
        if _HEADER_LABEL_RE.fullmatch(col0):
            return False
    else:
        if other_numeric >= 2:
            return True
    return False


def _classify_header_count(collapsed_rows: list[list[str]]) -> int:
    """Return how many leading rows are still header rows after group-collapse.

    Walk from the top and extend the header block as long as the next row
    does not look like a body row (``_row_looks_like_body``). Minimum 1.
    """
    if not collapsed_rows:
        return 0
    n = 1
    for row in collapsed_rows[1:]:
        if _row_looks_like_body(row):
            break
        n += 1
    # Safety: don't classify everything as header.
    if n == len(collapsed_rows):
        return 1
    return n


def _merge_header_grid(header_lines: list[list[str]]) -> list[str]:
    """R9: collapse multi-row header text column-wise, joined with '\\n'."""
    if not header_lines:
        return []
    width = len(header_lines[0])
    out: list[str] = []
    for c in range(width):
        parts: list[str] = []
        for row in header_lines:
            text = row[c].strip()
            if text and (not parts or parts[-1] != text):
                parts.append(text)
        out.append("\n".join(parts))
    return out


def _build_column_groups(header_rows: list[list[dict]], *, total_width: int | None = None) -> list[dict] | None:
    """Given the detected header rows, return a list of column groups as
    ``{"start": int, "width": int}`` intervals.

    Uses the **union** of every header row's cell-boundaries plus the overall
    grid ``total_width`` (so body cells past the last header boundary still
    land inside a group). Different header levels often disagree on
    granularity — a top-level year row has one colspan-covering cell while
    the sub-header row below it partitions that span into individual
    metrics. The union gives the finest-grained split that still respects
    every header row's cell structure.
    """
    if not header_rows:
        return None
    boundaries: set[int] = {0}
    max_header_width = 0
    for row in header_rows:
        col = 0
        for cell in row:
            col += max(1, cell["colspan"])
            boundaries.add(col)
        max_header_width = max(max_header_width, col)
    width = max(max_header_width, total_width or 0)
    if width == 0:
        return None
    boundaries.add(width)
    sorted_b = sorted(b for b in boundaries if b <= width)
    groups: list[dict] = []
    for start, end in zip(sorted_b, sorted_b[1:]):
        groups.append({"start": start, "width": end - start})
    return groups


def _collapse_row_into_groups(row: list[str], groups: list[dict], *, is_header: bool) -> list[str]:
    """Collapse a dense-grid row into one cell per header group.

    - For headers: take the first non-empty text (colspan-expanded duplicates
      collapse to one).
    - For body: apply bare-symbol merge (R6) within the slab, then de-dup
      adjacent identical texts before joining — colspan-expansion copies
      like ``"111,032 111,032"`` reduce to ``"111,032"``.
    """
    out: list[str] = []
    for g in groups:
        slab = row[g["start"] : g["start"] + g["width"]]
        merged = _merge_bare_symbols(slab) if not is_header else slab
        meaningful = [c for c in merged if c.strip()]
        if not meaningful:
            out.append("")
            continue
        if is_header:
            out.append(meaningful[0])
            continue
        # De-dup adjacent duplicates (colspan-expansion artefact).
        deduped: list[str] = []
        for cell in meaningful:
            if not deduped or deduped[-1] != cell:
                deduped.append(cell)
        if len(deduped) == 1:
            out.append(deduped[0])
        else:
            out.append(" ".join(deduped))
    return out


def _merge_header_lines(header_rows: list[list[str]]) -> list[str]:
    """R9: stack multi-row headers column-wise, joined by '\\n' and deduped."""
    if not header_rows:
        return []
    width = len(header_rows[0])
    stacked: list[str] = []
    for c in range(width):
        parts: list[str] = []
        for row in header_rows:
            text = row[c].strip() if c < len(row) else ""
            if text and text not in parts:
                parts.append(text)
        stacked.append("\n".join(parts))
    return stacked


def _column_has_distinguishing_header(col: int, header_rows: list[list[str]]) -> bool:
    """True if some header row assigns this column text that is not
    identical to *both* of its immediate neighbours (or: not identical to
    its only neighbour, at the edges).

    Uniform-across-every-column content (year labels with wide colspan,
    ``(In millions)`` units rows, etc.) collapses into "not
    distinguishing" — a column that only has such content is effectively a
    spacer. Columns whose sub-header text differs between neighbours
    (Level 1 / Level 2 / Level 3, 2024 / 2025) stay distinguishing and
    are preserved.
    """
    if not header_rows:
        return False
    for row in header_rows:
        if col >= len(row):
            continue
        text = row[col].strip()
        if not text:
            continue
        left = row[col - 1].strip() if col - 1 >= 0 else None
        right = row[col + 1].strip() if col + 1 < len(row) else None
        differs_left = left is not None and text != left
        differs_right = right is not None and text != right
        if left is None:
            # leftmost column: distinguishing if it differs from its right
            # neighbour (or has text where the neighbour is empty)
            if differs_right:
                return True
        elif right is None:
            if differs_left:
                return True
        else:
            if differs_left and differs_right:
                return True
    return False


def _merge_adjacent_duplicate_columns(
    header: list[str], body_rows: list[list[str]]
) -> tuple[list[str], list[list[str]]]:
    """Fuse adjacent columns when every row agrees (identical text or one
    side empty) for both the header and all body rows.

    Triggered when a body cell's ``colspan`` exceeds a header group width —
    the colspan expansion then duplicates the value across two or more
    adjacent groups. Merging folds them back to one column.
    """
    def _compatible(a: str, b: str) -> bool:
        if not a or not b:
            return True
        return a == b

    def _pick(a: str, b: str) -> str:
        # Prefer non-empty; when both set and equal, either works.
        return a if a else b

    changed = True
    while changed and len(header) > 1:
        changed = False
        c = 0
        while c < len(header) - 1:
            if not _compatible(header[c], header[c + 1]):
                c += 1
                continue
            if not all(
                _compatible(
                    row[c] if c < len(row) else "",
                    row[c + 1] if c + 1 < len(row) else "",
                )
                for row in body_rows
            ):
                c += 1
                continue
            # Merge c and c+1.
            header = header[:c] + [_pick(header[c], header[c + 1])] + header[c + 2 :]
            body_rows = [
                (
                    row[:c]
                    + [_pick(row[c] if c < len(row) else "", row[c + 1] if c + 1 < len(row) else "")]
                    + row[c + 2 :]
                )
                for row in body_rows
            ]
            changed = True
            # Don't advance c — re-check after merge.
    return header, body_rows


def _rebuild_table_markdown(html: str) -> str | None:
    if not html or "<table" not in html.lower():
        return None
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    if table is None:
        return None
    rows = _extract_rows(table)
    # Drop SEC-style width-setter rows (leading rows of empty cells used only
    # to seed column widths via inline CSS) and any truly empty rows.
    rows = [r for r in rows if r and not _is_width_setter_row(r)]
    # Single-cell caption row at the top (e.g. "Selected Consolidated
    # Financial Data") collapses segmentation to one group when used as
    # the column ruler — strip it ONLY if there are wider rows below to
    # take over segmentation. Otherwise (a signature block where every
    # row is one-cell text) leave the rows alone so they emit as a
    # plain-text list later.
    while (
        len(rows) >= 2
        and _is_title_row(rows[0])
        and any(len(r) >= 2 for r in rows[1:])
    ):
        rows = rows[1:]
    if not rows:
        return None

    grid = _expand_to_grid(rows)
    if not grid:
        return None
    total_width = len(grid[0]) if grid else 0

    # First pass: provisional groups from row 0 (padded to grid width),
    # collapse every row, classify header vs body.
    provisional = _build_column_groups(rows[:1], total_width=total_width)
    if not provisional:
        return None
    provisional_collapsed = [
        _collapse_row_into_groups(r, provisional, is_header=False) for r in grid
    ]
    header_count = _classify_header_count(provisional_collapsed)

    # Second pass: rebuild groups as the union of every header row's cell
    # boundaries (extended to full grid width so body-only columns survive).
    groups = _build_column_groups(rows[:header_count], total_width=total_width)
    if not groups:
        return None
    header_rows_collapsed = [
        _collapse_row_into_groups(grid[i], groups, is_header=True)
        for i in range(header_count)
    ]
    body_rows_collapsed = [
        _collapse_row_into_groups(grid[i], groups, is_header=False)
        for i in range(header_count, len(grid))
    ]

    header = _merge_header_lines(header_rows_collapsed)
    if not header:
        return None

    # R8: drop spacer columns. A column is a spacer when every body row is
    # empty AND no header row gives it *distinguishing* text (text different
    # from at least one neighbour). The distinguishing check defeats the
    # trap where a units row like ``(In millions, except per-share amounts)``
    # spans every column via colspan — it looks non-empty on every column
    # but tells us nothing about the column identity. Level 1/2/3 fair-value
    # columns keep passing this check because their sub-header text
    # ("Level 1" / "Level 2" / "Level 3") genuinely differs per column.
    keep: list[int] = []
    for c in range(len(header)):
        body_has = any(row[c].strip() for row in body_rows_collapsed if c < len(row))
        distinguishing = _column_has_distinguishing_header(c, header_rows_collapsed)
        # Keep column 0 always (row labels live there).
        if c == 0 or body_has or distinguishing:
            keep.append(c)
    if not keep:
        return None
    header = [header[c] for c in keep]
    body_rows_collapsed = [
        [row[c] if c < len(row) else "" for c in keep]
        for row in body_rows_collapsed
    ]

    # Drop body rows that are entirely empty post-collapse.
    body_rows_collapsed = [row for row in body_rows_collapsed if any(c.strip() for c in row)]
    if not body_rows_collapsed:
        return None

    # Single-column "table" — almost always an auditor signature block,
    # firm address, or a stack of single-line statements wrapped in a
    # <table> for layout. Emitting it as a 1-column markdown table looks
    # ugly; emit each row as a plain paragraph instead.
    if len(header) < 2:
        lines = [row[0].strip() for row in body_rows_collapsed if row and row[0].strip()]
        if header[0].strip():
            lines.insert(0, header[0].strip())
        return "\n\n".join(lines) if lines else None

    # Post-pass: merge adjacent duplicate columns. When a body cell's
    # colspan crosses a header group boundary, the collapse step produces
    # identical text in adjacent columns — fuse them if no row disagrees.
    header, body_rows_collapsed = _merge_adjacent_duplicate_columns(
        header, body_rows_collapsed
    )
    if len(header) < 2:
        # After post-pass merge we collapsed to a single column — emit as
        # plain lines for the same reason as above.
        lines = [row[0].strip() for row in body_rows_collapsed if row and row[0].strip()]
        if header[0].strip():
            lines.insert(0, header[0].strip())
        return "\n\n".join(lines) if lines else None

    width = len(header)

    def _emit(row: list[str]) -> str:
        return "| " + " | ".join(c.replace("\n", "<br>") for c in row) + " |"

    sep = "| " + " | ".join(["---"] * width) + " |"
    return "\n".join([_emit(header), sep, *(_emit(r) for r in body_rows_collapsed)])


def _slugify(text: str, *, max_len: int = _SLUG_MAX_LEN) -> str:
    """GitHub-style anchor slug for a heading, capped at `max_len` chars.

    The cap exists because sec_parser occasionally tags a long boilerplate
    paragraph as a TitleElement; without the cap a 400-char paragraph
    becomes a 400-char slug that pollutes the TOC and makes agent
    navigation impossible. We truncate at the last word-boundary under
    the limit so slugs remain human-readable when this happens.
    """
    lowered = text.lower().strip()
    stripped = _SLUG_STRIP_RE.sub("", lowered)
    slug = _SLUG_COLLAPSE_RE.sub("-", stripped).strip("-")
    if len(slug) <= max_len:
        return slug
    truncated = slug[:max_len]
    last_hyphen = truncated.rfind("-")
    # Prefer a clean word boundary when one is nearby; otherwise hard-truncate.
    if last_hyphen > max_len // 2:
        truncated = truncated[:last_hyphen]
    return truncated.rstrip("-")


def build_toc(markdown: str, *, max_level: int | None = 2) -> list[dict]:
    """Extract a flat table of contents from parsed filing markdown.

    Each entry is
    ``{"level": int, "text": str, "line_index": int, "slug": str, "char_count": int}``
    where ``char_count`` is the size of the section body (chars between this
    heading and the next kept heading, or the end of the document). Agents can
    use this to budget context before requesting a section body.

    Args:
        markdown: Parsed filing markdown, typically from ``parse_sec_filing``.
        max_level: Keep only headings up to this level. Defaults to ``2`` so
            agents see the canonical Part/Item scaffold of a 10-K/10-Q
            (~15–25 entries) without every nested sub-title. Pass ``None`` for
            the full hierarchy, or a higher number (e.g. ``3``) to drill in.
    """
    lines = markdown.splitlines()

    entries: list[dict] = []
    used_slugs: set[str] = set()
    for i, line in enumerate(lines):
        match = _HEADING_RE.match(line)
        if not match:
            continue
        level = len(match.group(1))
        if max_level is not None and level > max_level:
            continue
        # Strip trailing CR (survives from EDGAR HTML on Windows filings)
        # and other whitespace before slugifying so the slug doesn't end
        # with a garbage `-r` suffix that breaks section lookup.
        text = match.group(2).strip().rstrip("\r")
        base_slug = _slugify(text)
        # De-duplicate against every slug already emitted — including
        # any legitimate `exhibits-2` that slugified cleanly from its
        # own heading. Increment the suffix until we find an unused
        # slug rather than using a plain per-base-slug counter, so a
        # filing with `Exhibits / Exhibits 2 / Exhibits / Exhibits`
        # yields `exhibits`, `exhibits-2`, `exhibits-3`, `exhibits-4`
        # instead of colliding the third entry with the second.
        final_slug = base_slug
        suffix = 2
        while final_slug in used_slugs:
            final_slug = f"{base_slug}-{suffix}"
            suffix += 1
        used_slugs.add(final_slug)
        entries.append(
            {
                "level": level,
                "text": text,
                "line_index": i,
                "slug": final_slug,
            }
        )

    # char_count := size of the body from the line after this heading up to
    # (but not including) the next kept heading. Each newline counts as 1 char.
    for idx, entry in enumerate(entries):
        body_start = entry["line_index"] + 1
        body_end = entries[idx + 1]["line_index"] if idx + 1 < len(entries) else len(lines)
        entry["char_count"] = sum(len(lines[j]) + 1 for j in range(body_start, body_end))

    return entries


