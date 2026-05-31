import React from "react";
import { CATEGORY_LABELS } from "../constants";
import type { EventCategory } from "../types";

interface CalendarFiltersProps {
  selected: Set<EventCategory>;
  onToggle: (category: EventCategory) => void;
}

const categories: EventCategory[] = ["earning", "macro"];

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
            border: active ? "1px solid var(--tf-amber)" : "1px solid var(--tf-border)",
            background: active ? "var(--tf-bg-hover)" : "var(--tf-bg-elevated)",
            color: active ? "var(--tf-amber)" : "var(--tf-text)",
            fontSize: "var(--tf-fs-xs)",
            fontWeight: 600,
            borderRadius: "var(--tf-radius)",
            padding: "6px 10px",
            cursor: "pointer",
            fontFamily: "var(--tf-mono)",
          }}
        >
          {CATEGORY_LABELS[category]}
        </button>
      );
    })}
  </div>
);

export default CalendarFilters;
