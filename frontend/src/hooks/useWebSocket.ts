import { useEffect, useRef, useState, useCallback } from "react";
import type { Snapshot } from "../types/api";

type Status = "connecting" | "open" | "closed";

export function useWebSocket() {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [status, setStatus] = useState<Status>("connecting");
  const [progress, setProgress] = useState<{ running: boolean; label?: string; progress?: number }>({ running: false });
  const alertBuffer = useRef<any[]>([]);
  const wsRef = useRef<WebSocket | null>(null);
  const retry = useRef<number>(0);

  const connect = useCallback(() => {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${location.host}/ws`);
    wsRef.current = ws;
    setStatus("connecting");
    ws.onopen = () => { setStatus("open"); retry.current = 0; };
    ws.onmessage = (e) => {
      const msg = JSON.parse(e.data);
      if (msg.type === "hello") { setSnapshot(msg.data.snapshot); }
      else if (msg.type === "snapshot") {
        setSnapshot(msg.data);
        if (msg.data.new_alerts?.length) alertBuffer.current.push(...msg.data.new_alerts);
      } else if (msg.type === "experiment_progress") setProgress({ running: true, ...msg.data });
      else if (msg.type === "experiment_done") setProgress({ running: false });
    };
    ws.onclose = () => {
      setStatus("closed");
      retry.current = Math.min(retry.current + 1, 6);
      setTimeout(connect, 400 * retry.current);
    };
    ws.onerror = () => ws.close();
  }, []);

  useEffect(() => {
    connect();
    return () => wsRef.current?.close();
  }, [connect]);

  const drainAlerts = useCallback(() => {
    const a = alertBuffer.current; alertBuffer.current = []; return a;
  }, []);

  return { snapshot, status, progress, drainAlerts };
}
