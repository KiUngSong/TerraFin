import React, { useEffect, useRef, useState } from 'react';

interface DashboardHeaderProps {
  searchValue: string;
  onSearchChange: (value: string) => void;
  onSearchSubmit?: (query: string) => void;
  sectionLabel?: string;
  title?: string;
  placeholder?: string;
  rightContent?: React.ReactNode;
}

const defaultSearchSubmit = (query: string) => {
  const trimmed = query.trim();
  if (!trimmed) return;
  fetch(`/resolve-ticker?q=${encodeURIComponent(trimmed)}`)
    .then((res) => (res.ok ? res.json() : Promise.reject(new Error(`${res.status}`))))
    .then((d: { path: string }) => { window.location.href = d.path; })
    .catch(() => { window.location.href = `/stock/${trimmed.toUpperCase()}`; });
};

const DashboardHeader: React.FC<DashboardHeaderProps> = ({
  searchValue,
  onSearchChange,
  onSearchSubmit = defaultSearchSubmit,
  sectionLabel = 'Dashboard',
  title = 'TerraFin',
  placeholder = 'Search ticker, index, or indicator',
  rightContent = null,
}) => {
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [showSuggestions, setShowSuggestions] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const path = window.location.pathname;
  const links = [
    { href: '/dashboard', label: 'Market Overview', isActive: path.startsWith('/dashboard') },
    { href: '/market-insights', label: 'Market Insights', isActive: path.startsWith('/market-insights') },
    { href: '/calendar', label: 'Event Calendar', isActive: path.startsWith('/calendar') },
    { href: '/stock/', label: 'Stock Analysis', isActive: path.startsWith('/stock') },
    { href: '/watchlist', label: 'Watchlist', isActive: path.startsWith('/watchlist') },
  ];

  useEffect(() => {
    if (!showSuggestions) return;
    const handleClickOutside = (event: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setShowSuggestions(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [showSuggestions]);

  useEffect(() => {
    if (debounceRef.current) {
      clearTimeout(debounceRef.current);
      debounceRef.current = null;
    }

    const query = searchValue.trim();
    if (!query) {
      setSuggestions([]);
      setShowSuggestions(false);
      return;
    }

    debounceRef.current = setTimeout(() => {
      fetch(`/chart/api/chart-series/search?q=${encodeURIComponent(query)}`)
        .then((response) => (response.ok ? response.json() : Promise.reject(new Error(`${response.status}`))))
        .then((payload: { suggestions?: string[] }) => {
          const nextSuggestions = payload.suggestions || [];
          setSuggestions(nextSuggestions);
          setShowSuggestions(nextSuggestions.length > 0);
        })
        .catch(() => {
          setSuggestions([]);
          setShowSuggestions(false);
        });
    }, 200);

    return () => {
      if (debounceRef.current) {
        clearTimeout(debounceRef.current);
        debounceRef.current = null;
      }
    };
  }, [searchValue]);

  const submitSearch = (value: string) => {
    setShowSuggestions(false);
    onSearchSubmit(value);
  };

  return (
    <header className="tf-dashboard-header">
      <div className="tf-dashboard-header__main">
        <div className="tf-dashboard-header__brand-nav">
          <a
            href="/dashboard"
            style={{
              textDecoration: 'none',
              color: 'inherit',
              minWidth: 0,
            }}
            aria-label="Go to dashboard homepage"
          >
            <div style={{ fontSize: 11, color: '#64748b', textTransform: 'uppercase', letterSpacing: 0.8 }}>{sectionLabel}</div>
            <div style={{ fontSize: 18, fontWeight: 700, color: '#0f172a' }}>{title}</div>
          </a>

          <nav
            aria-label="Primary navigation"
            className="tf-dashboard-header__nav"
          >
            <div className="tf-dashboard-header__nav-scroll">
              {links.map((link) => (
                <a
                  key={link.href}
                  href={link.href}
                  style={{
                    textDecoration: 'none',
                    padding: '6px 10px',
                    borderRadius: 8,
                    border: link.isActive ? '1px solid #cbd5e1' : '1px solid transparent',
                    background: link.isActive ? '#ffffff' : 'transparent',
                    color: link.isActive ? '#0f172a' : '#475569',
                    fontSize: 12,
                    fontWeight: 600,
                    whiteSpace: 'nowrap',
                    flexShrink: 0,
                  }}
                  aria-current={link.isActive ? 'page' : undefined}
                >
                  {link.label}
                </a>
              ))}
            </div>
          </nav>
        </div>

        <div ref={containerRef} className="tf-dashboard-header__search">
          <input
            type="search"
            placeholder={placeholder}
            aria-label={placeholder}
            value={searchValue}
            onChange={(event) => onSearchChange(event.target.value)}
            onFocus={() => {
              if (suggestions.length > 0) {
                setShowSuggestions(true);
              }
            }}
            onKeyDown={(event) => {
              if (event.key === 'Enter') {
                event.preventDefault();
                submitSearch(searchValue);
              }
            }}
            style={{
              width: '100%',
              height: 40,
              border: '1px solid #cbd5e1',
              borderRadius: 999,
              padding: '0 16px',
              outline: 'none',
              fontSize: 14,
              color: '#1e293b',
              background: '#fff',
              boxSizing: 'border-box',
            }}
          />
          {showSuggestions && suggestions.length > 0 ? (
            <div
              style={{
                position: 'absolute',
                top: 'calc(100% + 6px)',
                left: 0,
                right: 0,
                background: '#ffffff',
                border: '1px solid #e2e8f0',
                borderRadius: 12,
                boxShadow: '0 12px 24px rgba(15, 23, 42, 0.12)',
                overflow: 'hidden',
                zIndex: 20,
              }}
            >
              {suggestions.map((suggestion) => (
                <button
                  key={suggestion}
                  type="button"
                  onMouseDown={(event) => event.preventDefault()}
                  onClick={() => {
                    onSearchChange(suggestion);
                    submitSearch(suggestion);
                  }}
                  style={{
                    display: 'block',
                    width: '100%',
                    border: 'none',
                    background: 'transparent',
                    textAlign: 'left',
                    padding: '10px 14px',
                    fontSize: 13,
                    color: '#0f172a',
                    cursor: 'pointer',
                  }}
                  onMouseEnter={(event) => {
                    event.currentTarget.style.background = '#f8fafc';
                  }}
                  onMouseLeave={(event) => {
                    event.currentTarget.style.background = 'transparent';
                  }}
                >
                  {suggestion}
                </button>
              ))}
            </div>
          ) : null}
        </div>
        {rightContent ? <div className="tf-dashboard-header__right">{rightContent}</div> : null}
      </div>
    </header>
  );
};

export default DashboardHeader;
