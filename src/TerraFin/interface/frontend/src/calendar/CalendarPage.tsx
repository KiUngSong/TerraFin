import React, { useMemo, useState } from "react";
import FullCalendar from "@fullcalendar/react";
import dayGridPlugin from "@fullcalendar/daygrid";
import interactionPlugin from "@fullcalendar/interaction";
import type { DatesSetArg, EventClickArg, EventContentArg } from "@fullcalendar/core";
import DashboardHeader from "../dashboard/components/DashboardHeader";
import InsightCard from "../dashboard/components/InsightCard";
import CalendarDetailPanel from "./components/CalendarDetailPanel";
import CalendarFilters from "./components/CalendarFilters";
import CalendarLegend from "./components/CalendarLegend";
import { CATEGORY_COLORS } from "./constants";
import type { CalendarEvent, EventCategory } from "./types";
import { useCalendarEvents } from "./useCalendarEvents";
import "./calendar.css";

const allCategories: EventCategory[] = ["earning", "macro", "event"];

const CalendarPage: React.FC = () => {
  const now = new Date();
  const [month, setMonth] = useState(now.getMonth() + 1);
  const [year, setYear] = useState(now.getFullYear());
  const [searchValue, setSearchValue] = useState("");
  const [selectedCategories, setSelectedCategories] = useState<Set<EventCategory>>(new Set(allCategories));
  const [selectedEvent, setSelectedEvent] = useState<CalendarEvent | null>(null);
  const { events, loading, error, refetch } = useCalendarEvents(month, year);

  const visibleEvents = useMemo(
    () => events.filter((event) => selectedCategories.has(event.category || "event")),
    [events, selectedCategories],
  );

  const toggleCategory = (category: EventCategory) => {
    setSelectedEvent(null);
    setSelectedCategories((current) => {
      const next = new Set(current);
      if (next.has(category)) {
        if (next.size === 1) return next;
        next.delete(category);
      } else {
        next.add(category);
      }
      return next;
    });
  };

  const handleDatesSet = (arg: DatesSetArg) => {
    const currentMonth = arg.view.currentStart;
    const nextMonth = currentMonth.getMonth() + 1;
    const nextYear = currentMonth.getFullYear();
    if (nextMonth !== month || nextYear !== year) {
      setMonth(nextMonth);
      setYear(nextYear);
      setSelectedEvent(null);
    }
  };

  const handleEventClick = (arg: EventClickArg) => {
    const category = (arg.event.extendedProps.category as EventCategory) || "event";
    const event: CalendarEvent = {
      id: arg.event.id,
      title: arg.event.title,
      start: arg.event.startStr,
      category,
      importance: arg.event.extendedProps.importance as string | null,
      displayTime: arg.event.extendedProps.displayTime as string | null,
      description: arg.event.extendedProps.description as string | null,
      source: arg.event.extendedProps.source as string | null,
    };
    setSelectedEvent(event);
    void fetch("/calendar/api/selection", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ eventId: event.id, month, year }),
    });
  };

  const renderEvent = (arg: EventContentArg): React.ReactNode => {
    const category = (arg.event.extendedProps.category as EventCategory) || "event";
    const color = CATEGORY_COLORS[category];
    // Show ticker only (before " - "), full name in detail panel
    const title = arg.event.title;
    const short = title.includes(" - ") ? title.split(" - ")[0] : title;
    return (
      <div className="tf-calendar-event">
        <span className="tf-calendar-dot" style={{ backgroundColor: color }} />
        <span className="tf-calendar-event-title">{short}</span>
      </div>
    );
  };

  return (
    <div className="tf-calendar-page">
      <DashboardHeader
        searchValue={searchValue}
        onSearchChange={setSearchValue}
      />

      <main className="tf-calendar-content">
        <InsightCard
          title="Economic And Earnings Calendar"
          subtitle="Track macro prints and company catalysts with month and agenda views."
          minHeight={88}
        >
          <div className="tf-calendar-toolbar">
            <CalendarLegend />
            <CalendarFilters selected={selectedCategories} onToggle={toggleCategory} />
          </div>
          <div className="tf-calendar-results-meta">
            Showing {visibleEvents.length} event{visibleEvents.length === 1 ? "" : "s"} in {month}/{year}
          </div>
        </InsightCard>

        <div className="tf-calendar-layout">
          <InsightCard title="Calendar View" subtitle="Use month and list to scan events quickly.">
            <section className="tf-calendar-main" aria-busy={loading}>
              {loading ? <div className="tf-calendar-state">Loading events...</div> : null}
              {error ? (
                <div className="tf-calendar-state error">
                  {error}{" "}
                  <button type="button" onClick={() => void refetch()} className="tf-link-button">
                    Retry
                  </button>
                </div>
              ) : null}
              {!loading && !error && visibleEvents.length === 0 ? (
                <div className="tf-calendar-state">No events found for this month and filters.</div>
              ) : null}

              <FullCalendar
                plugins={[dayGridPlugin, interactionPlugin]}
                initialView="dayGridMonth"
                initialDate={new Date(year, month - 1)}
                headerToolbar={{
                  left: "prev,next today",
                  center: "title",
                  right: "",
                }}
                events={visibleEvents.map((event) => ({
                  id: event.id,
                  title: event.title,
                  start: event.start,
                  extendedProps: {
                    category: event.category || "event",
                    importance: event.importance || null,
                    displayTime: event.displayTime || null,
                    description: event.description || null,
                    source: event.source || null,
                  },
                }))}
                dayMaxEvents={4}
                eventContent={renderEvent}
                eventDidMount={(info) => {
                  info.el.setAttribute("tabindex", "0");
                  info.el.setAttribute("title", info.event.title);
                }}
                eventClick={handleEventClick}
                datesSet={handleDatesSet}
                height="auto"
              />
            </section>
          </InsightCard>

          <InsightCard title="Selected Event" subtitle="Click an event to inspect details and source context.">
            <CalendarDetailPanel event={selectedEvent} />
          </InsightCard>
        </div>
      </main>
    </div>
  );
};

export default CalendarPage;
