import React from 'react';

/**
 * Magnitude-scaled signed delta.
 *
 * `value` is a fraction by default (e.g. 0.0123 → +1.23%). The visual weight
 * jumps with magnitude so the eye picks up large moves without reading the
 * number — this is the Bloomberg-DNA substance.
 *
 * Thresholds (abs(value)):
 *   < 0.001 (0.1%)   → 11px / 300
 *   < 0.01  (1%)     → 12px / 400
 *   < 0.05  (5%)     → 14px / 500
 *   < 0.10  (10%)    → 16px / 600
 *   ≥ 0.10           → 18px / 700
 *
 * Sign is always rendered: `+` or U+2212 minus (`−`). Tabular-nums keeps
 * columns aligned in tables/rows.
 *
 * `mode="bp"` renders basis points (yields / FRED), where `value` is
 * interpreted in basis points directly (no ×100).
 */

export type SignedDeltaMode = 'pct' | 'bp' | 'raw';

interface SignedDeltaProps {
  value: number;
  mode?: SignedDeltaMode;
  className?: string;
}

const MINUS = '−'; // U+2212 MINUS SIGN

function pickSize(abs: number): 'xs' | 'sm' | 'md' | 'lg' | 'xl' {
  if (abs < 0.001) return 'xs';
  if (abs < 0.01) return 'sm';
  if (abs < 0.05) return 'md';
  if (abs < 0.1) return 'lg';
  return 'xl';
}

function pickTone(value: number): 'up' | 'down' | 'zero' {
  if (value > 0) return 'up';
  if (value < 0) return 'down';
  return 'zero';
}

function format(value: number, mode: SignedDeltaMode): string {
  if (!Number.isFinite(value)) return '—';
  if (mode === 'bp') {
    const sign = value >= 0 ? '+' : MINUS;
    return `${sign}${Math.abs(value).toFixed(0)}bp`;
  }
  if (mode === 'raw') {
    const sign = value >= 0 ? '+' : MINUS;
    return `${sign}${Math.abs(value).toFixed(2)}`;
  }
  // pct (default) — value is a fraction
  const pct = value * 100;
  const absPct = Math.abs(pct);
  const decimals = absPct >= 100 ? 1 : 2;
  const sign = value >= 0 ? '+' : MINUS;
  return `${sign}${absPct.toFixed(decimals)}%`;
}

const SignedDelta: React.FC<SignedDeltaProps> = ({
  value,
  mode = 'pct',
  className = '',
}) => {
  // Magnitude-scaling caused column heights to vary; rows became uneven.
  // Single consistent size per the user feedback — keep tone color only.
  void pickSize;
  const tone = pickTone(value);
  const cls = ['tf-delta', `tf-delta--${tone}`, className].filter(Boolean).join(' ');
  return <span className={cls}>{format(value, mode)}</span>;
};

export default SignedDelta;
