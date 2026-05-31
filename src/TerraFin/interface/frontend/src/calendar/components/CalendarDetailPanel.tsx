import React from "react";
import { CATEGORY_COLORS } from "../constants";
import type { CalendarEvent } from "../types";

interface CalendarDetailPanelProps {
  event: CalendarEvent | null;
  upcomingEvents?: CalendarEvent[];
  onSelectEvent?: (event: CalendarEvent) => void;
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
  fontSize: "var(--tf-fs-xs)",
  borderBottom: "1px solid var(--tf-border)",
};

const SurpriseCell: React.FC<{ value: string }> = ({ value }) => {
  if (!value || value === "-") return <td style={cellBase}>-</td>;
  const num = parseFloat(value.replace(/[+%]/g, ""));
  const color = isNaN(num) ? "var(--tf-text)" : num >= 0 ? "var(--tf-up)" : "var(--tf-down)";
  return <td style={{ ...cellBase, color, fontWeight: 600, textAlign: "right" }}>{value}</td>;
};

const EarningsDetail: React.FC<{ data: EarningsData }> = ({ data }) => {
  const thStyle: React.CSSProperties = {
    ...cellBase,
    color: "var(--tf-muted)",
    fontWeight: 600,
    textAlign: "left",
    fontSize: "var(--tf-fs-micro)",
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
          <table style={{ width: "100%", borderCollapse: "collapse", background: "var(--tf-bg-elevated)", borderRadius: "var(--tf-radius)", overflow: "hidden", border: "1px solid var(--tf-border)", marginBottom: 10 }}>
            <tbody>
              {data.estimate !== "-" && (
                <tr><td style={{ ...cellBase, color: "var(--tf-muted)", fontWeight: 600, width: 80 }}>Estimate</td><td style={tdRight}>{data.estimate}</td></tr>
              )}
              {data.reported !== "-" && (
                <tr><td style={{ ...cellBase, color: "var(--tf-muted)", fontWeight: 600, width: 80 }}>Reported</td><td style={tdRight}>{data.reported}</td></tr>
              )}
              {data.surprise !== "-" && (
                <tr><td style={{ ...cellBase, color: "var(--tf-muted)", fontWeight: 600, width: 80 }}>Surprise</td><SurpriseCell value={data.surprise} /></tr>
              )}
            </tbody>
          </table>
        </>
      )}

      {history.length > 0 && (
        <>
          <div className="tf-calendar-detail-label" style={{ marginBottom: 6 }}>Recent History</div>
          <table style={{ width: "100%", borderCollapse: "collapse", background: "var(--tf-bg-elevated)", borderRadius: "var(--tf-radius)", overflow: "hidden", border: "1px solid var(--tf-border)" }}>
            <thead>
              <tr style={{ background: "var(--tf-bg-elevated)" }}>
                <th style={thStyle}>Date</th>
                <th style={{ ...thStyle, textAlign: "right" }}>Est</th>
                <th style={{ ...thStyle, textAlign: "right" }}>Actual</th>
                <th style={{ ...thStyle, textAlign: "right" }}>Surp.</th>
              </tr>
            </thead>
            <tbody>
              {history.map((h, i) => (
                <tr key={i}>
                  <td style={{ ...cellBase, fontSize: "var(--tf-fs-xs)", color: "var(--tf-text)" }}>{h.date ?? "-"}</td>
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
  const tdLabel: React.CSSProperties = { ...cellBase, color: "var(--tf-muted)", fontWeight: 600, width: 80 };
  const tdRight: React.CSSProperties = { ...cellBase, textAlign: "right", fontVariantNumeric: "tabular-nums" };

  const hasData = data.actual !== "-" || data.expected !== "-" || data.last !== "-";
  if (!hasData) return null;

  return (
    <div style={{ marginTop: 4 }}>
      <div className="tf-calendar-detail-label" style={{ marginBottom: 6 }}>
        {data.label || "Values"}
      </div>
      <table style={{ width: "100%", borderCollapse: "collapse", background: "var(--tf-bg-elevated)", borderRadius: "var(--tf-radius)", overflow: "hidden", border: "1px solid var(--tf-border)" }}>
        <tbody>
          {data.actual !== "-" && (
            <tr>
              <td style={tdLabel}>Latest</td>
              <td style={tdRight}>
                {data.actual}
                {data.actual_date && <span style={{ color: "var(--tf-muted)", fontSize: "var(--tf-fs-micro)", marginLeft: 6 }}>({data.actual_date})</span>}
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

const UpcomingAgenda: React.FC<{
  events: CalendarEvent[];
  onSelectEvent?: (event: CalendarEvent) => void;
}> = ({ events, onSelectEvent }) => {
  const now = Date.now();
  const sorted = [...events].sort(
    (a, b) => new Date(a.start).getTime() - new Date(b.start).getTime(),
  );
  const future = sorted.filter((e) => new Date(e.start).getTime() >= now - 12 * 60 * 60 * 1000);
  // Prefer upcoming events; if the viewed month is entirely in the past,
  // fall back to that month's full agenda so the rail is never empty.
  const showingFuture = future.length > 0;
  const agenda = (showingFuture ? future : sorted).slice(0, 14);

  if (agenda.length === 0) {
    return (
      <aside className="tf-calendar-detail empty">
        Select an event to view details.
      </aside>
    );
  }

  return (
    <aside className="tf-calendar-detail">
      <div>
        <div className="tf-calendar-detail-label">{showingFuture ? "Upcoming" : "This month"}</div>
        <div className="tf-calendar-detail-hint">Select an event on the calendar for full details.</div>
      </div>
      <div className="tf-calendar-agenda">
        {agenda.map((e) => {
          const color = CATEGORY_COLORS[e.category];
          const day = new Date(e.start).toLocaleDateString("en-US", { month: "short", day: "2-digit" });
          const title = e.title.includes(" - ") ? e.title.split(" - ")[0] : e.title;
          return (
            <button
              key={e.id}
              type="button"
              className="tf-calendar-agenda-row"
              onClick={() => onSelectEvent?.(e)}
            >
              <span className="tf-calendar-agenda-date">{day}</span>
              <span className="tf-calendar-dot" style={{ backgroundColor: color }} />
              <span className="tf-calendar-agenda-title">{title}</span>
            </button>
          );
        })}
      </div>
    </aside>
  );
};

const CalendarDetailPanel: React.FC<CalendarDetailPanelProps> = ({ event, upcomingEvents, onSelectEvent }) => {
  if (!event) {
    return <UpcomingAgenda events={upcomingEvents ?? []} onSelectEvent={onSelectEvent} />;
  }

  const localDate = new Date(event.start).toLocaleString("en-US", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
  const localDateOnly = new Date(event.start).toLocaleDateString("en-US", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  });
  const earnings =
    event.category === "earning" && event.description
      ? parseEarningsDesc(event.description)
      : null;
  const macro =
    event.category === "macro" && event.description
      ? parseMacroDesc(event.description)
      : null;

  const earningTicker = earnings
    ? event.title.split(" - ")[0].trim()
    : null;
  const displayTitle = event.title.replace(/\s*\(The\)\s*$/, "");

  return (
    <aside className="tf-calendar-detail">
      <div>
        <div className="tf-calendar-detail-label">Event</div>
        <div className="tf-calendar-detail-title">
          {earningTicker ? (
            <a href={`/stock/${earningTicker}`}>{displayTitle}</a>
          ) : (
            displayTitle
          )}
        </div>
      </div>

      <div className="tf-calendar-detail-grid">
        <div>
          <strong>Date:</strong>{" "}
          {event.category === "earning"
            ? localDateOnly
            : event.displayTime || localDate}
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
