import { useCallback, useEffect, useState } from 'react';

interface CompanyInfo {
  ticker: string;
  shortName: string | null;
  sector: string | null;
  industry: string | null;
  country: string | null;
  website: string | null;
  marketCap: number | null;
  trailingPE: number | null;
  forwardPE: number | null;
  trailingEps: number | null;
  forwardEps: number | null;
  dividendYield: number | null;
  fiftyTwoWeekHigh: number | null;
  fiftyTwoWeekLow: number | null;
  currentPrice: number | null;
  previousClose: number | null;
  changePercent: number | null;
  exchange: string | null;
  beta: number | null;
}

interface EarningsRecord {
  date: string;
  epsEstimate: string;
  epsReported: string;
  surprise: string;
  surprisePercent: string;
}

interface FinancialRow {
  label: string;
  values: Record<string, string | number | null>;
}

interface FinancialStatement {
  ticker: string;
  statement: string;
  period: string;
  columns: string[];
  rows: FinancialRow[];
}

interface ChartPoint {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
}

interface FilingRow {
  accession: string;
  form: string;
  filingDate: string;
  reportDate: string | null;
  primaryDocument: string;
  primaryDocDescription: string | null;
  indexUrl: string;
  documentUrl: string;
}

interface FilingsListResponse {
  ticker: string;
  cik: number;
  forms: string[];
  filings: FilingRow[];
}

interface TocEntry {
  level: number;
  text: string;
  lineIndex: number;
  slug: string;
  charCount: number;
}

interface FilingDocument {
  ticker: string;
  accession: string;
  primaryDocument: string;
  markdown: string;
  toc: TocEntry[];
  charCount: number;
  indexUrl: string;
  documentUrl: string;
}

export type { ChartPoint, CompanyInfo, EarningsRecord, FilingDocument, FilingRow, FilingsListResponse, FinancialRow, FinancialStatement, TocEntry };

export function useCompanyInfo(ticker: string, enabled = true) {
  const [data, setData] = useState<CompanyInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!ticker || !enabled) {
      setData(null);
      setError(null);
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    fetch(`/stock/api/company-info?ticker=${encodeURIComponent(ticker)}`)
      .then((res) => (res.ok ? res.json() : Promise.reject(new Error(`${res.status}`))))
      .then((d) => setData(d))
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [enabled, ticker]);

  return { data, loading, error };
}

export function useEarnings(ticker: string, enabled = true) {
  const [data, setData] = useState<EarningsRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!ticker || !enabled) {
      setData([]);
      setError(null);
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    fetch(`/stock/api/earnings?ticker=${encodeURIComponent(ticker)}`)
      .then((res) => (res.ok ? res.json() : Promise.reject(new Error(`${res.status}`))))
      .then((d) => setData(d.earnings || []))
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [enabled, ticker]);

  return { data, loading, error };
}

export function useFinancials(ticker: string, statement: string, period: string, enabled = true) {
  const [data, setData] = useState<FinancialStatement | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!ticker || !enabled) {
      setData(null);
      setError(null);
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    fetch(
      `/stock/api/financials?ticker=${encodeURIComponent(ticker)}&statement=${statement}&period=${period}`,
    )
      .then((res) => (res.ok ? res.json() : Promise.reject(new Error(`${res.status}`))))
      .then((d) => setData(d))
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [enabled, period, statement, ticker]);

  return { data, loading, error };
}

export function useFilings(ticker: string, enabled = true) {
  const [data, setData] = useState<FilingsListResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!ticker || !enabled) {
      setData(null);
      setError(null);
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    fetch(`/stock/api/filings?ticker=${encodeURIComponent(ticker)}`)
      .then((res) => (res.ok ? res.json() : Promise.reject(new Error(`${res.status}`))))
      .then((d: FilingsListResponse) => setData(d))
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [enabled, ticker]);

  return { data, loading, error };
}

export function useFilingDocument(
  ticker: string,
  accession: string | null,
  primaryDocument: string | null,
  form: string,
  enabled = true,
) {
  const [data, setData] = useState<FilingDocument | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!enabled || !ticker || !accession || !primaryDocument) {
      setData(null);
      setError(null);
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    const qs = new URLSearchParams({ ticker, accession, primaryDocument, form });
    fetch(`/stock/api/filing-document?${qs.toString()}`)
      .then((res) => (res.ok ? res.json() : Promise.reject(new Error(`${res.status}`))))
      .then((d: FilingDocument) => setData(d))
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [accession, enabled, form, primaryDocument, ticker]);

  return { data, loading, error };
}

export function useChartOHLCV(ticker: string) {
  const [data, setData] = useState<ChartPoint[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refetch = useCallback(() => {
    if (!ticker) return;
    setLoading(true);
    setError(null);
    fetch(`/agent/api/market-data?ticker=${encodeURIComponent(ticker)}`)
      .then((res) => (res.ok ? res.json() : Promise.reject(new Error(`${res.status}`))))
      .then((d) => setData(d.data || []))
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [ticker]);

  useEffect(() => { refetch(); }, [refetch]);

  return { data, loading, error };
}
