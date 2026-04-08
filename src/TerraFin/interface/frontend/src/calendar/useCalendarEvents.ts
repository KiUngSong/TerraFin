import { useCallback, useEffect, useState } from "react";
import { CALENDAR_API_BASE } from "./constants";
import type { CalendarEvent, CalendarEventsResponse, EventCategory } from "./types";

function normalizeCategory(category: unknown): EventCategory {
  if (category === "earning" || category === "macro") return category;
  return "event";
}

function normalizeEvent(raw: Partial<CalendarEvent>): CalendarEvent | null {
  if (!raw.id || !raw.title || !raw.start) return null;
  return {
    id: String(raw.id),
    title: String(raw.title),
    start: String(raw.start),
    category: normalizeCategory(raw.category),
    importance: raw.importance ?? null,
    displayTime: raw.displayTime ?? null,
    description: raw.description ?? null,
    source: raw.source ?? null,
  };
}

export function useCalendarEvents(month: number, year: number): {
  events: CalendarEvent[];
  loading: boolean;
  error: string | null;
  refetch: () => Promise<void>;
} {
  const [events, setEvents] = useState<CalendarEvent[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const refetch = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(`${CALENDAR_API_BASE}/events?month=${month}&year=${year}`);
      if (!response.ok) {
        throw new Error(`Failed to load events (${response.status})`);
      }
      const payload = (await response.json()) as CalendarEventsResponse;
      const nextEvents = (payload.events || []).map(normalizeEvent).filter(Boolean) as CalendarEvent[];
      setEvents(nextEvents);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load events");
    } finally {
      setLoading(false);
    }
  }, [month, year]);

  useEffect(() => {
    void refetch();
  }, [refetch]);

  return { events, loading, error, refetch };
}
