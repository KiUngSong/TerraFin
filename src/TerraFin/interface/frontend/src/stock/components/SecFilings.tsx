import React from 'react';
import { publishAgentViewContext, clearAgentViewContextSource } from '../../agent/viewContext';
import type { FilingRow, TocEntry } from '../useStockData';
import { useFilingDocument, useFilings } from '../useStockData';
import FilingMarkdown from './FilingMarkdown';

interface Props {
  ticker: string;
  // Fired when the ticker has no SEC registration (CIK lookup 404s). The parent
  // uses this to hide the whole card — non-US tickers like KOSPI / TSE / HKEX
  // issuers don't file with SEC, and an empty card is just noise.
  onUnavailable?: () => void;
}

// Maximum chars of section body we publish to the agent side-panel.
// Balances "agent can answer questions about this section" against context
// size. Larger sections get truncated with an explicit marker.
const AGENT_EXCERPT_CHAR_LIMIT = 4000;

const PART_HEADING_RE = /^PART\s/i;

interface FilingGroup {
  part: TocEntry | null; // null only for headings that precede any Part (rare)
  items: TocEntry[];
}

// Render every Item the TOC returns — user↔agent parity trumps UI
// tidiness. Empty-placeholder Items (e.g. the literal "Item 6.
// Reserved" left in 10-Ks after the SEC removed it) render with a
// 0-char body; they're unobtrusive when collapsed and stopping the
// agent from citing a section the user can't see is worse than a
// small visual noise bump.
function groupTocByPart(toc: TocEntry[]): FilingGroup[] {
  const groups: FilingGroup[] = [];
  let current: FilingGroup = { part: null, items: [] };
  for (const entry of toc) {
    if (PART_HEADING_RE.test(entry.text)) {
      if (current.part || current.items.length > 0) groups.push(current);
      current = { part: entry, items: [] };
    } else {
      current.items.push(entry);
    }
  }
  if (current.part || current.items.length > 0) groups.push(current);
  return groups;
}

function groupKey(group: FilingGroup): string {
  return group.part?.slug ?? '_orphan_';
}

function sliceSection(markdown: string, entry: TocEntry, next: TocEntry | undefined): string {
  const lines = markdown.split('\n');
  const endLine = next ? next.lineIndex : lines.length;
  // Skip the heading line itself so the body doesn't repeat it.
  return lines.slice(entry.lineIndex + 1, endLine).join('\n').trim();
}

function excerptForAgent(body: string): string {
  if (body.length <= AGENT_EXCERPT_CHAR_LIMIT) return body;
  return body.slice(0, AGENT_EXCERPT_CHAR_LIMIT) + '\n\n…[excerpt truncated]';
}

const SecFilings: React.FC<Props> = ({ ticker, onUnavailable }) => {
  const { data: filingsList, loading: listLoading, error: listError } = useFilings(ticker);

  // Signal the parent once the ticker is confirmed not to be an SEC filer.
  React.useEffect(() => {
    if (listError === '404') onUnavailable?.();
  }, [listError, onUnavailable]);
  const [selectedForm, setSelectedForm] = React.useState<string | null>(null);

  // Auto-pick the best form when the list first arrives: prefer 10-K, then 10-Q,
  // then whatever comes first.
  React.useEffect(() => {
    if (!filingsList || filingsList.forms.length === 0) {
      setSelectedForm(null);
      return;
    }
    const preferred = ['10-K', '10-Q'].find((f) => filingsList.forms.includes(f));
    setSelectedForm(preferred || filingsList.forms[0]);
  }, [filingsList]);

  const filteredFilings = React.useMemo<FilingRow[]>(() => {
    if (!filingsList || !selectedForm) return [];
    return filingsList.filings.filter((f) => f.form === selectedForm);
  }, [filingsList, selectedForm]);

  const [selectedAccession, setSelectedAccession] = React.useState<string | null>(null);
  React.useEffect(() => {
    // On form change, collapse the reader until the user picks a filing.
    setSelectedAccession(null);
  }, [selectedForm, ticker]);

  const selectedFiling = React.useMemo<FilingRow | null>(
    () => filteredFilings.find((f) => f.accession === selectedAccession) ?? null,
    [filteredFilings, selectedAccession],
  );

  const { data: filingDoc, loading: docLoading, error: docError } = useFilingDocument(
    ticker,
    selectedFiling?.accession ?? null,
    selectedFiling?.primaryDocument ?? null,
    selectedFiling?.form ?? '10-Q',
    Boolean(selectedFiling),
  );

  // Two-level navigation: outer Parts (Part I / Part II / ...), each holding
  // its Items. Parts are the structural halves of a 10-K / 10-Q; Items are
  // the actual content sections.
  const groups = React.useMemo(
    () => (filingDoc ? groupTocByPart(filingDoc.toc) : []),
    [filingDoc],
  );

  // Default-open state: all Parts expanded so users can scan, plus the first
  // Item of the first Part so the reader isn't empty on open.
  const [openParts, setOpenParts] = React.useState<Set<string>>(new Set());
  const [openItems, setOpenItems] = React.useState<Set<string>>(new Set());
  React.useEffect(() => {
    if (groups.length === 0) {
      setOpenParts(new Set());
      setOpenItems(new Set());
      return;
    }
    setOpenParts(new Set(groups.map(groupKey)));
    const first = groups[0].items[0];
    setOpenItems(first ? new Set([first.slug]) : new Set());
  }, [groups]);

  const togglePart = (key: string) => {
    setOpenParts((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };
  const toggleItem = (slug: string) => {
    setOpenItems((prev) => {
      const next = new Set(prev);
      if (next.has(slug)) next.delete(slug);
      else next.add(slug);
      return next;
    });
  };

  // Publish agent view context: the currently-focused Item (Parts have no
  // body themselves, so we track Item focus only). Picks the first open Item
  // in document order — keeps the agent's context small even with multiple
  // expanded.
  const visibleItems = React.useMemo(() => groups.flatMap((g) => g.items), [groups]);
  const focusedSlug = openItems.size > 0
    ? visibleItems.find((e) => openItems.has(e.slug))?.slug
    : undefined;

  React.useEffect(() => {
    if (!selectedFiling || !filingDoc || !focusedSlug) {
      return;
    }
    const entry = visibleItems.find((e) => e.slug === focusedSlug);
    if (!entry) return;
    // Use the next *raw* TOC entry (not the next visible one) as the slice
    // upper bound so we stop at the exact next heading in the markdown.
    const rawIdx = filingDoc.toc.indexOf(entry);
    const nextEntry = filingDoc.toc[rawIdx + 1];
    const body = sliceSection(filingDoc.markdown, entry, nextEntry);

    void publishAgentViewContext({
      source: 'sec-filings',
      scope: 'panel',
      route: window.location.pathname,
      pageType: 'stock',
      title: `${ticker} ${selectedFiling.form} — ${entry.text}`,
      summary: `Viewing ${selectedFiling.form} (filed ${selectedFiling.filingDate}), section "${entry.text}".`,
      selection: {
        ticker,
        // Matches the `form` parameter name on sec_filing_section so the agent
        // can plug this straight back in without a rename.
        form: selectedFiling.form,
        accession: selectedFiling.accession,
        // Required to call sec_filing_section for a fuller body when the
        // 4 KB excerpt below isn't enough (Item 1. Business in a large 10-K
        // can be 30-50 KB).
        primaryDocument: selectedFiling.primaryDocument,
        filingDate: selectedFiling.filingDate,
        reportDate: selectedFiling.reportDate,
        sectionSlug: entry.slug,
        sectionTitle: entry.text,
        sectionExcerpt: excerptForAgent(body),
        documentUrl: filingDoc.documentUrl,
        indexUrl: filingDoc.indexUrl,
      },
      entities: [
        { kind: 'ticker', id: ticker, label: ticker },
        { kind: 'sec-filing', id: selectedFiling.accession, label: `${selectedFiling.form} ${selectedFiling.filingDate}` },
      ],
      metadata: { source: 'sec-filings' },
    });
    return () => {
      void clearAgentViewContextSource('sec-filings');
    };
  }, [filingDoc, focusedSlug, selectedFiling, ticker, visibleItems]);

  return (
    <div style={rootStyle}>
      {listError === '404' ? (
        // Parent will unmount us via onUnavailable. Render nothing in the
        // meantime to avoid an error flash.
        null
      ) : listLoading && !filingsList ? (
        <div style={dimStyle}>Loading filings…</div>
      ) : listError ? (
        <div style={errorStyle}>Could not load filings: {listError}</div>
      ) : !filingsList || filingsList.filings.length === 0 ? (
        <div style={dimStyle}>No SEC filings found for {ticker}.</div>
      ) : (
        <>
          <div style={formRowStyle}>
            <label htmlFor="filings-form" style={formLabelStyle}>Form</label>
            <select
              id="filings-form"
              value={selectedForm ?? ''}
              onChange={(e) => setSelectedForm(e.target.value || null)}
              style={selectStyle}
            >
              {filingsList.forms.map((f) => (<option key={f} value={f}>{f}</option>))}
            </select>
            <span style={dimStyle}>{filteredFilings.length} filing{filteredFilings.length === 1 ? '' : 's'}</span>
          </div>

          <div style={filingListStyle}>
            {filteredFilings.map((row) => {
              const isSelected = row.accession === selectedAccession;
              return (
                <div
                  key={row.accession}
                  style={filingRowStyle(isSelected)}
                  onClick={() => setSelectedAccession(isSelected ? null : row.accession)}
                  role="button"
                  tabIndex={0}
                  onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') setSelectedAccession(isSelected ? null : row.accession); }}
                >
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 13, fontWeight: 700, color: '#0f172a' }}>{row.form}</div>
                    <div style={{ fontSize: 12, color: '#64748b' }}>
                      Filed {row.filingDate}{row.reportDate ? ` · Period ${row.reportDate}` : ''}
                    </div>
                  </div>
                  <a
                    href={row.documentUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    onClick={(e) => e.stopPropagation()}
                    style={edgarLinkStyle}
                  >View on EDGAR ↗</a>
                </div>
              );
            })}
          </div>

          {selectedFiling ? (
            <div style={readerWrapStyle}>
              <div style={readerHeaderStyle}>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 14, fontWeight: 800, color: '#0f172a' }}>
                    {selectedFiling.form} · Filed {selectedFiling.filingDate}
                  </div>
                  {selectedFiling.primaryDocDescription ? (
                    <div style={{ fontSize: 12, color: '#64748b' }}>{selectedFiling.primaryDocDescription}</div>
                  ) : null}
                </div>
                {filingDoc ? (
                  <a href={filingDoc.documentUrl} target="_blank" rel="noopener noreferrer" style={edgarPillStyle}>
                    View source on EDGAR ↗
                  </a>
                ) : null}
              </div>

              {docLoading ? (
                <div style={dimStyle}>Loading filing…</div>
              ) : docError ? (
                docError === '422' ? (
                  <div style={unsupportedStyle}>
                    <div style={{ fontSize: 13, color: '#1e293b', marginBottom: 6 }}>
                      In-app reader doesn&rsquo;t support <strong>{selectedFiling.form}</strong> filings yet.
                    </div>
                    <a href={selectedFiling.documentUrl} target="_blank" rel="noopener noreferrer" style={edgarPillStyle}>
                      Open on EDGAR ↗
                    </a>
                  </div>
                ) : (
                  <div style={errorStyle}>Could not load filing: {docError}</div>
                )
              ) : filingDoc ? (
                groups.length === 0 ? (
                  <div style={dimStyle}>Filing has no sections to navigate. Open on EDGAR for the raw document.</div>
                ) : (
                  <div style={accordionStyle}>
                    {groups.map((group) => {
                      const key = groupKey(group);
                      const partOpen = openParts.has(key);
                      const totalChars = group.items.reduce((acc, it) => acc + it.charCount, 0);
                      return (
                        <div key={key} style={partCardStyle}>
                          <button
                            type="button"
                            onClick={() => togglePart(key)}
                            aria-expanded={partOpen}
                            style={partHeaderStyle(partOpen)}
                          >
                            <span style={headerLeftStyle(10)}>
                              <span style={chevronStyle(partOpen)}>▸</span>
                              <span style={headerTitleStyle(14, 800, '#0f172a')}>
                                {group.part?.text ?? 'Sections'}
                              </span>
                            </span>
                            <span style={headerBadgeStyle}>
                              {group.items.length} item{group.items.length === 1 ? '' : 's'} · {totalChars.toLocaleString()} chars
                            </span>
                          </button>
                          {partOpen ? (
                            <div style={itemsWrapStyle}>
                              {group.items.map((entry) => {
                                const rawIdx = filingDoc.toc.indexOf(entry);
                                const next = filingDoc.toc[rawIdx + 1];
                                const body = sliceSection(filingDoc.markdown, entry, next);
                                const itemOpen = openItems.has(entry.slug);
                                return (
                                  <div key={entry.slug} style={itemCardStyle}>
                                    <button
                                      type="button"
                                      onClick={() => toggleItem(entry.slug)}
                                      aria-expanded={itemOpen}
                                      style={itemHeaderStyle(itemOpen)}
                                    >
                                      <span style={headerLeftStyle(8)}>
                                        <span style={chevronStyle(itemOpen)}>▸</span>
                                        <span style={headerTitleStyle(13, 700, '#1e293b')}>
                                          {entry.text}
                                        </span>
                                      </span>
                                      <span style={headerBadgeStyle}>
                                        {entry.charCount.toLocaleString()} chars
                                      </span>
                                    </button>
                                    {itemOpen ? (
                                      <div style={sectionBodyStyle}>
                                        <FilingMarkdown markdown={body} />
                                      </div>
                                    ) : null}
                                  </div>
                                );
                              })}
                            </div>
                          ) : null}
                        </div>
                      );
                    })}
                  </div>
                )
              ) : null}
            </div>
          ) : (
            <div style={pickerHintStyle}>Select a filing above to read it with a collapsible section-by-section view.</div>
          )}
        </>
      )}
    </div>
  );
};

// ── styles ─────────────────────────────────────────────────────────────────

const rootStyle: React.CSSProperties = { display: 'flex', flexDirection: 'column', gap: 12, minWidth: 0 };
const dimStyle: React.CSSProperties = { fontSize: 12, color: '#64748b' };
const errorStyle: React.CSSProperties = { fontSize: 12, color: '#b91c1c', padding: 8, background: '#fef2f2', borderRadius: 6 };
const formRowStyle: React.CSSProperties = { display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' };
const formLabelStyle: React.CSSProperties = { fontSize: 11, fontWeight: 700, color: '#475569', textTransform: 'uppercase', letterSpacing: 0.5 };
const selectStyle: React.CSSProperties = {
  height: 32, borderRadius: 6, border: '1px solid #cbd5e1', background: '#fff',
  padding: '0 10px', fontSize: 13, color: '#0f172a', outline: 'none',
};
const filingListStyle: React.CSSProperties = { display: 'flex', flexDirection: 'column', gap: 6, maxHeight: 220, overflowY: 'auto' };
const filingRowStyle = (selected: boolean): React.CSSProperties => ({
  display: 'flex', alignItems: 'center', gap: 10, padding: '8px 10px',
  border: `1px solid ${selected ? '#1d4ed8' : '#e2e8f0'}`,
  borderRadius: 8, background: selected ? '#eff6ff' : '#ffffff', cursor: 'pointer',
});
const edgarLinkStyle: React.CSSProperties = { fontSize: 11, color: '#475569', textDecoration: 'none', flexShrink: 0 };
const readerWrapStyle: React.CSSProperties = {
  display: 'flex', flexDirection: 'column', gap: 10,
  borderTop: '1px solid #e2e8f0', paddingTop: 12, marginTop: 4,
};
const readerHeaderStyle: React.CSSProperties = {
  display: 'flex', alignItems: 'center', gap: 10, justifyContent: 'space-between', flexWrap: 'wrap',
};
const edgarPillStyle: React.CSSProperties = {
  padding: '6px 12px', borderRadius: 999, background: '#1d4ed8', color: '#fff',
  fontSize: 12, fontWeight: 700, textDecoration: 'none', flexShrink: 0,
};
const accordionStyle: React.CSSProperties = { display: 'flex', flexDirection: 'column', gap: 10 };
// Part — outer container, heavier visual weight because it's a structural
// division (10-K Part I = Financial Info, Part II = Other Info).
const partCardStyle: React.CSSProperties = {
  border: '1px solid #cbd5e1', borderRadius: 10, background: '#ffffff', overflow: 'hidden',
  boxShadow: '0 1px 2px rgba(15, 23, 42, 0.04)',
};
const partHeaderStyle = (open: boolean): React.CSSProperties => ({
  width: '100%', border: 'none',
  background: open ? 'linear-gradient(180deg, #f1f5f9 0%, #e2e8f0 100%)' : '#f8fafc',
  padding: '12px 14px', display: 'flex', alignItems: 'center', gap: 10,
  justifyContent: 'space-between', cursor: 'pointer', textAlign: 'left',
});
const itemsWrapStyle: React.CSSProperties = {
  display: 'flex', flexDirection: 'column', gap: 6, padding: '10px 12px 12px',
  background: '#f8fafc',
};
// Item — inner, lighter card.
const itemCardStyle: React.CSSProperties = {
  border: '1px solid #e2e8f0', borderRadius: 8, background: '#ffffff', overflow: 'hidden',
};
const itemHeaderStyle = (open: boolean): React.CSSProperties => ({
  width: '100%', border: 'none', background: open ? '#f1f5f9' : '#ffffff',
  padding: '9px 12px', display: 'flex', alignItems: 'center', gap: 10,
  justifyContent: 'space-between', cursor: 'pointer', textAlign: 'left',
});
const chevronStyle = (open: boolean): React.CSSProperties => ({
  display: 'inline-block', transition: 'transform 0.15s', transform: open ? 'rotate(90deg)' : 'rotate(0deg)',
  color: '#64748b', fontSize: 12, flexShrink: 0, width: 12,
});
// Header left-hand column (chevron + title). Takes available space and can
// shrink below its intrinsic width — the `minWidth: 0` is what lets the
// nowrap+ellipsis truncation actually kick in on narrow viewports instead of
// the weird mid-word wrap we hit with ZETA ("Bus" / chars / "iness").
const headerLeftStyle = (gap: number): React.CSSProperties => ({
  display: 'flex', alignItems: 'center', gap, minWidth: 0, flex: '1 1 auto',
});
// Title span itself — must carry `minWidth: 0` so the flex-shrink cascade
// reaches the span where `overflow: hidden` + `textOverflow: ellipsis`
// actually clip on narrow viewports.
const headerTitleStyle = (
  fontSize: number,
  fontWeight: number,
  color: string,
): React.CSSProperties => ({
  fontSize,
  fontWeight,
  color,
  minWidth: 0,
  overflow: 'hidden',
  textOverflow: 'ellipsis',
  whiteSpace: 'nowrap',
});
const headerBadgeStyle: React.CSSProperties = {
  fontSize: 11, color: '#64748b', flexShrink: 0,
};
const sectionBodyStyle: React.CSSProperties = { padding: '4px 14px 14px' };
const pickerHintStyle: React.CSSProperties = {
  fontSize: 12, color: '#64748b', padding: 12, textAlign: 'center',
  background: '#f8fafc', border: '1px dashed #e2e8f0', borderRadius: 8,
};
const unsupportedStyle: React.CSSProperties = {
  padding: 14, background: '#fffbeb', border: '1px solid #fde68a',
  borderRadius: 8, display: 'flex', alignItems: 'center', gap: 12,
  justifyContent: 'space-between', flexWrap: 'wrap',
};

export default SecFilings;
