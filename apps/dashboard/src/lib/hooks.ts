"use client";

import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Calls `callback` every `intervalMs` while `enabled`. The next tick is scheduled
 * only after the previous callback settles, so slow requests never overlap.
 */
export function usePolling(callback: () => unknown, intervalMs: number, enabled: boolean): void {
  const saved = useRef(callback);
  useEffect(() => {
    saved.current = callback;
  }, [callback]);

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const tick = async () => {
      try {
        await saved.current();
      } catch {
        // Errors are surfaced by the callback's own state; keep polling.
      }
      if (!cancelled) timer = setTimeout(tick, intervalMs);
    };
    timer = setTimeout(tick, intervalMs);
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [enabled, intervalMs]);
}

export interface Resource<T> {
  data: T | undefined;
  error: unknown;
  loading: boolean;
  reload: () => Promise<T | undefined>;
  setData: (data: T) => void;
}

interface ResourceState<T> {
  data: T | undefined;
  error: unknown;
  loading: boolean;
}

/**
 * Loads data with `loader` whenever `key` changes (null = skip). Keeps the last
 * good data when a reload fails so polling views do not flash.
 */
export function useResource<T>(key: string | null, loader: () => Promise<T>): Resource<T> {
  const loaderRef = useRef(loader);
  useEffect(() => {
    loaderRef.current = loader;
  }, [loader]);

  const [state, setState] = useState<ResourceState<T>>({
    data: undefined,
    error: undefined,
    loading: key !== null,
  });

  const reload = useCallback(async () => {
    try {
      const data = await loaderRef.current();
      setState({ data, error: undefined, loading: false });
      return data;
    } catch (error) {
      setState((prev) => ({ data: prev.data, error, loading: false }));
      return undefined;
    }
  }, []);

  useEffect(() => {
    if (key === null) return;
    let active = true;
    loaderRef
      .current()
      .then((data) => {
        if (active) setState({ data, error: undefined, loading: false });
      })
      .catch((error: unknown) => {
        if (active) setState((prev) => ({ data: prev.data, error, loading: false }));
      });
    return () => {
      active = false;
    };
  }, [key]);

  const setData = useCallback((data: T) => setState({ data, error: undefined, loading: false }), []);

  return { ...state, reload, setData };
}
