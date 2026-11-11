import React, { useEffect, useMemo, useState } from "react";

interface CatalystEvent {
  id: string;
  title: string;
  start: string;
  category: string;
}

const MAX_EVENTS = 12;

// The date part, so a midnight-UTC start shows the same day in every time zone.
const fmtDate = (iso: string): string => `${iso.slice(5, 7)}/${iso.slice(8, 10)}`;

const fmtCategory = (cat: string): string => {
  const m: Record<string, string> = {
    earning: "EPS",
    earnings: "EPS",
    macro: "MAC",
    other: "OTH",
  };
  return m[cat.toLowerCase()] ?? cat.slice(0, 3).toUpperCase();
};

const extractSymbol = (title: string): { sym: string; rest: string } => {
  const m = title.match(/^([A-Z.]{1,8})\s*[-–]\s*(.+)$/);
  if (m) return { sym: m[1], rest: m[2] };
  return { sym: "", rest: title };
};

const UpcomingCatalysts: React.FC = () => {
  const [events, setEvents] = useState<CatalystEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const now = useMemo(() => new Date(), []);

  // The API returns a whole month from its first day, so this month and the next
  // are read and only events from today on are kept.
  useEffect(() => {
    const months = [0, 1].map((offset) => new Date(now.getFullYear(), now.getMonth() + offset, 1));
    // `start` is a calendar date at midnight, so events compare by their date part.
    const pad = (n: number) => String(n).padStart(2, "0");
    const today = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
    Promise.all(
      months.map((m) =>
        fetch(`/calendar/api/events?month=${m.getMonth() + 1}&year=${m.getFullYear()}`).then((res) =>
          res.ok ? res.json() : Promise.reject(new Error(`${res.status}`)),
        ),
      ),
    )
      .then((payloads: Array<{ events?: CatalystEvent[] }>) =>
        setEvents(
          payloads
            .flatMap((p) => p.events || [])
            .filter((e) => e.start.slice(0, 10) >= today)
            .sort((a, b) => a.start.slice(0, 10).localeCompare(b.start.slice(0, 10)))
            .slice(0, MAX_EVENTS),
        ),
      )
      .catch(() => setEvents([]))
      .finally(() => setLoading(false));
  }, [now]);

  return (
    <div className="tf-table tf-table--events">
      <div className="tf-table__head">
        <span className="tf-table__col tf-table__col--sym">Date</span>
        <span className="tf-table__col tf-table__col--name">Event</span>
        <span className="tf-table__col tf-table__col--num">Type</span>
      </div>
      <div className="tf-table__body">
        {loading ? <div className="tf-table__status">loading…</div> : null}
        {!loading && events.length === 0 ? (
          <div className="tf-table__status">no upcoming events</div>
        ) : null}
        {events.map((event) => {
          const { sym, rest } = extractSymbol(event.title);
          return (
            <a
              key={event.id}
              href="/calendar"
              className="tf-table__row"
              title={event.title}
            >
              <span className="tf-table__col tf-table__col--sym">{fmtDate(event.start)}</span>
              <span className="tf-table__col tf-table__col--name">
                {sym ? <span className="tf-events__sym">{sym}</span> : null}
                {sym ? " " : ""}
                {rest}
              </span>
              <span className="tf-table__col tf-table__col--num">{fmtCategory(event.category)}</span>
            </a>
          );
        })}
      </div>
    </div>
  );
};

export default UpcomingCatalysts;
