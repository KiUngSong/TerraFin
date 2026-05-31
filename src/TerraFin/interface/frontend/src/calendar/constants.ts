import type { EventCategory } from "./types";

export const CALENDAR_API_BASE = "/calendar/api";

export const CATEGORY_COLORS: Record<EventCategory, string> = {
  earning: "var(--tf-amber)",
  macro: "var(--tf-up)",
};

export const CATEGORY_LABELS: Record<EventCategory, string> = {
  earning: "Earnings",
  macro: "Macro",
};
