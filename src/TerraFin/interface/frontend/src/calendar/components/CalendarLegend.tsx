import React from "react";
import { CATEGORY_COLORS, CATEGORY_LABELS } from "../constants";
import type { EventCategory } from "../types";

const categories: EventCategory[] = ["earning", "macro", "event"];

const CalendarLegend: React.FC = () => (
  <div style={{ display: "flex", flexWrap: "wrap", gap: 12 }}>
    {categories.map((category) => (
      <div key={category} style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 12, color: "#334155" }}>
        <span
          style={{
            width: 10,
            height: 10,
            borderRadius: "999px",
            display: "inline-block",
            backgroundColor: CATEGORY_COLORS[category],
          }}
        />
        {CATEGORY_LABELS[category]}
      </div>
    ))}
  </div>
);

export default CalendarLegend;
