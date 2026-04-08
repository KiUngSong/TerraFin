export type EventCategory = "earning" | "macro" | "event";

export interface CalendarEvent {
  id: string;
  title: string;
  start: string;
  category: EventCategory;
  importance?: string | null;
  displayTime?: string | null;
  description?: string | null;
  source?: string | null;
}

export interface CalendarEventsResponse {
  events: CalendarEvent[];
  count: number;
  month: number;
  year: number;
}
