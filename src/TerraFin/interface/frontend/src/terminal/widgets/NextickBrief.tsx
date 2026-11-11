import React, { useEffect, useState } from 'react';

interface NextickIssue {
  date: string;
  headline: string;
  url: string;
  publishedAt: string | null;
}

const API = '/terminal/api/nextick/latest';
const SEEN_KEY = 'tf-nextick-seen';
const REFRESH_MS = 10 * 60 * 1000;

// `date` is the US trading day the issue covers, a calendar date with no zone.
const fmtIssueDate = (date: string): string =>
  new Date(`${date}T12:00:00Z`).toLocaleDateString('en-US', {
    weekday: 'short',
    month: 'short',
    day: 'numeric',
    timeZone: 'UTC',
  });

const fmtAgo = (iso: string | null): string => {
  if (!iso) return '';
  const minutes = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (!Number.isFinite(minutes) || minutes < 0) return '';
  if (minutes < 60) return `${minutes}m ago`;
  if (minutes < 48 * 60) return `${Math.round(minutes / 60)}h ago`;
  return `${Math.round(minutes / 1440)}d ago`;
};

const readSeen = (): string | null => {
  try {
    return localStorage.getItem(SEEN_KEY);
  } catch {
    return null;
  }
};

const markSeen = (date: string) => {
  try {
    localStorage.setItem(SEEN_KEY, date);
  } catch {
    // The badge only returns on the next visit.
  }
};

// The latest English issue of NexTick Daily as a one-line strip. A click opens the
// issue itself in a side drawer.
const NextickBrief: React.FC = () => {
  const [issue, setIssue] = useState<NextickIssue | null>(null);
  const [state, setState] = useState<'loading' | 'ready' | 'error'>('loading');
  const [open, setOpen] = useState(false);
  const [seen, setSeen] = useState<string | null>(readSeen);

  useEffect(() => {
    let alive = true;
    const load = () =>
      fetch(API)
        .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`${r.status}`))))
        .then((p: { issue: NextickIssue | null }) => {
          if (!alive) return;
          setIssue(p.issue);
          setState('ready');
        })
        .catch(() => {
          if (alive) setState((s) => (s === 'ready' ? s : 'error'));
        });
    load();
    const id = window.setInterval(load, REFRESH_MS);
    return () => {
      alive = false;
      window.clearInterval(id);
    };
  }, []);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open]);

  if (!issue) {
    return (
      <div className="tf-brief tf-brief--empty">
        <span className="tf-brief__eyebrow">NexTick Daily</span>
        <span className="tf-brief__status">
          {state === 'loading' ? 'loading…' : state === 'error' ? 'unreachable right now' : 'no English issue yet'}
        </span>
      </div>
    );
  }

  const isNew = seen !== issue.date;
  const ago = fmtAgo(issue.publishedAt);
  const openIssue = () => {
    setOpen(true);
    markSeen(issue.date);
    setSeen(issue.date);
  };

  return (
    <>
      <button type="button" className="tf-brief" onClick={openIssue} title={`Read NexTick Daily for ${issue.date}`}>
        <span className="tf-brief__eyebrow">NexTick Daily</span>
        {isNew ? <span className="tf-brief__new">New</span> : null}
        <span className="tf-brief__date">{fmtIssueDate(issue.date)}</span>
        <span className="tf-brief__headline">{issue.headline}</span>
        <span className="tf-brief__meta">
          {ago ? <span>{ago}</span> : null}
          <span className="tf-brief__cta">Read ›</span>
        </span>
      </button>
      {open ? (
        <div className="tf-brief-drawer" role="dialog" aria-modal="true" aria-label="NexTick Daily issue">
          <div className="tf-brief-drawer__backdrop" onClick={() => setOpen(false)} />
          <div className="tf-brief-drawer__panel">
            <div className="tf-brief-drawer__head">
              <span className="tf-brief__eyebrow">NexTick Daily</span>
              <span className="tf-brief__date">{fmtIssueDate(issue.date)}</span>
              <a className="tf-brief-drawer__link" href={issue.url} target="_blank" rel="noopener noreferrer">
                Open in new tab ↗
              </a>
              <button
                type="button"
                className="tf-brief-drawer__close"
                onClick={() => setOpen(false)}
                aria-label="Close"
              >
                ×
              </button>
            </div>
            <iframe className="tf-brief-drawer__frame" src={issue.url} title={`NexTick Daily, ${issue.date}`} />
          </div>
        </div>
      ) : null}
    </>
  );
};

export default NextickBrief;
