import React, { useEffect, useMemo, useState } from "react";

interface CatalystEvent {
  id: string;
  title: string;
  start: string;
  category: string;
}

const fmtDate = (iso: string): string => {
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso.slice(0, 10);
    const mm = String(d.getMonth() + 1).padStart(2, "0");
    const dd = String(d.getDate()).padStart(2, "0");
    return `${mm}/${dd}`;
  } catch {
    return iso;
  }
};

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

  useEffect(() => {
    const month = now.getMonth() + 1;
    const year = now.getFullYear();
    fetch(`/calendar/api/events?month=${month}&year=${year}&limit=12`)
      .then((res) => (res.ok ? res.json() : Promise.reject(new Error(`${res.status}`))))
      .then((payload: { events?: CatalystEvent[] }) => setEvents(payload.events || []))
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
