import { useEffect, useState } from "react";
import { usePolling } from "../hooks/usePolling";
import { api } from "../services/api";
import { useApp } from "../App";
import { Panel, Badge, Empty } from "../components/ui";
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend, Cell } from "recharts";
import type { ExperimentResult, Metrics } from "../types/api";

const CONFIG_LABEL: Record<string, string> = {
  network_only: "Network IDS only", network_process: "Network + Process",
  network_process_twin: "Network + Process + Twin", full: "Full stack + watermark",
};

export function Experiments() {
  const { meta } = useApp();
  const { data: list, refresh } = usePolling<any>(api.experiments, 3000);
  const [scenario, setScenario] = useState<string>("false_data_injection");
  const [wm, setWm] = useState(true);
  const [dur, setDur] = useState(210);
  const [result, setResult] = useState<ExperimentResult | null>(null);
  const [running, setRunning] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const scenarios = meta?.scenarios ?? [];

  const run = async () => {
    setRunning(true); setErr(null);
    try {
      const r = await api.runExperiment({
        scenario: scenario === "none" ? null : scenario, watermark: wm, duration: dur,
        attack_at: Math.round(dur * 0.3), attack_stop: Math.round(dur * 0.72), response_mode: "monitor",
        label: `${scenario === "none" ? "normal" : scenario}${wm ? " +wm" : ""}`,
      });
      setResult(r as ExperimentResult); await refresh();
    } catch (e) { setErr((e as Error).message); } finally { setRunning(false); }
  };

  const load = async (id: string) => { setResult(await api.experiment(id) as ExperimentResult); };

  const chartData = result ? Object.entries(result.by_detector_config).map(([k, m]: [string, Metrics]) => ({
    name: CONFIG_LABEL[k] ?? k, precision: m.precision, recall: m.recall, f1: m.f1, detected: m.detected,
  })) : [];

  return (
    <div className="grid grid-cols-12 gap-4">
      <Panel title="Run experiment" className="col-span-12 lg:col-span-4">
        <div className="space-y-2 text-xs">
          <label className="block">
            <span className="text-[var(--muted)]">Scenario</span>
            <select className="w-full mt-1" value={scenario} onChange={(e) => setScenario(e.target.value)}>
              <option value="none">Normal operation (no attack)</option>
              {scenarios.map((s: any) => <option key={s.key} value={s.key}>{s.name}</option>)}
            </select>
          </label>
          <label className="flex items-center gap-2">
            <input type="checkbox" checked={wm} onChange={(e) => setWm(e.target.checked)} />
            <span>Watermarking enabled</span>
          </label>
          <label className="block">
            <span className="text-[var(--muted)]">Duration: {dur}s (attack {Math.round(dur*0.3)}–{Math.round(dur*0.72)}s)</span>
            <input type="range" min={120} max={360} step={30} value={dur} onChange={(e) => setDur(Number(e.target.value))} className="w-full" />
          </label>
          <button className="btn btn-accent w-full justify-center" disabled={running} onClick={run}>
            {running ? "Running (deterministic, seeded)…" : "Run experiment"}
          </button>
          {err && <div className="text-red-400">{err}</div>}
          <p className="text-[10px] text-[var(--muted)] leading-relaxed pt-1">
            Runs a fresh headless engine through a scripted timeline and scores the <i>same</i> recorded trace under
            each detector configuration, so the comparison is apples-to-apples. Results are deterministic for a seed.
          </p>
        </div>

        <div className="mt-3">
          <div className="card-title mb-1">Saved runs</div>
          <div className="space-y-1 max-h-[200px] overflow-auto">
            {(list?.experiments ?? []).map((e: any) => (
              <div key={e.run_id} onClick={() => load(e.run_id)}
                className="panel p-1.5 cursor-pointer text-[11px] hover:border-orange-600" style={{ background: "var(--panel2)" }}>
                <div className="flex items-center justify-between">
                  <span className="font-medium">{e.label}</span>
                  <Badge tone={e.metrics?.overall?.detected ? "danger" : "ok"}>
                    {e.metrics?.overall?.detected ? "detected" : "clean"}
                  </Badge>
                </div>
                <div className="text-[var(--muted)] mono">{e.run_id}</div>
              </div>
            ))}
            {!list?.experiments?.length && <Empty>No saved runs yet.</Empty>}
          </div>
        </div>
      </Panel>

      <div className="col-span-12 lg:col-span-8 flex flex-col gap-4">
        {result ? (
          <>
            <Panel title={`Result — ${result.label}`}
              right={<div className="flex gap-2">
                <Badge tone="info">{result.samples} samples</Badge>
                <Badge>{result.wall_time_s}s wall</Badge>
              </div>}>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-2 mb-3">
                <Mini label="Scenario" value={result.scenario ?? "normal"} />
                <Mini label="Watermark" value={result.watermark ? "on" : "off"} />
                <Mini label="Attack window" value={`${result.attack_window[0]}–${result.attack_window[1]}s`} />
                <Mini label="Responses" value={String(result.responses.length)} />
              </div>
              <ResponsiveContainer width="100%" height={240}>
                <BarChart data={chartData} margin={{ top: 8, right: 10, left: -10, bottom: 4 }}>
                  <CartesianGrid stroke="#3a3a40" strokeDasharray="2 4" />
                  <XAxis dataKey="name" stroke="#71717a" tick={{ fontSize: 9 }} interval={0} angle={-8} textAnchor="end" height={50} />
                  <YAxis stroke="#71717a" tick={{ fontSize: 10 }} domain={[0, 1]} />
                  <Tooltip contentStyle={{ background: "#202023", border: "1px solid #3a3a40", borderRadius: 8, fontSize: 12 }} />
                  <Legend wrapperStyle={{ fontSize: 11 }} />
                  <Bar dataKey="precision" fill="#38bdf8" radius={[3, 3, 0, 0]} />
                  <Bar dataKey="recall" fill="#34d399" radius={[3, 3, 0, 0]} />
                  <Bar dataKey="f1" fill="#fbbf24" radius={[3, 3, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </Panel>

            <Panel title="Detection-configuration comparison (A–F matrix)">
              <div className="overflow-auto">
                <table className="text-xs">
                  <thead className="text-[var(--muted)]"><tr className="text-left">
                    <th className="p-1.5">Configuration</th><th>Detected</th><th>TP</th><th>FP</th><th>FN</th>
                    <th>Precision</th><th>Recall</th><th>F1</th><th>Latency</th>
                  </tr></thead>
                  <tbody>
                    {Object.entries(result.by_detector_config).map(([k, m]: [string, Metrics]) => (
                      <tr key={k} className="border-t border-[var(--border)]">
                        <td className="p-1.5">{CONFIG_LABEL[k] ?? k}</td>
                        <td><Badge tone={m.detected ? "danger" : "ok"}>{m.detected ? "yes" : "no"}</Badge></td>
                        <td className="tnum">{m.tp}</td><td className="tnum">{m.fp}</td><td className="tnum">{m.fn}</td>
                        <td className="tnum">{m.precision.toFixed(2)}</td>
                        <td className="tnum">{m.recall.toFixed(2)}</td>
                        <td className="tnum font-semibold">{m.f1.toFixed(2)}</td>
                        <td className="tnum">{m.detection_latency_s != null ? `${m.detection_latency_s}s` : "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-2 mt-3 text-xs">
                <Mini label="Process dev. RMS" value={result.overall.process_deviation_rms.toFixed(3)} />
                <Mini label="Process dev. max" value={result.overall.process_deviation_max.toFixed(3)} />
                <Mini label="Recovery time" value={result.overall.recovery_time_s != null ? `${result.overall.recovery_time_s}s` : "—"} />
                <Mini label="Attack windows" value={String(result.overall.attack_windows)} />
              </div>
            </Panel>
          </>
        ) : (
          <Panel title="Results"><Empty>Run an experiment or open a saved run to see the comparison.</Empty></Panel>
        )}
      </div>
    </div>
  );
}

function Mini({ label, value }: { label: string; value: string }) {
  return (
    <div className="panel p-2" style={{ background: "var(--panel2)" }}>
      <div className="text-[10px] text-[var(--muted)] uppercase tracking-wide">{label}</div>
      <div className="text-sm font-semibold mt-0.5">{value}</div>
    </div>
  );
}
