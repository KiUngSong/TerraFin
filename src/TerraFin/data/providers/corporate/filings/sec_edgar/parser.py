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

from TerraFin.data.utils.md_to_df import from_md_to_df


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
# Require the Item token to be `\d+[A-Z]?` (a digit + optional single
# letter suffix like 7A) and the trailing `.` optional. Bare `\w+` from
# the previous version matched ambiguous body text like `"item 1 was"`
# — legitimate `### item foo` H3 sub-sections would be promoted to a
# bogus `## ITEM foo` top-level entry.
_MERGE_ITEM_HEADING_RE = re.compile(
    r"^###\s+(ITEM\s+\d+[A-Z]?\.?)\s*\n+###\s+([A-Z][^\n]+)$",
    re.MULTILINE | re.IGNORECASE,
)
_PROMOTE_ITEM_HEADING_RE = re.compile(
    r"^###\s+(ITEM\s+\d+[A-Z]?\.?)\s*$",
    re.MULTILINE | re.IGNORECASE,
)



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
        current, merge_hits = _MERGE_ITEM_HEADING_RE.subn(r"## \1 \2\n", current)
        current, promote_hits = _PROMOTE_ITEM_HEADING_RE.subn(r"## \1\n", current)
        total = word_hits + term_hits + merge_hits + promote_hits
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
    """Convert a TableElement to markdown.

    Returns the raw markdown from sec_parser. We avoid aggressive post-processing
    (like md->df conversion) to ensure the agent sees the same verbatim rows
    and columns as the user, avoiding accidental data loss in sparse tables.
    """
    return element.table_to_markdown()


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


def _modify_to_valid_md_table(text):
    """Normalize an SEC-extracted markdown table: inject a separator, drop empty columns."""
    rows = text.split("\n")
    if len(rows) < 2:
        return text

    num_columns = rows[0].count("|")
    if num_columns < 2:
        # Not enough `|` separators to be a real table; leave as-is.
        return text

    separator = "|" + " --- |" * (num_columns - 1)
    markdown_txt = "\n".join([rows[0], separator, *rows[1:]])

    table_df = from_md_to_df(markdown_txt)
    # Coerce to string before using the `.str` accessor — empty/NaN-bearing
    # columns can otherwise raise AttributeError.
    table_df = table_df.astype(str)
    table_df = table_df.loc[:, ~table_df.apply(lambda col: col.str.strip().eq("")).all()]
    return table_df.to_markdown(index=False)
