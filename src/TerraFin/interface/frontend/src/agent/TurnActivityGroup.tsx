import React, { useReducer } from 'react';
import { formatInputs, TurnActivity } from './turnActivity';

const RAW_CHAR_LIMIT = 4000;

const prettyJson = (raw: string) => {
  try {
    return JSON.stringify(JSON.parse(raw), null, 2);
  } catch {
    return raw;
  }
};

type TurnActivityGroupProps = {
  turn: TurnActivity;
  summary: string;
  live?: boolean;
  // Owned by the widget, so a poll that remounts this row keeps it open.
  openKeys: Set<string>;
};

export const TurnActivityGroup: React.FC<TurnActivityGroupProps> = ({ turn, summary, live, openKeys }) => {
  const [, rerender] = useReducer((count: number) => count + 1, 0);
  const toggle = (key: string) => {
    if (openKeys.has(key)) {
      openKeys.delete(key);
    } else {
      openKeys.add(key);
    }
    rerender();
  };
  const groupKey = `turn:${turn.key}`;
  const open = openKeys.has(groupKey);
  const failed = turn.calls.filter((call) => call.isError);
  return (
    <div className={`tf-agent-turn${live ? ' tf-agent-turn--live' : ''}`}>
      <button
        type="button"
        className="tf-agent-turn__toggle"
        onClick={() => toggle(groupKey)}
        aria-expanded={open}
      >
        {live ? <span className="tf-agent-message__status-spinner" aria-hidden="true" /> : null}
        <span>{summary}</span>
      </button>
      {!open
        ? failed.map((call) => (
            <div key={call.callId} className="tf-agent-turn__detail">
              <span className="tf-agent-task-badge tf-agent-task-badge--failed">FAILED</span> {call.label}
              {call.errorLine ? `: ${call.errorLine}` : ''}
            </div>
          ))
        : null}
      {open ? (
        <ul className="tf-agent-turn__calls">
          {turn.calls.map((call) => {
            const rawKey = `raw:${call.callId}`;
            const rawOpen = openKeys.has(rawKey);
            const inputs = formatInputs(call.inputs);
            const raw = rawOpen ? prettyJson(call.raw) : '';
            return (
              <li key={call.callId} className="tf-agent-turn__call">
                <div className="tf-agent-turn__call-head">
                  <span className="tf-agent-task-card__label">{call.label}</span>
                  {call.isError ? <span className="tf-agent-task-badge tf-agent-task-badge--failed">FAILED</span> : null}
                  <button
                    type="button"
                    className="tf-agent-turn__raw-toggle"
                    onClick={() => toggle(rawKey)}
                    aria-expanded={rawOpen}
                    aria-label={`${rawOpen ? 'Hide raw' : 'Raw'} output of ${call.label}`}
                  >
                    {rawOpen ? 'Hide raw' : 'Raw'}
                  </button>
                </div>
                {call.errorLine ? <div className="tf-agent-turn__detail">{call.errorLine}</div> : null}
                {inputs.length > 0 ? <div className="tf-agent-turn__detail">{inputs.join(' · ')}</div> : null}
                {call.outputKeys.length > 0 ? (
                  <div className="tf-agent-turn__detail">Returned {call.outputKeys.join(', ')}</div>
                ) : null}
                {rawOpen ? (
                  <>
                    <pre className="tf-agent-turn__raw">{raw.slice(0, RAW_CHAR_LIMIT)}</pre>
                    {raw.length > RAW_CHAR_LIMIT ? (
                      <div className="tf-agent-turn__detail">
                        Showing {RAW_CHAR_LIMIT.toLocaleString('en-US')} of {raw.length.toLocaleString('en-US')} chars
                      </div>
                    ) : null}
                  </>
                ) : null}
              </li>
            );
          })}
        </ul>
      ) : null}
    </div>
  );
};

type TurnFooterProps = {
  text: string;
  sources: Array<{ artifactId: string; title: string; kind: string }>;
};

export const TurnFooter: React.FC<TurnFooterProps> = ({ text, sources }) => (
  <div className="tf-agent-turn__footer">
    <span>{text}</span>
    {sources.length > 0 ? (
      <span className="tf-agent-turn__sources">
        Sources: {sources.map((source) => `${source.title} (${source.kind})`).join(', ')}
      </span>
    ) : null}
  </div>
);
