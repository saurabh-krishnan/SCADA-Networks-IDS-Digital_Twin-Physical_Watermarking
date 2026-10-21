import { useState } from "react";
import { usePolling } from "../hooks/usePolling";
import { api } from "../services/api";
import { Panel, Stat, Badge, Empty } from "../components/ui";
import { TimeSeries } from "../charts/TimeSeries";
import type { WatermarkState } from "../types/api";

const DECISION_TONE: Record<string, string> = {
  consistent: "ok", suspicious: "danger", inconclusive: "warn", inactive: "default",
};

export function Watermarking() {
  const { data: wm, refresh } = usePolling<WatermarkState>(api.watermark, 700);
  const [amp, setAmp] = useState(1.5);
  const [busy, setBusy] = useState(false);

  const act = async (fn: () => Promise<unknown>) => {
    setBusy(true); try { await fn(); await refresh(); } finally { setBusy(false); }
  };

  const hist = (wm?.history ?? []).map((h) => ({ ...h }));
  const channels = wm?.channels ?? {};

  return (
    <div className="grid grid-cols-12 gap-4">
      <div className="col-span-12 flex items-center gap-3 flex-wrap">
        {wm?.enabled ? (
          <button className="btn btn-danger" disabled={busy} onClick={() => act(api.wmDisable)}>Disable watermark</button>
        ) : (
          <button className="btn btn-ok" disabled={busy} onClick={() => act(api.wmEnable)}>Enable watermark</button>
        )}
        <div className="flex items-center gap-2 text-xs">
          <span className="text-[var(--muted)]">amplitude</span>
          <input type="range" min={0.3} max={3} step={0.1} value={amp} onChange={(e) => setAmp(Number(e.target.value))} />
          <span className="tnum w-8">{amp.toFixed(1)}%</span>
          <button className="btn" disabled={busy} onClick={() => act(() => api.wmConfig({ amplitude: amp }))}>Apply</button>
        </div>
        <div className="ml-auto flex items-center gap-2">
          <span className="text-xs text-[var(--muted)]">decision</span>
          <Badge tone={DECISION_TONE[wm?.decision ?? "inactive"]}>{(wm?.decision ?? "inactive").toUpperCase()}</Badge>
          {wm?.alarm && <Badge tone="danger">ALARM · streak {wm.streak}</Badge>}
        </div>
      </div>

      <div className="col-span-12 grid grid-cols-2 md:grid-cols-4 gap-3">
        <Stat label="Status" value={<span className="text-base">{wm?.enabled ? (wm.injecting ? "injecting" : "suspended") : "disabled"}</span>}
          color={wm?.injecting ? "var(--ok)" : "var(--muted)"}
          sub={wm?.suspended_reason ?? (wm?.calibrating ? "calibrating…" : undefined)} />
        <Stat label="Current offset" value={(wm?.current_offset ?? 0).toFixed(3)} unit="% cmd"
          sub={`target ${wm?.config?.target ?? "—"}`} />
        <Stat label="Flow correlation ρ" value={(channels["FT-101"]?.rho ?? 0).toFixed(3)}
          color={corColor(channels["FT-101"]?.rho)} sub={`gain ${channels["FT-101"]?.gain_ratio?.toFixed(2) ?? "—"}`} />
        <Stat label="Pressure correlation ρ" value={(channels["PT-101"]?.rho ?? 0).toFixed(3)}
          color={corColor(channels["PT-101"]?.rho)} sub={`gain ${channels["PT-101"]?.gain_ratio?.toFixed(2) ?? "—"}`} />
      </div>

      <Panel title="Watermark injection signal (actuator command offset)" className="col-span-12 lg:col-span-6">
        {hist.length ? <TimeSeries data={hist} height={160} series={[
          { key: "offset", label: "injected offset (%)", color: "#fbbf24" },
        ]} refLines={[{ y: 0, color: "#334155" }]} /> : <Empty>Enable the watermark to see the signal.</Empty>}
      </Panel>

      <Panel title="Expected vs observed response (flow, high-pass)" className="col-span-12 lg:col-span-6">
        {hist.length ? <TimeSeries data={hist} height={160} series={[
          { key: "e_flow", label: "expected (twin)", color: "#f59e0b", dash: "5 3" },
          { key: "o_flow", label: "observed", color: "#38bdf8" },
        ]} /> : <Empty>No data yet.</Empty>}
      </Panel>

      <Panel title="Detection decision per channel" className="col-span-12 lg:col-span-7">
        <div className="overflow-auto">
          <table className="text-xs">
            <thead className="text-[var(--muted)]"><tr className="text-left">
              <th className="p-1.5">Channel</th><th>ρ</th><th>gain ratio</th><th>SNR</th><th>valid</th><th>decision</th><th>reason</th>
            </tr></thead>
            <tbody>
              {Object.entries(channels).map(([k, c]: any) => (
                <tr key={k} className="border-t border-[var(--border)]">
                  <td className="p-1.5 mono">{k}</td>
                  <td className="tnum" style={{ color: corColor(c.rho) }}>{c.rho?.toFixed(3) ?? "—"}</td>
                  <td className="tnum">{c.gain_ratio?.toFixed(2) ?? "—"}</td>
                  <td className="tnum">{c.snr?.toFixed(2) ?? "—"}</td>
                  <td className="tnum">{((c.valid_frac ?? 0) * 100).toFixed(0)}%</td>
                  <td><Badge tone={DECISION_TONE[c.decision] ?? "default"}>{c.decision}</Badge></td>
                  <td className="text-[var(--muted)] max-w-[220px] truncate" title={c.reason}>{c.reason}</td>
                </tr>
              ))}
              {!Object.keys(channels).length && <tr><td colSpan={7}><Empty>No channel decisions yet.</Empty></td></tr>}
            </tbody>
          </table>
        </div>
      </Panel>

      <Panel title="How it works" className="col-span-12 lg:col-span-5">
        <div className="text-xs text-[var(--muted)] leading-relaxed space-y-2">
          <p>A reproducible, bounded PRBS excitation (seed {wm?.config?.seed}) is added to the <b>{wm?.config?.target}</b> command inside the PLC's secured function block. The exported command register still reports the operator's base value.</p>
          <p>Two shadow copies of the twin's hydraulics predict the <b>expected</b> response; SCADA telemetry gives the <b>observed</b> response. The detector compares them by correlation ρ, response gain and SNR.</p>
          <p>Injection self-suspends on a safety trip, actuator saturation, process limits or poor measurement quality — so it never forces an unsafe perturbation and does not fabricate a result when it cannot measure cleanly. Decisions: <b>consistent / suspicious / inconclusive</b>.</p>
        </div>
      </Panel>
    </div>
  );
}

function corColor(rho?: number) {
  if (rho == null) return "var(--muted)";
  return rho > 0.5 ? "var(--ok)" : rho > 0.25 ? "var(--warn)" : "var(--alarm)";
}
