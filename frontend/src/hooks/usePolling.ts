import { useEffect, useRef, useState, useCallback } from "react";

export function usePolling<T>(fn: () => Promise<T>, intervalMs: number, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const fnRef = useRef(fn);
  fnRef.current = fn;

  const refresh = useCallback(async () => {
    try { setData(await fnRef.current()); setError(null); }
    catch (e) { setError((e as Error).message); }
  }, []);

  useEffect(() => {
    let alive = true;
    const tick = async () => { if (alive) await refresh(); };
    tick();
    const id = setInterval(tick, intervalMs);
    return () => { alive = false; clearInterval(id); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [intervalMs, ...deps]);

  return { data, error, refresh };
}
