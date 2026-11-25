"use client";

import { useCallback, useEffect, useRef, useState } from "react";

/** Minimal data hook: load on mount / when deps change, optional polling, manual reload. */
export function useFetch<T>(loader: () => Promise<T>, deps: unknown[], pollMs?: number) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const loaderRef = useRef(loader);
  loaderRef.current = loader;
  const generation = useRef(0); // bumped when deps change, so a slow answer for old deps is ignored

  const reload = useCallback(async () => {
    const started = generation.current;
    const current = () => started === generation.current;
    try {
      const result = await loaderRef.current();
      if (!current()) return;
      setData(result);
      setError(null);
    } catch (e) {
      if (current()) setError(e instanceof Error ? e.message : "Something went wrong");
    } finally {
      if (current()) setLoading(false);
    }
  }, []);

  useEffect(() => {
    generation.current++;
    setLoading(true);
    reload();
    if (!pollMs) return;
    const id = setInterval(reload, pollMs);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, pollMs, reload]);

  return { data, error, loading, reload, setData };
}
