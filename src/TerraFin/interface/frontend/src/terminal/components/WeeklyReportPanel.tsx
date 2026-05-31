import React, { useEffect, useLayoutEffect, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';

interface ReportSummary {
  asOf: string;
  generatedAt: string;
  isSample: boolean;
  universe: string[];
  tickers: number;
}

interface ReportDetail extends ReportSummary {
  markdown: string;
}

interface Props {
  onClose: () => void;
}

const API = '/terminal/api/reports/weekly';

const MOBILE_BREAKPOINT = 640;

const WeeklyReportPanel: React.FC<Props> = ({ onClose }) => {
  const [summaries, setSummaries] = useState<ReportSummary[]>([]);
  const [selected, setSelected] = useState<ReportDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [isMobile, setIsMobile] = useState(
    typeof window !== 'undefined' && window.innerWidth < MOBILE_BREAKPOINT,
  );
  // Anchor the mobile sheet just below the actual header bottom — at narrow
  // widths the function bar stacks brand/nav/search vertically and grows past
  // its default height. Hardcoding a top would cover the search bar.
  const [headerBottom, setHeaderBottom] = useState(56);
  const activeChipRef = useRef<HTMLLIElement | null>(null);

  useEffect(() => {
    const onResize = () => setIsMobile(window.innerWidth < MOBILE_BREAKPOINT);
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, []);

  useLayoutEffect(() => {
    const measure = () => {
      const header = document.querySelector('.tf-funcbar') as HTMLElement | null;
      if (header) {
        const rect = header.getBoundingClientRect();
        setHeaderBottom(Math.max(0, Math.round(rect.bottom)) + 4);
      }
    };
    measure();
    window.addEventListener('resize', measure);
    window.addEventListener('orientationchange', measure);
    return () => {
      window.removeEventListener('resize', measure);
      window.removeEventListener('orientationchange', measure);
    };
  }, []);

  // Scroll the active chip into view on mobile after a selection so it doesn't
  // sit off-screen in the horizontal scroller.
  useEffect(() => {
    if (!isMobile || !activeChipRef.current) return;
    activeChipRef.current.scrollIntoView({ block: 'nearest', inline: 'center', behavior: 'smooth' });
  }, [isMobile, selected?.asOf]);

  const fetchList = async () => {
    setLoading(true);
    try {
      const resp = await fetch(API);
      if (!resp.ok) return;
      const data = await resp.json();
      const list: ReportSummary[] = data.reports || [];
      setSummaries(list);
      if (list.length > 0) {
        await openReport(list[0].asOf);
      } else {
        setSelected(null);
      }
    } finally {
      setLoading(false);
    }
  };

  const openReport = async (asOf: string) => {
    const resp = await fetch(`${API}/${asOf}`);
    if (!resp.ok) return;
    const data: ReportDetail = await resp.json();
    setSelected(data);
  };

  useEffect(() => {
    fetchList();
  }, []);

  // Mobile sheet position depends on the measured header bottom — the one
  // dynamic value that can't live in CSS (the function bar height varies with
  // how the brand/nav/search wrap at narrow widths). dvh handles the iOS
  // Safari URL-bar collapse so the sheet doesn't run past the visible area.
  const mobilePos: React.CSSProperties | undefined = isMobile
    ? { top: headerBottom, maxHeight: `calc(100dvh - ${headerBottom + 16}px)` }
    : undefined;

  return (
    <div
      className={`tf-wreport${isMobile ? ' tf-wreport--mobile' : ''}`}
      style={mobilePos}
      role="dialog"
      aria-label="Weekly reports"
    >
      <div className="tf-wreport__header">
        <span className="tf-wreport__title">Weekly Reports</span>
        <button type="button" onClick={onClose} className="tf-wreport__close" aria-label="Close">×</button>
      </div>
      <div className={`tf-wreport__body${isMobile ? ' tf-wreport__body--mobile' : ''}`}>
        {loading ? (
          <div className="tf-wreport__status">Loading…</div>
        ) : summaries.length === 0 ? (
          <div className="tf-wreport__status">
            No reports yet. The next weekly report drops Friday at 16:30 ET.
          </div>
        ) : (
          <>
            <ul className={`tf-wreport__list${isMobile ? ' tf-wreport__list--mobile' : ''}`}>
              {summaries.map((s) => {
                const active = selected?.asOf === s.asOf;
                return (
                  <li key={s.asOf} ref={active ? activeChipRef : undefined}>
                    <button
                      type="button"
                      onClick={() => openReport(s.asOf)}
                      className={`tf-wreport__item${active ? ' tf-wreport__item--active' : ''}${isMobile ? ' tf-wreport__item--mobile' : ''}`}
                    >
                      <span className="tf-wreport__item-date">{s.asOf}</span>
                      <span className="tf-wreport__count">{s.tickers} tickers</span>
                      {s.isSample && <span className="tf-wreport__sample">SAMPLE</span>}
                    </button>
                  </li>
                );
              })}
            </ul>
            <div className="tf-wreport__content">
              {selected ? (
                <div className="tf-wreport__md">
                  <ReactMarkdown>{selected.markdown}</ReactMarkdown>
                </div>
              ) : (
                <div className="tf-wreport__status">Select a report</div>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
};

export default WeeklyReportPanel;
