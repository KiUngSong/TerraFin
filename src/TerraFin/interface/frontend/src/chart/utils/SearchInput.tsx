import React, { useCallback, useState } from 'react';
import { chartRequest } from '../api';
import { CHART_API_BASE } from '../constants';
import TickerSearchInput from '../../shared/TickerSearchInput';
import type { ChartHistoryBySeries, ChartUpdate } from '../types';

interface SearchInputProps {
  sessionId: string;
  seriesCount: number;
  maxSeries: number;
  onAdded: (update: ChartUpdate | null, historyBySeries?: ChartHistoryBySeries | null) => void;
  fullWidth?: boolean;
  compact?: boolean;
}

const SearchInput: React.FC<SearchInputProps> = ({
  sessionId,
  seriesCount,
  maxSeries,
  onAdded,
  fullWidth = false,
  compact = false,
}) => {
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);
  const disabled = seriesCount >= maxSeries;

  const addSeries = useCallback(
    (name: string) => {
      if (!name.trim() || loading) return;
      setLoading(true);
      chartRequest(`${CHART_API_BASE}/chart-series/add`, sessionId, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: name.trim() }),
      })
        .then((r) => r.json())
        .then((data) => {
          if (data.ok) {
            setQuery('');
            onAdded(data.mutation ?? null, data.historyBySeries ?? null);
          } else {
            setError(true);
            setTimeout(() => setError(false), 1500);
          }
          setLoading(false);
        })
        .catch(() => {
          setError(true);
          setLoading(false);
          setTimeout(() => setError(false), 1500);
        });
    },
    [loading, onAdded, sessionId],
  );

  return (
    <div
      className={`tf-chart-search${fullWidth ? ' tf-chart-search--full' : ''}`}
      style={{ position: 'relative', ...(compact ? { width: 'clamp(118px, 34vw, 152px)', flexShrink: 0 } : null) }}
    >
      <TickerSearchInput
        value={query}
        onChange={setQuery}
        onSelect={(hit) => addSeries(hit.symbol)}
        onSubmit={() => addSeries(query)}
        placeholder={disabled ? `Max ${maxSeries} charts` : 'Search ticker or company'}
        ariaLabel="Add chart series"
        disabled={disabled || loading}
        inputStyle={{
          width: '100%',
          height: 28,
          border: `1px solid ${error ? '#ef5350' : '#e0e0e0'}`,
          borderRadius: 6,
          padding: '0 12px',
          fontSize: 12,
          color: '#333',
          background: disabled ? '#f5f5f5' : '#fff',
          outline: 'none',
          boxSizing: 'border-box',
        }}
      />
    </div>
  );
};

export default SearchInput;
