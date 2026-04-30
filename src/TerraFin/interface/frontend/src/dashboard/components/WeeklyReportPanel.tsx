import React, { useEffect, useState } from 'react';
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

const API = '/dashboard/api/reports/weekly';

const WeeklyReportPanel: React.FC<Props> = ({ onClose }) => {
  const [summaries, setSummaries] = useState<ReportSummary[]>([]);
  const [selected, setSelected] = useState<ReportDetail | null>(null);
  const [loading, setLoading] = useState(true);

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

  return (
    <div style={panelStyle} role="dialog" aria-label="Weekly reports">
      <div style={headerStyle}>
        <span style={{ fontSize: 13, fontWeight: 700, color: '#0f172a' }}>Weekly Reports</span>
        <button type="button" onClick={onClose} style={closeBtnStyle}>×</button>
      </div>
      <div style={bodyStyle}>
        {loading ? (
          <div style={{ padding: 12, fontSize: 12, color: '#64748b' }}>Loading…</div>
        ) : summaries.length === 0 ? (
          <div style={{ padding: 12, fontSize: 12, color: '#64748b' }}>
            No reports yet. The next weekly report drops Friday at 16:30 ET.
          </div>
        ) : (
          <>
            <ul style={listStyle}>
              {summaries.map((s) => (
                <li key={s.asOf}>
                  <button
                    type="button"
                    onClick={() => openReport(s.asOf)}
                    style={listItemStyle(selected?.asOf === s.asOf)}
                  >
                    <span style={{ fontWeight: 600 }}>{s.asOf}</span>
                    <span style={{ fontSize: 10, color: '#94a3b8', marginLeft: 6 }}>
                      {s.tickers} tickers
                    </span>
                    {s.isSample && <span style={sampleBadgeStyle}>SAMPLE</span>}
                  </button>
                </li>
              ))}
            </ul>
            <div style={contentStyle}>
              {selected ? (
                <div style={mdStyle}>
                  <ReactMarkdown
                    components={{
                      h1: ({ children }) => <h1 style={h1Style}>{children}</h1>,
                      h2: ({ children }) => <h2 style={h2Style}>{children}</h2>,
                      blockquote: ({ children }) => <div style={bannerStyle}>{children}</div>,
                      ul: ({ children }) => <ul style={ulStyle}>{children}</ul>,
                      li: ({ children }) => <li style={liStyle}>{children}</li>,
                      strong: ({ children }) => <strong style={strongStyle}>{children}</strong>,
                      em: ({ children }) => <em style={emStyle}>{children}</em>,
                      code: ({ children }) => <code style={codeStyle}>{children}</code>,
                      p: ({ children }) => <p style={pStyle}>{children}</p>,
                    }}
                  >
                    {selected.markdown}
                  </ReactMarkdown>
                </div>
              ) : (
                <div style={{ padding: 12, fontSize: 12, color: '#64748b' }}>Select a report</div>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
};

const panelStyle: React.CSSProperties = {
  position: 'absolute',
  top: 'calc(100% + 8px)',
  right: 0,
  width: 'min(560px, 90vw)',
  maxHeight: '70vh',
  background: '#ffffff',
  border: '1px solid #cbd5e1',
  borderRadius: 12,
  boxShadow: '0 12px 32px rgba(15, 23, 42, 0.14)',
  zIndex: 60,
  display: 'flex',
  flexDirection: 'column',
  overflow: 'hidden',
};

const headerStyle: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'space-between',
  padding: '10px 14px',
  borderBottom: '1px solid #e2e8f0',
  background: '#f8fafc',
};

const bodyStyle: React.CSSProperties = {
  display: 'grid',
  gridTemplateColumns: '160px 1fr',
  flex: 1,
  minHeight: 0,
};

const listStyle: React.CSSProperties = {
  listStyle: 'none',
  margin: 0,
  padding: 6,
  borderRight: '1px solid #e2e8f0',
  overflowY: 'auto',
  background: '#fafafa',
};

const listItemStyle = (active: boolean): React.CSSProperties => ({
  width: '100%',
  textAlign: 'left',
  padding: '7px 9px',
  border: 'none',
  borderRadius: 6,
  background: active ? '#eff6ff' : 'transparent',
  fontSize: 12,
  color: '#0f172a',
  cursor: 'pointer',
  outline: 'none',
  display: 'flex',
  alignItems: 'center',
  gap: 4,
});

const sampleBadgeStyle: React.CSSProperties = {
  marginLeft: 'auto',
  fontSize: 9,
  fontWeight: 700,
  color: '#b45309',
  background: '#fef3c7',
  padding: '1px 6px',
  borderRadius: 4,
  letterSpacing: 0.4,
};

const contentStyle: React.CSSProperties = {
  overflowY: 'auto',
  padding: 12,
};

const mdStyle: React.CSSProperties = {
  fontSize: 13,
  lineHeight: 1.55,
  color: '#0f172a',
};

const h1Style: React.CSSProperties = {
  margin: '0 0 6px',
  fontSize: 16,
  fontWeight: 700,
  color: '#0f172a',
};

const h2Style: React.CSSProperties = {
  margin: '14px 0 6px',
  fontSize: 13,
  fontWeight: 700,
  color: '#1e293b',
  borderBottom: '1px solid #e2e8f0',
  paddingBottom: 4,
  textTransform: 'uppercase',
  letterSpacing: 0.4,
};

const bannerStyle: React.CSSProperties = {
  margin: '8px 0',
  padding: '8px 10px',
  background: '#fef3c7',
  border: '1px solid #fcd34d',
  borderRadius: 8,
  fontSize: 11,
  color: '#92400e',
};

const ulStyle: React.CSSProperties = {
  margin: '0 0 6px',
  paddingLeft: 18,
  listStyle: 'disc',
};

const liStyle: React.CSSProperties = {
  margin: '3px 0',
  fontSize: 12,
};

const strongStyle: React.CSSProperties = {
  fontWeight: 700,
  color: '#0f172a',
};

const emStyle: React.CSSProperties = {
  color: '#64748b',
  fontStyle: 'italic',
  fontSize: 11,
};

const codeStyle: React.CSSProperties = {
  fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
  fontSize: 11,
  background: '#f1f5f9',
  padding: '1px 5px',
  borderRadius: 4,
};

const pStyle: React.CSSProperties = {
  margin: '6px 0',
  fontSize: 12,
};

const closeBtnStyle: React.CSSProperties = {
  border: 'none',
  background: 'transparent',
  fontSize: 18,
  color: '#94a3b8',
  cursor: 'pointer',
  padding: '0 4px',
  lineHeight: 1,
};

export default WeeklyReportPanel;
