import React, { useEffect, useRef, useState } from 'react';
import WeeklyReportPanel from '../terminal/components/WeeklyReportPanel';

const SEEN_KEY = 'tf-weekly-report-seen';

const BellIcon: React.FC = () => (
  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M18 8a6 6 0 1 0-12 0c0 7-3 9-3 9h18s-3-2-3-9" />
    <path d="M13.73 21a2 2 0 0 1-3.46 0" />
  </svg>
);

// Weekly-report launcher for the FunctionBar. Polls the live
// /terminal/api/reports/weekly feed, shows an unread dot when a newer report
// exists than the one last viewed (localStorage), and opens WeeklyReportPanel.
const ReportBell: React.FC = () => {
  const [open, setOpen] = useState(false);
  const [hasUnread, setHasUnread] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cancelled = false;
    const check = async () => {
      try {
        const resp = await fetch('/terminal/api/reports/weekly');
        if (!resp.ok) return;
        const data = await resp.json();
        const latest = (data.reports || [])[0];
        if (!latest || cancelled) return;
        setHasUnread(latest.asOf !== localStorage.getItem(SEEN_KEY));
      } catch {
        // ignore
      }
    };
    check();
    const id = window.setInterval(check, 5 * 60 * 1000);
    return () => { cancelled = true; window.clearInterval(id); };
  }, []);

  useEffect(() => {
    if (!open) return;
    const handler = (e: PointerEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('pointerdown', handler);
    return () => document.removeEventListener('pointerdown', handler);
  }, [open]);

  const handleOpen = async () => {
    const next = !open;
    setOpen(next);
    if (next) {
      try {
        const resp = await fetch('/terminal/api/reports/weekly');
        const data = await resp.json();
        const latest = (data.reports || [])[0];
        if (latest) {
          localStorage.setItem(SEEN_KEY, latest.asOf);
          setHasUnread(false);
        }
      } catch {
        // ignore
      }
    }
  };

  return (
    <div ref={ref} style={{ position: 'relative' }}>
      <button
        type="button"
        className="tf-funcbar__kbutton"
        onClick={handleOpen}
        aria-label="Weekly reports"
        title="Weekly reports"
        style={{ position: 'relative' }}
      >
        <BellIcon />
        {hasUnread && (
          <span
            aria-label="New report"
            style={{
              position: 'absolute',
              top: 3,
              right: 3,
              width: 7,
              height: 7,
              borderRadius: '50%',
              background: 'var(--tf-down)',
              border: '2px solid var(--tf-bg-pane)',
            }}
          />
        )}
      </button>
      {open && <WeeklyReportPanel onClose={() => setOpen(false)} />}
    </div>
  );
};

export default ReportBell;
