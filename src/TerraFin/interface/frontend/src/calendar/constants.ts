import type { EventCategory } from "./types";

export const CALENDAR_API_BASE = "/calendar/api";

export const CATEGORY_COLORS: Record<EventCategory, string> = {
  earning: "#2563eb",
  macro: "#7c3aed",
  event: "#0891b2",
};

export const CATEGORY_LABELS: Record<EventCategory, string> = {
  earning: "Earnings",
  macro: "Macro",
  event: "Other",
};
