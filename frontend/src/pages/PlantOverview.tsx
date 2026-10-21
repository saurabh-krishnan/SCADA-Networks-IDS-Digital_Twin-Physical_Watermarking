import { useMemo } from "react";
import { useApp } from "../App";
import { usePolling } from "../hooks/usePolling";
import { useChartData } from "../hooks/useChartData";
import { api } from "../services/api";
import { Panel, Stat, Dot, alarmColor, Badge } from "../components/ui";
import { TimeSeries } from "../charts/TimeSeries";
import type { PlantState } from "../types/api";
import { ProcessFlow } from "../components/ProcessFlow";

const BATCH = ["IDLE", "FILL A", "FILL B", "REACT", "DRAIN"];

export function PlantOverview() {
  const { snap } = useApp();
  const { data: ps } = usePolling<PlantState>(api.plantState, 500);
  const chart = useChartData(["TT-101", "TT-201", "FT-101", "gen.P"], 1000, 300);

  const sensors = ps?.sensors ?? {};
  const acts = ps?.actuators ?? {};
  const keyStats = useMemo(() => ([
    { label: "Hot-leg temp", id: "TT-101" },
    { label: "Primary flow", id: "FT-101" },
    { label: "Discharge press.", id: "PT-101" },
    { label: "Sec. inlet temp", id: "TT-201" },
    { label: "Generator output", id: "JT-201" },
    { label: "Treated-water lvl", id: "LT-302" },
  ]), []);

  const safety = ps?.safety;

  return (
    <div className="grid grid-cols-12 gap-4">
      <div className="col-span-12 grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-3">
        {keyStats.map((k) => {
          const s = sensors[k.id];
          return (
            <Stat key={k.id} label={k.label} value={s?.value?.toFixed(s.value! < 10 ? 2 : 1) ?? "—"}
              unit={s?.unit} color={s ? alarmColor(s.alarm) : undefined}
              sub={<span className="flex items-center gap-1"><Dot color={s ? alarmColor(s.alarm) : "#555"} pulse={s?.alarm === "critical"} />{k.id} · {s?.quality ?? "—"}</span>} />
          );
        })}
      </div>

      <Panel title="Process flow — liquid-metal boiler & balance of plant" className="col-span-12 xl:col-span-8"
        right={<Badge tone={ps?.mode === "tripped" ? "danger" : ps?.running ? "ok" : "warn"}>{ps?.mode ?? "—"}</Badge>}>
        <ProcessFlow ps={ps} />
      </Panel>

      <div className="col-span-12 xl:col-span-4 flex flex-col gap-4">
        <Panel title="Safety system (independent SIS)"
          right={<Badge tone={safety?.tripped ? "danger" : "ok"}>{safety?.tripped ? "TRIPPED" : "normal"}</Badge>}>
          <div className="space-y-1.5 max-h-[150px] overflow-auto">
            {safety?.rules.map((r) => (
              <div key={r.id} className="flex items-center justify-between text-xs">
                <span className="flex items-center gap-1.5">
                  <Dot color={r.latched ? "var(--crit)" : "var(--ok)"} pulse={r.latched} />
                  <span className="mono">{r.id}</span>
                </span>
                <span className="text-[var(--muted)] tnum">{r.value?.toFixed(1)} {r.op} {r.limit}</span>
              </div>
            ))}
          </div>
          {safety?.tripped && (
            <button className="btn btn-ok mt-2 justify-center" onClick={() => api.esdReset()}>
              Reset trip (operator)
            </button>
          )}
        </Panel>

        <Panel title="Subsystem status">
          <div className="space-y-2 text-xs">
            <Row label="Chemical batch">
              <Badge tone="info">{BATCH[ps?.batch_phase ?? 0]}</Badge>
            </Row>
            <Row label="Turbine load demand">
              <span className="tnum">{ps?.load_demand_kw?.toFixed(0)} kW</span>
            </Row>
            {ps && Object.entries(ps.controllers).map(([cid, c]) => (
              <Row key={cid} label={cid}>
                <span className="flex items-center gap-2">
                  {c.allowlist && <Badge tone="warn">allow-list</Badge>}
                  {c.rejected_writes > 0 && <Badge tone="danger">{c.rejected_writes} rejected</Badge>}
                  <Dot color="var(--ok)" />
                </span>
              </Row>
            ))}
          </div>
        </Panel>
      </div>

      <Panel title="Primary / secondary temperatures" className="col-span-12 lg:col-span-6">
        <TimeSeries data={chart} series={[
          { key: "TT-101", label: "Hot-leg (°C)", color: "#f87171" },
          { key: "TT-201", label: "Sec. inlet (°C)", color: "#38bdf8" },
        ]} />
      </Panel>
      <Panel title="Flow & generation" className="col-span-12 lg:col-span-6">
        <TimeSeries data={chart} series={[
          { key: "FT-101", label: "Primary flow (kg/s)", color: "#a78bfa" },
          { key: "gen.P", label: "Generator (kW)", color: "#34d399" },
        ]} />
      </Panel>

      <Panel title="Actuators" className="col-span-12">
        <div className="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-6 gap-2">
          {Object.entries(acts).map(([id, a]) => (
            <div key={id} className="panel p-2" style={{ background: "var(--panel2)" }}>
              <div className="flex items-center justify-between">
                <span className="mono text-xs">{id}</span>
                {a.tripped && <Badge tone="danger">TRIP</Badge>}
                {a.suspicious && <Badge tone="warn">susp</Badge>}
              </div>
              <div className="text-[10px] text-[var(--muted)] truncate" title={a.name}>{a.name}</div>
              <div className="mt-1.5 h-1.5 rounded-full bg-[#1a2537] overflow-hidden">
                <div className="h-full rounded-full" style={{
                  width: `${Math.max(0, Math.min(100, a.output))}%`,
                  background: a.tripped ? "var(--crit)" : a.suspicious ? "var(--warn)" : "var(--accent)",
                }} />
              </div>
              <div className="flex justify-between text-[10px] mt-0.5 tnum">
                <span className="text-[var(--muted)]">out {a.output?.toFixed(0)}{a.unit}</span>
                <span className="text-[var(--muted)]">cmd {a.command?.toFixed(0)}</span>
              </div>
            </div>
          ))}
        </div>
      </Panel>
    </div>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-[var(--muted)]">{label}</span>
      {children}
    </div>
  );
}
