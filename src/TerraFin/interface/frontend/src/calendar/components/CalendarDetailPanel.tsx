import React from "react";
import type { CalendarEvent } from "../types";

interface CalendarDetailPanelProps {
  event: CalendarEvent | null;
}

interface EpsRow {
  date?: string;
  estimate: string;
  reported: string;
  surprise: string;
}

interface EarningsData {
  estimate: string;
  reported: string;
  surprise: string;
  history?: EpsRow[];
}

interface MacroData {
  actual: string;
  actual_date?: string;
  expected: string;
  last: string;
  label?: string;
}

function parseEarningsDesc(desc: string): EarningsData | null {
  try {
    const parsed = JSON.parse(desc);
    if (parsed && typeof parsed === "object" && "estimate" in parsed) return parsed as EarningsData;
  } catch {
    // not JSON
  }
  return null;
}

function parseMacroDesc(desc: string): MacroData | null {
  try {
    const parsed = JSON.parse(desc);
    if (parsed && typeof parsed === "object" && "actual" in parsed) return parsed as MacroData;
  } catch {
    // not JSON
  }
  return null;
}

const cellBase: React.CSSProperties = {
  padding: "5px 8px",
  fontSize: 11,
  borderBottom: "1px solid #e2e8f0",
};

const SurpriseCell: React.FC<{ value: string }> = ({ value }) => {
  if (!value || value === "-") return <td style={cellBase}>-</td>;
  const num = parseFloat(value.replace(/[+%]/g, ""));
  const color = isNaN(num) ? "#334155" : num >= 0 ? "#047857" : "#b91c1c";
  return <td style={{ ...cellBase, color, fontWeight: 600, textAlign: "right" }}>{value}</td>;
};

const EarningsDetail: React.FC<{ data: EarningsData }> = ({ data }) => {
  const thStyle: React.CSSProperties = {
    ...cellBase,
    color: "#64748b",
    fontWeight: 600,
    textAlign: "left",
    fontSize: 10,
    textTransform: "uppercase",
    letterSpacing: "0.5px",
  };
  const tdRight: React.CSSProperties = { ...cellBase, textAlign: "right", fontVariantNumeric: "tabular-nums" };

  const showCurrent = data.estimate !== "-" || data.reported !== "-";
  const history = data.history ?? [];

  return (
    <div style={{ marginTop: 4 }}>
      {showCurrent && (
        <>
          <div className="tf-calendar-detail-label" style={{ marginBottom: 6 }}>Current</div>
          <table style={{ width: "100%", borderCollapse: "collapse", background: "#fff", borderRadius: 6, overflow: "hidden", border: "1px solid #e2e8f0", marginBottom: 10 }}>
            <tbody>
              {data.estimate !== "-" && (
                <tr><td style={{ ...cellBase, color: "#64748b", fontWeight: 600, width: 80 }}>Estimate</td><td style={tdRight}>{data.estimate}</td></tr>
              )}
              {data.reported !== "-" && (
                <tr><td style={{ ...cellBase, color: "#64748b", fontWeight: 600, width: 80 }}>Reported</td><td style={tdRight}>{data.reported}</td></tr>
              )}
              {data.surprise !== "-" && (
                <tr><td style={{ ...cellBase, color: "#64748b", fontWeight: 600, width: 80 }}>Surprise</td><SurpriseCell value={data.surprise} /></tr>
              )}
            </tbody>
          </table>
        </>
      )}

      {history.length > 0 && (
        <>
          <div className="tf-calendar-detail-label" style={{ marginBottom: 6 }}>Recent History</div>
          <table style={{ width: "100%", borderCollapse: "collapse", background: "#fff", borderRadius: 6, overflow: "hidden", border: "1px solid #e2e8f0" }}>
            <thead>
              <tr style={{ background: "#f8fafc" }}>
                <th style={thStyle}>Date</th>
                <th style={{ ...thStyle, textAlign: "right" }}>Est</th>
                <th style={{ ...thStyle, textAlign: "right" }}>Actual</th>
                <th style={{ ...thStyle, textAlign: "right" }}>Surp.</th>
              </tr>
            </thead>
            <tbody>
              {history.map((h, i) => (
                <tr key={i}>
                  <td style={{ ...cellBase, fontSize: 11, color: "#334155" }}>{h.date ?? "-"}</td>
                  <td style={tdRight}>{h.estimate || "-"}</td>
                  <td style={tdRight}>{h.reported || "-"}</td>
                  <SurpriseCell value={h.surprise} />
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </div>
  );
};

const MacroDetail: React.FC<{ data: MacroData }> = ({ data }) => {
  const tdLabel: React.CSSProperties = { ...cellBase, color: "#64748b", fontWeight: 600, width: 80 };
  const tdRight: React.CSSProperties = { ...cellBase, textAlign: "right", fontVariantNumeric: "tabular-nums" };

  const hasData = data.actual !== "-" || data.expected !== "-" || data.last !== "-";
  if (!hasData) return null;

  return (
    <div style={{ marginTop: 4 }}>
      <div className="tf-calendar-detail-label" style={{ marginBottom: 6 }}>
        {data.label || "Values"}
      </div>
      <table style={{ width: "100%", borderCollapse: "collapse", background: "#fff", borderRadius: 6, overflow: "hidden", border: "1px solid #e2e8f0" }}>
        <tbody>
          {data.actual !== "-" && (
            <tr>
              <td style={tdLabel}>Latest</td>
              <td style={tdRight}>
                {data.actual}
                {data.actual_date && <span style={{ color: "#94a3b8", fontSize: 10, marginLeft: 6 }}>({data.actual_date})</span>}
              </td>
            </tr>
          )}
          {data.expected !== "-" && (
            <tr><td style={tdLabel}>Expected</td><td style={tdRight}>{data.expected}</td></tr>
          )}
          {data.last !== "-" && (
            <tr><td style={tdLabel}>Previous</td><td style={tdRight}>{data.last}</td></tr>
          )}
        </tbody>
      </table>
    </div>
  );
};

const CalendarDetailPanel: React.FC<CalendarDetailPanelProps> = ({ event }) => {
  if (!event) {
    return (
      <aside className="tf-calendar-detail empty">
        Select an event to view details.
      </aside>
    );
  }

  const localDate = new Date(event.start).toLocaleString();
  const earnings =
    event.category === "earning" && event.description
      ? parseEarningsDesc(event.description)
      : null;
  const macro =
    event.category === "macro" && event.description
      ? parseMacroDesc(event.description)
      : null;

  return (
    <aside className="tf-calendar-detail">
      <div>
        <div className="tf-calendar-detail-label">Event</div>
        <div className="tf-calendar-detail-title">{event.title}</div>
      </div>

      <div className="tf-calendar-detail-grid">
        <div>
          <strong>Date/Time:</strong> {event.displayTime || localDate}
        </div>
        <div>
          <strong>Category:</strong> {event.category.charAt(0).toUpperCase() + event.category.slice(1)}
        </div>
        {event.importance ? (
          <div>
            <strong>Importance:</strong> {event.importance}
          </div>
        ) : null}
        {event.source ? (
          <div>
            <strong>Source:</strong> {event.source}
          </div>
        ) : null}
      </div>

      {earnings ? (
        <EarningsDetail data={earnings} />
      ) : macro ? (
        <MacroDetail data={macro} />
      ) : event.description ? (
        <div>
          <strong>Description:</strong> {event.description}
        </div>
      ) : null}
    </aside>
  );
};

export default CalendarDetailPanel;
