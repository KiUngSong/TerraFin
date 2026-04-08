import React, { useState, useCallback } from 'react';
import DatePicker from 'react-datepicker';
import 'react-datepicker/dist/react-datepicker.css';
import { FONT_FAMILY } from '../constants';

export type DateSelectionRequest =
  | { type: 'date'; date: string }
  | { type: 'range'; from: string; to: string }
  | null;

type TabId = 'date' | 'range';

const MONTH_NAMES = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];

function formatDate(d: Date): string {
  return d.toISOString().slice(0, 10);
}

function ModernCalendarHeader({
  date,
  changeMonth,
  decreaseMonth,
  increaseMonth,
  prevMonthButtonDisabled,
  nextMonthButtonDisabled,
}: {
  date: Date;
  changeMonth: (month: number) => void;
  decreaseMonth: () => void;
  increaseMonth: () => void;
  prevMonthButtonDisabled: boolean;
  nextMonthButtonDisabled: boolean;
}) {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '12px 8px 16px',
        gap: 8,
      }}
    >
      <button
        type="button"
        onClick={decreaseMonth}
        disabled={prevMonthButtonDisabled}
        aria-label="Previous month"
        style={{
          padding: 6,
          border: 'none',
          background: 'transparent',
          color: '#616161',
          cursor: prevMonthButtonDisabled ? 'default' : 'pointer',
          fontSize: 16,
          lineHeight: 1,
        }}
      >
        {'<'}
      </button>
      <div
        style={{
          flex: 1,
          textAlign: 'center',
          padding: '8px 16px',
          background: '#f0f0f0',
          borderRadius: 20,
          fontSize: 14,
          fontWeight: 500,
          color: '#212121',
        }}
      >
        {MONTH_NAMES[date.getMonth()]} {date.getFullYear()}
      </div>
      <button
        type="button"
        onClick={increaseMonth}
        disabled={nextMonthButtonDisabled}
        aria-label="Next month"
        style={{
          padding: 6,
          border: 'none',
          background: 'transparent',
          color: '#616161',
          cursor: nextMonthButtonDisabled ? 'default' : 'pointer',
          fontSize: 16,
          lineHeight: 1,
        }}
      >
        {'>'}
      </button>
    </div>
  );
}

interface DateSelectorProps {
  isOpen: boolean;
  onClose: () => void;
  onSelect: (request: NonNullable<DateSelectionRequest>) => void;
}

const DateSelector: React.FC<DateSelectorProps> = ({ isOpen, onClose, onSelect }) => {
  const [tab, setTab] = useState<TabId>('date');
  const [date, setDate] = useState<Date>(() => new Date());
  const [rangeFrom, setRangeFrom] = useState<Date>(() => {
    const d = new Date();
    d.setMonth(d.getMonth() - 1);
    return d;
  });
  const [rangeTo, setRangeTo] = useState<Date>(() => new Date());

  const handleSubmit = useCallback(() => {
    if (tab === 'date') {
      onSelect({ type: 'date', date: formatDate(date) });
    } else {
      const from = formatDate(rangeFrom);
      const to = formatDate(rangeTo);
      if (from <= to) {
        onSelect({ type: 'range', from, to });
      }
    }
    onClose();
  }, [tab, date, rangeFrom, rangeTo, onSelect, onClose]);

  const handleBackdropClick = useCallback(
    (e: React.MouseEvent) => {
      if (e.target === e.currentTarget) onClose();
    },
    [onClose]
  );

  const renderCustomHeader = useCallback(
    (props: {
      date: Date;
      changeMonth: (month: number) => void;
      decreaseMonth: () => void;
      increaseMonth: () => void;
      prevMonthButtonDisabled: boolean;
      nextMonthButtonDisabled: boolean;
    }) => (
      <ModernCalendarHeader
        date={props.date}
        changeMonth={props.changeMonth}
        decreaseMonth={props.decreaseMonth}
        increaseMonth={props.increaseMonth}
        prevMonthButtonDisabled={props.prevMonthButtonDisabled}
        nextMonthButtonDisabled={props.nextMonthButtonDisabled}
      />
    ),
    []
  );

  if (!isOpen) return null;

  const rangeValid = tab !== 'range' || formatDate(rangeFrom) <= formatDate(rangeTo);

  const datePickerCommon = {
    dateFormat: 'yyyy-MM-dd',
    renderCustomHeader: renderCustomHeader,
    className: 'terrafin-datepicker-input',
    wrapperClassName: 'terrafin-datepicker-wrapper',
    calendarClassName: 'terrafin-calendar-modern',
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="date-modal-title"
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(0,0,0,0.35)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 1000,
        fontFamily: FONT_FAMILY,
      }}
      onClick={handleBackdropClick}
    >
      <div
        style={{
          background: '#fff',
          borderRadius: 12,
          boxShadow: '0 8px 32px rgba(0,0,0,0.12)',
          minWidth: 320,
          maxWidth: 380,
          overflow: 'hidden',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: '16px 20px',
            borderBottom: '1px solid #eee',
          }}
        >
          <h2
            id="date-modal-title"
            style={{
              margin: 0,
              fontSize: 18,
              fontWeight: 600,
              color: '#212121',
            }}
          >
            Date
          </h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            style={{
              padding: 4,
              border: 'none',
              background: 'transparent',
              cursor: 'pointer',
              fontSize: 20,
              lineHeight: 1,
              color: '#616161',
            }}
          >
            x
          </button>
        </div>

        <div
          style={{
            padding: '16px 20px',
            maxHeight: '70vh',
            overflowY: 'auto',
          }}
        >
          <div
            style={{
              display: 'flex',
              gap: 0,
              marginBottom: 16,
              borderBottom: '1px solid #eee',
            }}
          >
            <button
              type="button"
              onClick={() => setTab('date')}
              style={{
                fontFamily: FONT_FAMILY,
                padding: '8px 12px',
                fontSize: 14,
                fontWeight: 500,
                border: 'none',
                background: 'transparent',
                color: tab === 'date' ? '#1976d2' : '#616161',
                cursor: 'pointer',
                borderBottom: tab === 'date' ? '2px solid #1976d2' : '2px solid transparent',
                marginBottom: -1,
              }}
            >
              Date
            </button>
            <button
              type="button"
              onClick={() => setTab('range')}
              style={{
                fontFamily: FONT_FAMILY,
                padding: '8px 12px',
                fontSize: 14,
                fontWeight: 500,
                border: 'none',
                background: 'transparent',
                color: tab === 'range' ? '#1976d2' : '#616161',
                cursor: 'pointer',
                borderBottom: tab === 'range' ? '2px solid #1976d2' : '2px solid transparent',
                marginBottom: -1,
              }}
            >
              Custom range
            </button>
          </div>

          {tab === 'date' && (
            <div style={{ marginBottom: 16 }}>
              <label
                style={{
                  display: 'block',
                  fontSize: 12,
                  fontWeight: 500,
                  color: '#616161',
                  marginBottom: 8,
                }}
              >
                Pick a date
              </label>
              <DatePicker selected={date} onChange={(d: Date | null) => d && setDate(d)} {...datePickerCommon} />
            </div>
          )}

          {tab === 'range' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12, marginBottom: 16 }}>
              <div>
                <label
                  style={{
                    display: 'block',
                    fontSize: 12,
                    fontWeight: 500,
                    color: '#616161',
                    marginBottom: 8,
                  }}
                >
                  From
                </label>
                <DatePicker selected={rangeFrom} onChange={(d: Date | null) => d && setRangeFrom(d)} {...datePickerCommon} />
              </div>
              <div>
                <label
                  style={{
                    display: 'block',
                    fontSize: 12,
                    fontWeight: 500,
                    color: '#616161',
                    marginBottom: 8,
                  }}
                >
                  To
                </label>
                <DatePicker selected={rangeTo} onChange={(d: Date | null) => d && setRangeTo(d)} {...datePickerCommon} />
              </div>
              {!rangeValid && <span style={{ fontSize: 12, color: '#c62828' }}>From date must be before or equal to To date.</span>}
            </div>
          )}

          <div
            style={{
              display: 'flex',
              justifyContent: 'flex-end',
              gap: 8,
              marginTop: 20,
            }}
          >
            <button
              type="button"
              onClick={onClose}
              style={{
                fontFamily: FONT_FAMILY,
                padding: '8px 16px',
                fontSize: 14,
                fontWeight: 500,
                border: '1px solid #e0e0e0',
                borderRadius: 8,
                background: '#fff',
                color: '#212121',
                cursor: 'pointer',
              }}
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={handleSubmit}
              disabled={tab === 'range' && !rangeValid}
              style={{
                fontFamily: FONT_FAMILY,
                padding: '8px 16px',
                fontSize: 14,
                fontWeight: 500,
                border: 'none',
                borderRadius: 8,
                background: tab === 'range' && !rangeValid ? '#e0e0e0' : '#212121',
                color: '#fff',
                cursor: tab === 'range' && !rangeValid ? 'not-allowed' : 'pointer',
              }}
            >
              Apply
            </button>
          </div>
        </div>
      </div>
      <style>{`
        .terrafin-datepicker-wrapper { display: block; width: 100%; }
        .terrafin-datepicker-input {
          width: 100%;
          padding: 10px 12px;
          font-size: 14px;
          font-family: ${FONT_FAMILY};
          border: 1px solid #e8e8e8;
          border-radius: 8px;
          box-sizing: border-box;
        }
        .terrafin-datepicker-input:focus {
          outline: none;
          border-color: #bdbdbd;
        }
        .terrafin-calendar-modern {
          font-family: ${FONT_FAMILY} !important;
          border: none !important;
          border-radius: 12px !important;
          box-shadow: 0 4px 20px rgba(0,0,0,0.08) !important;
          padding: 0 8px 12px !important;
          height: 320px !important;
          max-height: 320px !important;
          min-height: 320px !important;
          overflow-y: auto !important;
          overflow-x: hidden !important;
          display: block !important;
          box-sizing: border-box !important;
        }
        .terrafin-calendar-modern .react-datepicker__header {
          background: transparent !important;
          border: none !important;
          padding: 0 !important;
        }
        .terrafin-calendar-modern .react-datepicker__day-names {
          margin-bottom: 8px !important;
        }
        .terrafin-calendar-modern .react-datepicker__day-name {
          color: #212121 !important;
          font-size: 13px !important;
          font-weight: 500 !important;
          width: 2.2rem !important;
          line-height: 2.2rem !important;
          margin: 0.2rem !important;
        }
        .terrafin-calendar-modern .react-datepicker__day {
          width: 2.2rem !important;
          line-height: 2.2rem !important;
          margin: 0.2rem !important;
          border-radius: 8px !important;
          font-size: 14px !important;
          color: #212121 !important;
        }
        .terrafin-calendar-modern .react-datepicker__day:hover {
          background: #f0f0f0 !important;
        }
        .terrafin-calendar-modern .react-datepicker__day--selected,
        .terrafin-calendar-modern .react-datepicker__day--keyboard-selected {
          background: #424242 !important;
          color: #fff !important;
          font-weight: 500 !important;
        }
        .terrafin-calendar-modern .react-datepicker__day--outside-month {
          color: #bdbdbd !important;
        }
        .terrafin-calendar-modern .react-datepicker__month-container {
          float: none !important;
        }
        .react-datepicker-popper .terrafin-calendar-modern {
          height: 320px !important;
          max-height: 320px !important;
          min-height: 320px !important;
        }
      `}</style>
    </div>
  );
};

export default DateSelector;
