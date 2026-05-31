import React, { useState } from 'react';
import TickerSearchInput from '../shared/TickerSearchInput';
import { resolveAndGo } from '../shared/resolveTicker';
import ReportBell from './ReportBell';
import { useTerminalStore } from './store';

interface NavLink {
  code: string;
  label: string;
  path: string;
}

const NAV: NavLink[] = [
  { code: 'Terminal', label: 'Terminal', path: '/terminal' },
  { code: 'Analysis', label: 'Stock Analysis', path: '/stock' },
  { code: 'Insights', label: 'Market Insights', path: '/market-insights' },
  { code: 'Watchlist', label: 'Watchlist', path: '/watchlist' },
  { code: 'Calendar', label: 'Calendar', path: '/calendar' },
];

const sectionForPath = (path: string): NavLink => {
  if (path.startsWith('/stock')) return NAV[1];
  if (path.startsWith('/market-insights')) return NAV[2];
  if (path.startsWith('/watchlist')) return NAV[3];
  if (path.startsWith('/calendar')) return NAV[4];
  return NAV[0];
};

const FunctionBar: React.FC = () => {
  const theme = useTerminalStore((s) => s.theme);
  const toggleTheme = useTerminalStore((s) => s.toggleTheme);
  const [searchValue, setSearchValue] = useState('');
  const section = sectionForPath(window.location.pathname);

  return (
    <div className="tf-funcbar" role="navigation" aria-label="Terminal function bar">
      <div className="tf-funcbar__brand-row">
        <span className="tf-funcbar__brand">TERRAFIN</span>
        <span className="tf-funcbar__brand-spacer" />
        <button
          type="button"
          className="tf-funcbar__kbutton tf-funcbar__kbutton--theme"
          onClick={() => toggleTheme()}
          title={`switch to ${theme === 'dark' ? 'light' : 'dark'} mode`}
          aria-label="toggle theme"
        >
          {theme === 'dark' ? (
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
              <circle cx="12" cy="12" r="4" />
              <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41" strokeLinecap="round" />
            </svg>
          ) : (
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
              <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" strokeLinejoin="round" />
            </svg>
          )}
        </button>
        <ReportBell />
        <a
          className="tf-funcbar__kbutton"
          href="https://github.com/KiUngSong/TerraFin"
          target="_blank"
          rel="noopener noreferrer"
          aria-label="GitHub repository"
          title="GitHub repository"
        >
          <svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor" aria-hidden>
            <path d="M12 .297a12 12 0 0 0-3.79 23.39c.6.11.82-.26.82-.58 0-.29-.01-1.04-.02-2.04-3.34.73-4.04-1.61-4.04-1.61-.55-1.39-1.34-1.76-1.34-1.76-1.09-.74.08-.73.08-.73 1.21.09 1.84 1.24 1.84 1.24 1.07 1.84 2.81 1.31 3.5 1 .11-.78.42-1.31.76-1.61-2.66-.3-5.47-1.33-5.47-5.93 0-1.31.47-2.38 1.24-3.22-.13-.3-.54-1.52.12-3.18 0 0 1.01-.32 3.3 1.23a11.5 11.5 0 0 1 6 0c2.29-1.55 3.3-1.23 3.3-1.23.66 1.66.25 2.88.12 3.18.77.84 1.24 1.91 1.24 3.22 0 4.61-2.81 5.62-5.49 5.92.43.37.81 1.1.81 2.22 0 1.61-.01 2.91-.01 3.3 0 .32.22.7.83.58A12 12 0 0 0 12 .297z" />
          </svg>
        </a>
        <a
          className="tf-funcbar__kbutton"
          href="https://kiungsong.github.io/TerraFin/"
          target="_blank"
          rel="noopener noreferrer"
          aria-label="Documentation"
          title="Documentation"
        >
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
            <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" />
            <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" />
            <path d="M8 7h8M8 11h8M8 15h6" />
          </svg>
        </a>
      </div>
      <div className="tf-funcbar__nav">
        {NAV.map((m) => {
          const active = m.code === section.code;
          return (
            <a
              key={m.code}
              href={m.path}
              className={`tf-funcbar__nav-item${active ? ' tf-funcbar__nav-item--active' : ''}`}
              title={m.label}
            >
              {m.code}
            </a>
          );
        })}
      </div>
      <div className="tf-funcbar__search">
        <TickerSearchInput
          value={searchValue}
          onChange={setSearchValue}
          onSelect={(hit) => resolveAndGo(hit.symbol)}
          onSubmit={() => resolveAndGo(searchValue)}
          placeholder="Search ticker or company"
          ariaLabel="Search ticker or company"
          inputStyle={{
            width: '100%',
            height: 32,
            border: '1px solid var(--tf-border-strong)',
            borderRadius: 'var(--tf-radius)',
            padding: '0 12px',
            outline: 'none',
            fontFamily: 'var(--tf-mono)',
            fontSize: 'var(--tf-header-search-font, 13px)',
            color: 'var(--tf-text)',
            background: 'var(--tf-bg)',
            boxSizing: 'border-box',
          }}
        />
      </div>
    </div>
  );
};

export default FunctionBar;
