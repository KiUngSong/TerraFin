import React, { useEffect, useMemo, useState } from "react";

interface CatalystEvent {
  id: string;
  title: string;
  start: string;
  category: string;
}

const UpcomingCatalysts: React.FC = () => {
  const [events, setEvents] = useState<CatalystEvent[]>([]);
  const [loading, setLoading] = useState<boolean>(true);

  const now = useMemo(() => new Date(), []);

  useEffect(() => {
    const month = now.getMonth() + 1;
    const year = now.getFullYear();
    fetch(`/calendar/api/events?month=${month}&year=${year}&limit=3`)
      .then((res) => (res.ok ? res.json() : Promise.reject(new Error(`${res.status}`))))
      .then((payload: { events?: CatalystEvent[] }) => setEvents(payload.events || []))
      .catch(() => setEvents([]))
      .finally(() => setLoading(false));
  }, [now]);

  if (loading) {
    return <div style={{ fontSize: 13, color: "#475569" }}>Loading upcoming events...</div>;
  }

  return (
    <div style={{ display: "grid", gap: 10 }}>
      {events.length === 0 ? (
        <div
          style={{
            border: "1px dashed #cbd5e1",
            borderRadius: 10,
            padding: 12,
            fontSize: 13,
            color: "#475569",
            background: "#f8fafc",
          }}
        >
          No events available for this month yet.
        </div>
      ) : (
        <div className="tf-upcoming-catalysts-grid">
          {events.map((event) => (
            <div
              key={event.id}
              style={{
                border: "1px solid #e2e8f0",
                borderRadius: 10,
                padding: "8px 10px",
                background: "#ffffff",
                display: "grid",
                gap: 4,
              }}
            >
              <div style={{ fontSize: 13, fontWeight: 600, color: "#0f172a" }}>{event.title}</div>
              <div style={{ fontSize: 12, color: "#64748b" }}>
                {new Date(event.start).toLocaleDateString()} - {event.category}
              </div>
            </div>
          ))}
        </div>
      )}
      <a
        href="/calendar"
        style={{
          marginTop: 2,
          fontSize: 12,
          fontWeight: 600,
          color: "#1d4ed8",
          textDecoration: "none",
        }}
      >
        Open full calendar →
      </a>
    </div>
  );
};

export default UpcomingCatalysts;
