import React from "react";
import { CATEGORY_COLORS } from "../constants";
import type { CalendarEvent } from "../types";

interface CalendarAgendaProps {
  events: CalendarEvent[];
  month: number; // 1-12
  year: number;
  onSelectEvent: (event: CalendarEvent) => void;
  onPrev: () => void;
  onNext: () => void;
  onToday: () => void;
  loading: boolean;
  error: string | null;
  onRetry: () => void;
}

interface DayGroup {
  key: string;
  date: string;
  weekday: string;
  events: CalendarEvent[];
}

// Force en-US: `undefined`/`[]` locale follows the device, which rendered the
// whole agenda in Korean on a Korean-locale phone. The UI is English.
function formatTime(iso: string): string {
  const d = new Date(iso);
  return d
    .toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" })
    .toLowerCase()
    .replace(/\s/g, "");
}

function groupByDay(events: CalendarEvent[]): DayGroup[] {
  const sorted = [...events].sort(
    (a, b) => new Date(a.start).getTime() - new Date(b.start).getTime(),
  );
  const groups: DayGroup[] = [];
  const index: Record<string, DayGroup> = {};
  for (const e of sorted) {
    const d = new Date(e.start);
    const key = `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
    let group = index[key];
    if (!group) {
      group = {
        key,
        date: d.toLocaleDateString("en-US", { month: "long", day: "numeric", year: "numeric" }),
        weekday: d.toLocaleDateString("en-US", { weekday: "long" }),
        events: [],
      };
      index[key] = group;
      groups.push(group);
    }
    group.events.push(e);
  }
  return groups;
}

// Pure-React agenda for mobile. Replaces FullCalendar's listMonth view, whose
// HTML <table> + colspan day-header made column widths uncontrollable (endless
// spread / shift / collapse). This is plain flex rows — no table, no FC.
const CalendarAgenda: React.FC<CalendarAgendaProps> = ({
  events,
  month,
  year,
  onSelectEvent,
  onPrev,
  onNext,
  onToday,
  loading,
  error,
  onRetry,
}) => {
  const monthLabel = new Date(year, month - 1).toLocaleDateString("en-US", {
    month: "long",
    year: "numeric",
  });
  const groups = groupByDay(events);

  return (
    <div className="tf-magenda">
      <div className="tf-magenda__nav">
        <button type="button" className="tf-magenda__navbtn" onClick={onPrev} aria-label="Previous month">‹</button>
        <button type="button" className="tf-magenda__navbtn" onClick={onNext} aria-label="Next month">›</button>
        <button type="button" className="tf-magenda__navbtn tf-magenda__today" onClick={onToday}>today</button>
        <span className="tf-magenda__title">{monthLabel}</span>
      </div>

      {loading ? <div className="tf-magenda__state">Loading events…</div> : null}
      {error ? (
        <div className="tf-magenda__state tf-magenda__state--error">
          {error}{" "}
          <button type="button" onClick={onRetry} className="tf-link-button">Retry</button>
        </div>
      ) : null}
      {!loading && !error && groups.length === 0 ? (
        <div className="tf-magenda__state">No events found for this month and filters.</div>
      ) : null}

      {!loading && !error
        ? groups.map((group) => (
            <div key={group.key}>
              <div className="tf-magenda__day">
                {group.date} <span className="tf-magenda__day-wd">{group.weekday}</span>
              </div>
              {group.events.map((e) => (
                <button
                  key={e.id}
                  type="button"
                  className="tf-magenda__row"
                  onClick={() => onSelectEvent(e)}
                >
                  <span className="tf-magenda__time">{formatTime(e.start)}</span>
                  <span className="tf-calendar-dot" style={{ backgroundColor: CATEGORY_COLORS[e.category] }} />
                  <span className="tf-magenda__title-text">{e.title}</span>
                </button>
              ))}
            </div>
          ))
        : null}
    </div>
  );
};

export default CalendarAgenda;
