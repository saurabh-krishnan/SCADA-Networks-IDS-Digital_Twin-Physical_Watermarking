import { useEffect, useRef, useState } from "react";
import { api } from "../services/api";

export function useChartData(keys: string[], intervalMs = 1000, points = 400) {
  const [data, setData] = useState<any[]>([]);
  const keyStr = keys.join(",");
  const keysRef = useRef(keys);
  keysRef.current = keys;

  useEffect(() => {
    let alive = true;
    const load = async () => {
      try {
        const r = await api.charts(keysRef.current, points);
        if (!alive) return;
        const rows = (r.t as number[]).map((t, i) => {
          const row: any = { t };
          for (const k of keysRef.current) row[k] = r.series[k]?.[i] ?? null;
          return row;
        });
        setData(rows);
      } catch { /* ignore transient */ }
    };
    load();
    const id = setInterval(load, intervalMs);
    return () => { alive = false; clearInterval(id); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [keyStr, intervalMs, points]);

  return data;
}
