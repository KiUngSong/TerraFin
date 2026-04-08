import React from "react";
import { CATEGORY_LABELS } from "../constants";
import type { EventCategory } from "../types";

interface CalendarFiltersProps {
  selected: Set<EventCategory>;
  onToggle: (category: EventCategory) => void;
}

const categories: EventCategory[] = ["earning", "macro", "event"];

const CalendarFilters: React.FC<CalendarFiltersProps> = ({ selected, onToggle }) => (
  <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
    {categories.map((category) => {
      const active = selected.has(category);
      return (
        <button
          key={category}
          type="button"
          onClick={() => onToggle(category)}
          style={{
            border: active ? "1px solid #1d4ed8" : "1px solid #cbd5e1",
            background: active ? "#dbeafe" : "#ffffff",
            color: active ? "#1e3a8a" : "#334155",
            fontSize: 12,
            fontWeight: 600,
            borderRadius: 999,
            padding: "6px 10px",
            cursor: "pointer",
          }}
        >
          {CATEGORY_LABELS[category]}
        </button>
      );
    })}
  </div>
);

export default CalendarFilters;
