import pytest

from TerraFin.data.providers.corporate.filings.sec_edgar import parser


_FILING_HTML = """<html><body>
<h2>PART I - FINANCIAL INFORMATION</h2>
<h3>Item 1. Financial Statements</h3>
<p>Revenue grew 10% year over year.</p>
<img src="charts/revenue.jpg" alt="Revenue chart" />
<img src="data:image/png;base64,AAAAAAAA" alt="Inline logo" />
<img src="logo.png" alt="  Leading\nand trailing\twhitespace  " />
<h3>Item 2. MD&amp;A</h3>
<p>Management commentary.</p>
</body></html>"""


def test_parse_sec_filing_uses_hash_prefix_for_section_titles() -> None:
    md = parser.parse_sec_filing(_FILING_HTML, "10-Q")

    # sec_parser classifies "PART I" and "Item N" as TopSectionTitle → "## ".
    # Flat "#### " from the prior implementation should be gone.
    assert "## PART I - FINANCIAL INFORMATION" in md
    assert "## Item 1. Financial Statements" in md
    assert "#### " not in md


def test_parse_filing_maps_title_element_to_h3(monkeypatch) -> None:
    """Direct branch-coverage test for the TitleElement → '### ' path.

    Real SEC filings that use explicit `<strong>`-style sub-titles can yield
    TitleElements alongside TopSectionTitles — mock the parser to guarantee
    we see both branches.
    """
    from unittest.mock import MagicMock

    from sec_parser.semantic_elements import TitleElement, TopSectionTitle

    top = MagicMock(spec=TopSectionTitle)
    top.text = "Top"
    sub = MagicMock(spec=TitleElement)
    sub.text = "Sub"

    class _FakeParser:
        def parse(self, _html):
            return [top, sub]

    monkeypatch.setattr(parser.sp, "Edgar10QParser", _FakeParser)

    md = parser._parse_filing("<html></html>", include_images=False)

    assert "## Top" in md
    assert "### Sub" in md


def test_parse_sec_filing_omits_images_by_default() -> None:
    md = parser.parse_sec_filing(_FILING_HTML, "10-Q")
    assert "![" not in md
    assert "<inline-image" not in md


def test_parse_sec_filing_includes_images_when_requested() -> None:
    md = parser.parse_sec_filing(_FILING_HTML, "10-Q", include_images=True)

    assert "![Revenue chart](charts/revenue.jpg)" in md
    # Data URI is replaced with a placeholder — no raw base64 payload.
    assert "AAAAAAAA" not in md
    assert "![Inline logo](<inline-image:image/png>)" in md
    # Alt text whitespace is collapsed.
    assert "![Leading and trailing whitespace](logo.png)" in md


def test_image_to_md_sanitizes_long_alt() -> None:
    import sec_parser as sp
    from sec_parser.semantic_elements import ImageElement

    long_alt = "x" * 500
    html = f'<html><body><h2>S</h2><img src="a.png" alt="{long_alt}" /></body></html>'
    elements = sp.Edgar10QParser().parse(html)
    images = [e for e in elements if isinstance(e, ImageElement)]
    assert images, "sec_parser should emit an ImageElement"

    md = parser._image_to_md(images[0])
    # Truncated to _ALT_MAX with an ellipsis, leaving room for ]( syntax.
    assert md.startswith("![xxx")
    assert md.endswith("\u2026](a.png)")
    assert len(md) < 500


def test_parse_sec_filing_raises_for_unsupported_form() -> None:
    with pytest.raises(ValueError, match="not supported"):
        parser.parse_sec_filing(_FILING_HTML, "DEF 14A")


def test_parse_sec_filing_accepts_verbose_form_descriptors() -> None:
    # SEC's primaryDocDescription sometimes comes as "FORM 10-Q" or
    # "10-K (Annual Report)". Loose matching preserves the caller contract.
    md_a = parser.parse_sec_filing(_FILING_HTML, "FORM 10-Q")
    md_b = parser.parse_sec_filing(_FILING_HTML, "10-K (Annual Report)")
    md_c = parser.parse_sec_filing(_FILING_HTML, "10-Q/A")
    assert "PART I" in md_a
    assert "PART I" in md_b
    assert "PART I" in md_c


def test_parse_sec_filing_handles_none_filing_form() -> None:
    with pytest.raises(ValueError, match="not supported"):
        parser.parse_sec_filing(_FILING_HTML, None)


_SAMPLE_MD = (
    "## PART I - FINANCIAL INFORMATION\n"
    "\n"
    "### Item 1. Financial Statements\n"
    "\n"
    "Some prose that mentions #tokens but is not a heading.\n"
    "\n"
    "### Item 2. MD&A\n"
    "\n"
    "## PART II - OTHER INFORMATION\n"
)


def test_build_toc_default_keeps_top_level_only_for_compact_agent_context() -> None:
    """Compact default: agents get the Part/Item scaffold, not every sub-title."""
    toc = parser.build_toc(_SAMPLE_MD)

    assert [(e["level"], e["text"]) for e in toc] == [
        (2, "PART I - FINANCIAL INFORMATION"),
        (2, "PART II - OTHER INFORMATION"),
    ]


def test_build_toc_max_level_none_returns_full_hierarchy() -> None:
    toc = parser.build_toc(_SAMPLE_MD, max_level=None)

    assert [(e["level"], e["text"]) for e in toc] == [
        (2, "PART I - FINANCIAL INFORMATION"),
        (3, "Item 1. Financial Statements"),
        (3, "Item 2. MD&A"),
        (2, "PART II - OTHER INFORMATION"),
    ]
    # Common entry shape for every item.
    for entry in toc:
        assert set(entry) == {"level", "text", "line_index", "slug", "char_count"}
    assert toc[0]["slug"] == "part-i-financial-information"


def test_build_toc_char_count_aggregates_filtered_subsections() -> None:
    """When subsections are filtered out, the parent section's char_count expands
    to cover every filtered-out heading line plus its body."""
    toc_full = parser.build_toc(_SAMPLE_MD, max_level=None)
    toc_compact = parser.build_toc(_SAMPLE_MD, max_level=2)

    # PART I (compact) must span strictly more chars than PART I (full): full
    # stops at the next ### heading; compact stops at the next ## heading.
    assert toc_compact[0]["text"] == "PART I - FINANCIAL INFORMATION"
    assert toc_compact[0]["char_count"] > toc_full[0]["char_count"]

    # Every body span should be non-negative and no larger than the document itself.
    total_chars = sum(len(line) + 1 for line in _SAMPLE_MD.splitlines())
    for entry in toc_compact + toc_full:
        assert 0 <= entry["char_count"] <= total_chars


def test_build_toc_on_empty_or_heading_less_input() -> None:
    assert parser.build_toc("") == []
    assert parser.build_toc("No headings here.\nJust prose.") == []


def test_heal_broken_titles_splices_mid_word_split() -> None:
    """sec_parser occasionally splits a heading mid-word (e.g. ZETA's 10-K
    gives `TopSectionTitle("Item 1. Bus")` + `TitleElement("iness.")`).
    The post-parse healer must merge them back."""
    raw = (
        "## Item 1. Bus\n"
        "\n"
        "### iness.\n"
        "\n"
        "### Overview\n"
        "\n"
        "Body prose.\n"
    )
    healed = parser._heal_broken_titles(raw)

    assert "## Item 1. Business." in healed
    assert "### iness." not in healed
    # Overview and body prose should survive unchanged.
    assert "### Overview" in healed
    assert "Body prose." in healed


def test_heal_broken_titles_handles_multi_fragment_chain() -> None:
    """Handles chains where the word is split across 3+ fragments."""
    raw = "## Item 1. Bus\n\n### iness\n\n### .\n"
    healed = parser._heal_broken_titles(raw)
    assert "## Item 1. Business." in healed


def test_heal_broken_titles_leaves_legit_subheadings_alone() -> None:
    """A genuine lowercase subheading after a complete parent title must NOT
    be merged. Signal: parent ends with a period or other terminator."""
    raw = "## Item 2. Properties.\n\n### overview\n\nBody.\n"
    healed = parser._heal_broken_titles(raw)
    assert "## Item 2. Properties." in healed
    assert "### overview" in healed


def test_heal_broken_titles_does_not_merge_all_caps_parents() -> None:
    """All-caps section titles followed by a legitimate lowercase subheading
    are a real 10-K pattern (e.g. `RISKS` + `### related to operations`).
    The old regex merged them into `RISKSrelated`; the tightened regex
    requires the parent-line tail to be title-case (one upper + two lower)."""
    raw = "## RISKS\n\n### related to operations\n\nBody.\n"
    healed = parser._heal_broken_titles(raw)
    assert "## RISKS" in healed
    assert "RISKSrelated" not in healed
    assert "### related to operations" in healed


def test_heal_broken_titles_does_not_merge_possessive_parent() -> None:
    """Possessive nouns like `Company's` look mid-wordish to a naive regex
    because they end in a letter, but the following lowercase-led line is
    always a legitimate sub-heading."""
    raw = "## Item 1. Company's\n\n### own operations\n\nBody.\n"
    healed = parser._heal_broken_titles(raw)
    assert "## Item 1. Company's" in healed
    assert "Company'sown" not in healed
    assert "### own operations" in healed


def test_heal_broken_titles_does_not_merge_complete_short_parent() -> None:
    """A four-character complete word like `Note` must not glue onto a
    following lowercase sub-heading."""
    raw = "## Note\n\n### overview of disclosures\n\nBody.\n"
    healed = parser._heal_broken_titles(raw)
    assert "## Note" in healed
    assert "Noteoverview" not in healed
    assert "### overview of disclosures" in healed


def test_build_toc_ignores_inline_hashes() -> None:
    md = "This sentence has a ## middle-of-line token.\n## Real Heading"
    toc = parser.build_toc(md)
    assert len(toc) == 1
    assert toc[0]["text"] == "Real Heading"
    assert toc[0]["line_index"] == 1


def test_looks_like_section_heading_matches_part_and_item_patterns() -> None:
    """Core regex that decides whether a sec_parser text blob should be
    promoted to a ## heading. Matches the canonical Part/Item prefixes
    (case-insensitive, with or without period/dash).

    No length cap: a genuine Item 7 MD&A heading can be 100+ chars, and
    even when sec_parser fuses the heading with its paragraph into one
    long blob we still want promotion — `_split_heading_and_body` in
    `_emit_heading` splits at the first newline so the heading line
    lands cleanly in the TOC."""
    assert parser._looks_like_section_heading("Item 7. Management's Discussion") is True
    assert parser._looks_like_section_heading("ITEM 7A. Quantitative and Qualitative") is True
    assert parser._looks_like_section_heading("Part I") is True
    assert parser._looks_like_section_heading("PART II") is True
    assert parser._looks_like_section_heading("Item 8") is True  # no period
    # Run-on (heading fused with body) still matches — caller splits.
    run_on = "Item 7. MD&A\nOverview\nNet income was ..."
    assert parser._looks_like_section_heading(run_on) is True
    # Rejects non-heading text.
    assert parser._looks_like_section_heading("The Company sells products") is False
    assert parser._looks_like_section_heading("") is False


def test_slugify_caps_output_at_80_chars() -> None:
    """Without this cap, a sec_parser-misclassified 400-char boilerplate
    paragraph becomes a 400-char slug that floods the TOC. Cap at 80 chars
    at a word boundary."""
    long_title = (
        "Indicates a management contract or compensatory plan. The certifications "
        "attached as Exhibit 32.1 and Exhibit 32.2 that accompany this Annual Report"
    )
    slug = parser._slugify(long_title)
    assert len(slug) <= 80
    # Must end at a word boundary (no trailing hyphen / partial word).
    assert not slug.endswith("-")
    # Stays meaningful-looking.
    assert slug.startswith("indicates-a-management-contract")


def test_slugify_preserves_short_slugs_unchanged() -> None:
    assert parser._slugify("Item 7. MD&A") == "item-7-mda"
    assert parser._slugify("Part II") == "part-ii"


def test_emit_heading_splits_run_on_item_paragraph_into_heading_plus_body() -> None:
    """sec_parser's Edgar10QParser routinely fuses a 10-K Item heading
    with the paragraph that follows it into a single TextElement. Before
    this split, Item 7 / Item 8 never appeared in the TOC for 10-Ks
    because the fused text was too long to recognize as a heading —
    ZETA's 10-K reproduced this.

    The fix: when a text blob starts with an `Item N.` / `Part I` marker
    and contains a newline, treat the first line as the heading and
    emit the rest as body. The length of the heading line itself no
    longer matters; a 91-char `Item 7. Management's Discussion and
    Analysis of Financial Condition and Results of Operations` is a
    legitimate heading, not boilerplate."""
    run_on = (
        "Item 7. Management's Discussion and Analysis of Financial Condition "
        "and Results of Operations\n"
        "Overview\n"
        "Net income was $X million for the year."
    )
    rendered = parser._emit_heading(run_on, default_level=3)

    # Heading promoted to ##, body preserved as following lines.
    assert rendered.startswith("## Item 7. Management's Discussion")
    assert "Overview" in rendered
    assert "Net income was $X million" in rendered


def test_build_toc_keeps_long_real_headings() -> None:
    """No length filter in `build_toc` — a genuine `Item 5.` heading is
    often 100+ chars in a 10-K (`Item 5. Market for Registrant's Common
    Equity, Related Stockholder Matters and Issuer Purchases of Equity
    Securities`) and must still appear in the TOC."""
    long_real = (
        "Item 5. Market for Registrant's Common Equity, Related Stockholder "
        "Matters and Issuer Purchases of Equity Securities"
    )
    md = f"## Real Part II\n### {long_real}\nBody.\n### Item 7. MD&A\nMD&A body.\n"
    toc = parser.build_toc(md, max_level=3)
    texts = [entry["text"] for entry in toc]
    assert long_real in texts
    assert "Item 7. MD&A" in texts


def test_emit_heading_splits_multi_item_blob_so_every_item_lands_in_toc() -> None:
    """sec_parser routinely fuses several 10-K Item headings and their
    bodies into one big TextElement. The ZETA 10-K failure mode: Item 7
    MD&A, Item 7A Market Risk, and Item 8 Financial Statements all live
    inside a single blob, so only the first one used to get promoted.
    After the multi-chunk split they all surface in the TOC."""
    blob = (
        "Item 7. Management's Discussion and Analysis of Financial Condition\n"
        "Overview of results.\n"
        "Revenue was $500M.\n"
        "Item 7A. Quantitative and Qualitative Disclosures About Market Risk\n"
        "Interest rate sensitivity analysis.\n"
        "Item 8. Financial Statements and Supplementary Data\n"
        "Net income was $50M for the year ended 2025.\n"
    )
    rendered = parser._emit_heading(blob, default_level=3)

    # All three Item headings promoted to ##.
    assert "## Item 7. Management's Discussion" in rendered
    assert "## Item 7A. Quantitative and Qualitative" in rendered
    assert "## Item 8. Financial Statements" in rendered
    # And their bodies are still present under each heading.
    assert "Revenue was $500M" in rendered
    assert "Interest rate sensitivity" in rendered
    assert "Net income was $50M" in rendered


def test_emit_heading_promotes_embedded_item_after_preamble() -> None:
    """If a text blob starts with non-heading prose (like a 'Table of
    Contents' breadcrumb) and an Item heading is embedded further down,
    the embedded heading must still promote — earlier regex anchored
    at start-of-string and would miss this case, leaving the whole
    blob as unclassified body prose."""
    preamble_blob = (
        "Table of Contents\n"
        "Item 7. Management's Discussion\n"
        "Overview text."
    )
    rendered = parser._emit_heading(preamble_blob, default_level=3)

    # The Item 7 heading is promoted despite the preamble line.
    assert "## Item 7. Management's Discussion" in rendered
    # Preamble stays, emitted above the heading.
    assert "Table of Contents" in rendered
    # Body stays under the heading.
    assert "Overview text" in rendered


def test_build_toc_dedupes_colliding_slugs_with_numeric_suffix() -> None:
    """Two sections whose titles slugify to the same string would
    otherwise alias to a single TOC entry — first-match-wins in
    `sec_filing_section` makes the second section unreachable.
    Deduplicate with `-2`, `-3`, … suffixes so every entry has a
    unique slug."""
    # Same heading text appearing twice is the simplest collision case;
    # it happens in real 10-Ks where, e.g. Part I and Part IV both have
    # an "Exhibits" subsection.
    md = "## Part I\n### Exhibits\nA.\n## Part IV\n### Exhibits\nB.\n"
    toc = parser.build_toc(md, max_level=3)
    slugs = [entry["slug"] for entry in toc]
    # All slugs distinct.
    assert len(set(slugs)) == len(slugs)
    # One `exhibits`, one `exhibits-2`.
    assert "exhibits" in slugs
    assert "exhibits-2" in slugs


def test_build_toc_dedup_respects_existing_numeric_suffix_slug() -> None:
    """If the source already has a heading whose own slug is
    `exhibits-2` (e.g. literally `## Exhibits 2`) AND two `Exhibits`
    headings collide, the collision resolver must increment past the
    already-used `-2` rather than re-emitting it. A plain per-base-slug
    counter would produce a duplicate; the used-slug set approach
    avoids that."""
    md = "## Exhibits\nA.\n## Exhibits 2\nB.\n## Exhibits\nC.\n## Exhibits\nD.\n"
    toc = parser.build_toc(md, max_level=3)
    slugs = [entry["slug"] for entry in toc]
    # Every slug must be unique.
    assert len(set(slugs)) == len(slugs)
    # Sensible ordering: first `Exhibits` wins the bare slug, then the
    # legitimately-named `Exhibits 2` keeps its own slug, and the later
    # duplicates skip past the collision.
    assert slugs[0] == "exhibits"
    assert slugs[1] == "exhibits-2"
    # Subsequent collisions use suffixes that don't collide with slug[1].
    assert slugs[2] != slugs[1]
    assert slugs[3] != slugs[1] and slugs[3] != slugs[2]


def test_build_toc_dedupes_colliding_truncated_slugs() -> None:
    """Collision case that specifically exercises the 80-char cap: two
    long titles that share their first 80 chars but diverge after that.
    Before dedup, both truncate to the same slug."""
    # Identical prefix (first 80 chars of slug identical), different tails.
    prefix = "Item 1. Business overview covering segments products go to market strategy and"
    title_a = prefix + " North America revenue"
    title_b = prefix + " Europe operations headcount"
    md = f"## Part I\n### {title_a}\nA.\n### {title_b}\nB.\n"
    toc = parser.build_toc(md, max_level=3)
    slugs = [entry["slug"] for entry in toc]
    assert len(set(slugs)) == len(slugs)  # no collision survives


def test_build_toc_strips_trailing_carriage_return_from_heading_text() -> None:
    """EDGAR HTML often has CRLF line endings. `splitlines()` preserves
    the `\\r` inside the captured group, which would leak into the slug
    as a `-r` suffix and break lookup."""
    md = "## Part I\r\n### Item 1. Business\r\nBody.\r\n"
    toc = parser.build_toc(md, max_level=3)
    slugs = [entry["slug"] for entry in toc]
    assert "item-1-business" in slugs
    # None of the slugs end with a garbage `-r`.
    assert not any(s.endswith("-r") for s in slugs)


def test_promote_item_heading_regex_does_not_overmatch_body_text() -> None:
    """The promote/merge regexes used to accept `\\w+` after `ITEM`,
    which matched incidental body text like `### item foo` (a real H3
    sub-section). Tightening to `\\d+[A-Z]?` prevents spurious
    level-2 promotions.

    The critical property here is that an `### item foo bar` heading
    (non-numeric Item-like word) stays at level 3 in the healed
    markdown — `build_toc(max_level=2)` will correctly ignore it."""
    md = "## Part II\n### item foo bar\nRegular subsection.\n"
    healed = parser._heal_broken_titles(md)
    # It's still a level-3 heading; `build_toc(max_level=2)` excludes it
    # instead of surfacing a bogus level-2 entry.
    toc = parser.build_toc(healed, max_level=2)
    slugs = [e["slug"] for e in toc]
    assert "item-foo-bar" not in slugs
    assert "part-ii" in slugs


def test_table_to_md_returns_sec_parser_markdown_verbatim() -> None:
    """We intentionally don't post-process sec_parser's table markdown so the
    agent sees the same rows and columns the user renders. Strip/normalize
    would risk silent data loss on sparse tables, and user↔agent data
    surface must stay identical."""
    class _FakeTable:
        def table_to_markdown(self) -> str:
            return "| Header | Other |\n| cell | value |"

    result = parser._table_to_md(_FakeTable())

    assert result == "| Header | Other |\n| cell | value |"
