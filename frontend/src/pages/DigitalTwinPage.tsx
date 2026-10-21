import { useState } from "react";
import { usePolling } from "../hooks/usePolling";
import { useChartData } from "../hooks/useChartData";
import { api } from "../services/api";
import { Panel, Stat, Badge, Dot, Empty } from "../components/ui";
import { TimeSeries } from "../charts/TimeSeries";
import type { TwinState } from "../types/api";

const MONITORED = ["TT-101", "TT-102", "TT-103", "FT-101", "PT-101", "PT-102", "TT-201", "TT-202", "FT-201"];

export function DigitalTwinPage() {
  const { data: tw } = usePolling<TwinState>(api.twin, 700);
  const [tag, setTag] = useState("TT-101");
  // predicted vs observed chart only wired for TT-101 / FT-101 (buffered server-side)
  const buffered = tag === "TT-101" ? ["TT-101", "twin.TT-101", "res.TT-101"]
    : tag === "FT-101" ? ["FT-101", "twin.FT-101", "res.FT-101"] : [tag];
  const data = useChartData(buffered, 1000, 300);
  const hasTwin = buffered.length > 1;

  const health = tw?.health ?? "—";
  const healthTone = health === "healthy" ? "ok" : health === "degraded" ? "warn" : "danger";

  return (
    <div className="grid grid-cols-12 gap-4">
      <div className="col-span-12 grid grid-cols-2 md:grid-cols-4 gap-3">
        <Stat label="Model health" value={health}
          color={healthTone === "ok" ? "var(--ok)" : healthTone === "warn" ? "var(--warn)" : "var(--crit)"} />
        <Stat label="Confidence" value={((tw?.confidence ?? 0) * 100).toFixed(0)} unit="%" />
        <Stat label="Sync status" value={<span className="text-base">{tw?.sync_status ?? "—"}</span>} />
        <Stat label="Max anomaly score" value={((tw?.anomaly_score ?? 0)).toFixed(2)}
          color={(tw?.anomaly_score ?? 0) > 0.5 ? "var(--alarm)" : "var(--ok)"} sub={`resyncs: ${tw?.resyncs ?? 0}`} />
      </div>

      <Panel className="col-span-12 lg:col-span-8"
        title="Predicted vs observed"
        right={<select value={tag} onChange={(e) => setTag(e.target.value)}>
          {["TT-101", "FT-101", ...MONITORED.filter((m) => m !== "TT-101" && m !== "FT-101")]
            .map((m) => <option key={m} value={m}>{m}</option>)}
        </select>}>
        {hasTwin ? (
          <>
            <TimeSeries data={data} height={200} series={[
              { key: tag, label: "observed", color: "#38bdf8" },
              { key: `twin.${tag}`, label: "twin prediction", color: "#f59e0b", dash: "5 3" },
            ]} />
            <div className="card-title mt-3 mb-1">Residual (observed − predicted)</div>
            <TimeSeries data={data} height={120} series={[
              { key: `res.${tag}`, label: "residual", color: "#a78bfa" },
            ]} refLines={[{ y: 0, color: "#334155" }]} />
          </>
        ) : (
          <div className="py-6">
            <Empty>Live predicted/observed chart is buffered for TT-101 and FT-101. Residual table below covers all channels.</Empty>
            <TimeSeries data={data} height={180} series={[{ key: tag, label: tag, color: "#38bdf8" }]} />
          </div>
        )}
      </Panel>

      <Panel title="Independence" className="col-span-12 lg:col-span-4">
        <div className="text-xs text-[var(--muted)] leading-relaxed space-y-2">
          <p>The twin integrates its <b>own</b> RK4 physics model with datasheet parameters that differ from the plant by a few percent. It is driven by issued commands and a few measured inputs — never by the simulator's hidden ground-truth state.</p>
          <p>Measurements are fused only through a gated correction (|z| &lt; {tw?.gate_z}). Readings that jump outside the gate are <b>rejected</b>, so a falsified sensor cannot silently drag the twin along.</p>
          <div className="flex items-center gap-2 pt-1">
            <Dot color="var(--ok)" /> <span>independent of ground truth: {String(tw?.independent_of_ground_truth)}</span>
          </div>
        </div>
        <div className="mt-3">
          <div className="card-title mb-1">Model inputs</div>
          <div className="grid grid-cols-2 gap-x-3 text-xs">
            {tw && Object.entries(tw.inputs).map(([k, v]) => (
              <div key={k} className="flex justify-between"><span className="text-[var(--muted)]">{k}</span><span className="mono">{v}</span></div>
            ))}
          </div>
        </div>
      </Panel>

      <Panel title="Residual monitor (all channels)" className="col-span-12">
        <div className="overflow-auto">
          <table className="text-xs">
            <thead className="text-[var(--muted)]">
              <tr className="text-left">
                <th className="p-1.5">Tag</th><th>Observed</th><th>Predicted</th><th>Residual</th>
                <th>z</th><th>σ</th><th>CUSUM</th><th>Score</th><th>State</th>
              </tr>
            </thead>
            <tbody>
              {tw && MONITORED.map((m) => {
                const r = tw.residuals[m];
                if (!r) return null;
                const z = r.z ?? 0;
                const zc = Math.abs(z) > 5 ? "var(--crit)" : Math.abs(z) > 3 ? "var(--warn)" : "var(--txt)";
                return (
                  <tr key={m} className="border-t border-[var(--border)]">
                    <td className="p-1.5 mono">{m}{tw.gated[m] && <span className="ml-1 text-amber-400" title="rejected by gate">⊘</span>}</td>
                    <td className="tnum">{r.observed?.toFixed(3) ?? "—"}</td>
                    <td className="tnum text-[var(--muted)]">{r.predicted?.toFixed(3) ?? "—"}</td>
                    <td className="tnum">{r.residual?.toFixed(3) ?? "—"}</td>
                    <td className="tnum font-semibold" style={{ color: zc }}>{r.z?.toFixed(2) ?? "—"}</td>
                    <td className="tnum text-[var(--muted)]">{r.sigma?.toFixed(3)}</td>
                    <td className="tnum">{r.cusum?.toFixed(1)}</td>
                    <td><ScoreBar v={r.score ?? 0} /></td>
                    <td>
                      {r.calibrating ? <Badge>calibrating</Badge>
                        : r.sudden ? <Badge tone="danger">sudden</Badge>
                        : r.persistent ? <Badge tone="warn">persistent</Badge>
                        : <Badge tone="ok">ok</Badge>}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Panel>
    </div>
  );
}

function ScoreBar({ v }: { v: number }) {
  return (
    <div className="w-16 h-1.5 rounded-full bg-[#1a2537] overflow-hidden">
      <div className="h-full rounded-full" style={{
        width: `${Math.min(100, v * 100)}%`, background: v > 0.7 ? "var(--crit)" : v > 0.4 ? "var(--warn)" : "var(--ok)",
      }} />
    </div>
  );
}
