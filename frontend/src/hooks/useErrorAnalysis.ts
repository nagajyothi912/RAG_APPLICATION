import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  getAnalysisSummary,
  getTrace,
  listTraces,
  type AnalysisSummary,
  type TraceDetail,
  type TraceFilters,
  type TraceRow,
} from '../services/api';

const PAGE = 50;

/**
 * State for the Error Analysis tab.
 *
 * The trace list is fetched server-side rather than loaded whole and filtered in
 * the browser: the committed run is 1.4 MB of JSON, and the live file grows
 * without bound. Filtering where the data already lives keeps the tab usable
 * when someone points it at a week of real traffic.
 */
export function useErrorAnalysis(active: boolean) {
  const [summary, setSummary] = useState<AnalysisSummary | null>(null);
  const [rows, setRows] = useState<TraceRow[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [filters, setFilters] = useState<TraceFilters>({ source: 'analysis' });
  const [selected, setSelected] = useState<TraceDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);

  // Guards against an older in-flight response overwriting a newer one when
  // filters change faster than the network answers.
  const requestId = useRef(0);

  const source = filters.source || 'analysis';

  const refreshSummary = useCallback(async () => {
    try {
      setSummary(await getAnalysisSummary(source));
      setError(null);
    } catch (err: unknown) {
      setSummary(null);
      setError(err instanceof Error ? err.message : 'Could not load the analysis summary.');
    }
  }, [source]);

  const fetchRows = useCallback(
    async (nextOffset: number) => {
      const id = ++requestId.current;
      setLoading(true);
      try {
        const data = await listTraces({ ...filters, offset: nextOffset, limit: PAGE });
        if (id !== requestId.current) return;
        setRows(data.rows);
        setTotal(data.total);
        setOffset(data.offset);
        setError(null);
      } catch (err: unknown) {
        if (id !== requestId.current) return;
        setError(err instanceof Error ? err.message : 'Could not load traces.');
        setRows([]);
        setTotal(0);
      } finally {
        if (id === requestId.current) setLoading(false);
      }
    },
    [filters],
  );

  // Nothing is fetched until the tab is opened, so the chat page pays nothing
  // for a feature most sessions never use.
  useEffect(() => {
    if (!active) return;
    void refreshSummary();
    void fetchRows(0);
    setLoaded(true);
  }, [active, refreshSummary, fetchRows]);

  const open = useCallback(
    async (traceId: string) => {
      setDetailLoading(true);
      try {
        setSelected(await getTrace(traceId, source));
      } catch (err: unknown) {
        setError(err instanceof Error ? err.message : `Could not load ${traceId}.`);
      } finally {
        setDetailLoading(false);
      }
    },
    [source],
  );

  const update = useCallback((patch: Partial<TraceFilters>) => {
    setFilters((prev) => {
      const next = { ...prev, ...patch };
      // Empty string means "no filter", so the query string stays clean.
      Object.keys(next).forEach((key) => {
        const value = (next as Record<string, unknown>)[key];
        if (value === '' || value === undefined) delete (next as Record<string, unknown>)[key];
      });
      return next;
    });
  }, []);

  const activeFilterCount = useMemo(
    () =>
      Object.entries(filters).filter(
        ([key, value]) => key !== 'source' && value !== undefined && value !== '',
      ).length,
    [filters],
  );

  return {
    summary,
    rows,
    total,
    offset,
    page: PAGE,
    filters,
    activeFilterCount,
    selected,
    loading,
    detailLoading,
    error,
    loaded,
    setFilters: update,
    clearFilters: () => setFilters({ source }),
    reload: () => fetchRows(offset),
    goto: (next: number) => void fetchRows(Math.max(0, next)),
    open,
    close: () => setSelected(null),
  };
}
