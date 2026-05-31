import React, { useEffect, useMemo, useRef, useState } from "react";
import FullCalendar from "@fullcalendar/react";
import dayGridPlugin from "@fullcalendar/daygrid";
import type { DatesSetArg, EventClickArg, EventContentArg } from "@fullcalendar/core";
import InsightCard from "../terminal/components/InsightCard";
import CalendarDetailPanel from "./components/CalendarDetailPanel";
import CalendarAgenda from "./components/CalendarAgenda";
import CalendarFilters from "./components/CalendarFilters";
import { useViewportTier } from "../shared/responsive";
import { CATEGORY_COLORS } from "./constants";
import type { CalendarEvent, EventCategory } from "./types";
import { useCalendarEvents } from "./useCalendarEvents";
import "./calendar.css";

const allCategories: EventCategory[] = ["earning", "macro"];

const CalendarPage: React.FC = () => {
  const now = new Date();
  const [month, setMonth] = useState(now.getMonth() + 1);
  const [year, setYear] = useState(now.getFullYear());
  const [selectedCategories, setSelectedCategories] = useState<Set<EventCategory>>(new Set(allCategories));
  const [selectedEvent, setSelectedEvent] = useState<CalendarEvent | null>(null);
  const { isMobile } = useViewportTier();
  const detailRef = useRef<HTMLDivElement>(null);

  // Mobile: the detail card stacks far below the month grid, so tapping an event
  // updated something the user couldn't see. Scroll it into view on selection.
  // Vertical-only via window.scrollTo — scrollIntoView walks every scroll
  // ancestor and was nudging the layout sideways (the "pushed left" bug).
  useEffect(() => {
    if (isMobile && selectedEvent && detailRef.current) {
      const top = detailRef.current.getBoundingClientRect().top + window.scrollY - 8;
      window.scrollTo({ top, behavior: "smooth" });
    }
  }, [isMobile, selectedEvent]);
  const { events, loading, error, refetch } = useCalendarEvents(month, year);

  const visibleEvents = useMemo(
    () => events.filter((event) => selectedCategories.has(event.category)),
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

  // Month nav for the mobile agenda (FC's toolbar drove month/year via
  // datesSet on desktop; the agenda has no FC, so it writes the same state).
  const goPrevMonth = () => {
    setSelectedEvent(null);
    if (month === 1) { setMonth(12); setYear((y) => y - 1); }
    else setMonth((m) => m - 1);
  };
  const goNextMonth = () => {
    setSelectedEvent(null);
    if (month === 12) { setMonth(1); setYear((y) => y + 1); }
    else setMonth((m) => m + 1);
  };
  const goToday = () => {
    const d = new Date();
    setSelectedEvent(null);
    setMonth(d.getMonth() + 1);
    setYear(d.getFullYear());
  };

  // Shared selection: sets the detail event AND posts selection (the agenda and
  // the desktop FC click both go through this so neither drops the POST).
  const selectEvent = (event: CalendarEvent) => {
    setSelectedEvent(event);
    void fetch("/calendar/api/selection", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ eventId: event.id, month, year }),
    });
  };

  const handleEventClick = (arg: EventClickArg) => {
    const category = (arg.event.extendedProps.category as EventCategory) || "macro";
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
    selectEvent(event);
  };

  const renderEvent = (arg: EventContentArg): React.ReactNode => {
    const category = (arg.event.extendedProps.category as EventCategory) || "macro";
    const color = CATEGORY_COLORS[category];
    const title = arg.event.title;
    // Desktop month grid: ticker only (before " - "); full name in detail panel.
    // (Mobile uses CalendarAgenda, not FullCalendar.)
    const label = title.includes(" - ") ? title.split(" - ")[0] : title;
    return (
      <div className="tf-calendar-event">
        <span className="tf-calendar-dot" style={{ backgroundColor: color }} />
        <span className="tf-calendar-event-title">{label}</span>
      </div>
    );
  };

  return (
    <div className="tf-calendar-page">
      <main className="tf-calendar-content">
        <InsightCard
          title="Economic And Earnings Calendar"
          subtitle="Track macro prints and company catalysts with month and agenda views."
          minHeight={88}
        >
          <div className="tf-calendar-toolbar">
            <CalendarFilters selected={selectedCategories} onToggle={toggleCategory} />
          </div>
          <div className="tf-calendar-results-meta">
            Showing {visibleEvents.length} event{visibleEvents.length === 1 ? "" : "s"} in {month}/{year}
          </div>
        </InsightCard>

        <div className="tf-calendar-layout">
          <InsightCard title="Calendar View" subtitle="Use month and list to scan events quickly.">
            <section className="tf-calendar-main" aria-busy={loading}>
              {isMobile ? (
                <CalendarAgenda
                  events={visibleEvents}
                  month={month}
                  year={year}
                  onSelectEvent={selectEvent}
                  onPrev={goPrevMonth}
                  onNext={goNextMonth}
                  onToday={goToday}
                  loading={loading}
                  error={error}
                  onRetry={() => void refetch()}
                />
              ) : (
                <>
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
                    plugins={[dayGridPlugin]}
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
                        category: event.category,
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
                </>
              )}
            </section>
          </InsightCard>

          {/* Detail panel: on mobile the agenda IS the list, so only show the
              detail card once an event is picked (no redundant second agenda).
              Desktop always shows it (the side rail's UPCOMING is a useful preview). */}
          {!isMobile || selectedEvent ? (
            <div ref={detailRef} style={{ scrollMarginTop: 12, minWidth: 0 }}>
              <InsightCard title="Selected Event" subtitle="Click an event for details." fillContent>
                <CalendarDetailPanel
                  event={selectedEvent}
                  upcomingEvents={visibleEvents}
                  onSelectEvent={selectEvent}
                />
              </InsightCard>
            </div>
          ) : null}
        </div>
      </main>
    </div>
  );
};

export default CalendarPage;
