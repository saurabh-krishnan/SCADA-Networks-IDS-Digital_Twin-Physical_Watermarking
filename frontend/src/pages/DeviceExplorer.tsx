import { useMemo, useState } from "react";
import { usePolling } from "../hooks/usePolling";
import { useChartData } from "../hooks/useChartData";
import { api } from "../services/api";
import { Panel, Dot, alarmColor, Badge, Empty } from "../components/ui";
import { TimeSeries } from "../charts/TimeSeries";

export function DeviceExplorer() {
  const { data } = usePolling<any>(api.devices, 1000);
  const [q, setQ] = useState("");
  const [sub, setSub] = useState("all");
  const [kind, setKind] = useState("all");
  const [sel, setSel] = useState<string | null>(null);

  const devices = data?.devices ?? [];
  const subsystems = useMemo(() => Array.from(new Set(devices.map((d: any) => d.subsystem))).filter(Boolean), [devices]);

  const filtered = devices.filter((d: any) => {
    if (sub !== "all" && d.subsystem !== sub) return false;
    if (kind !== "all" && d.type !== kind) return false;
    if (q && !(`${d.id} ${d.name}`.toLowerCase().includes(q.toLowerCase()))) return false;
    return true;
  });

  const selected = devices.find((d: any) => d.id === sel) ?? filtered[0];
  const isSensor = selected?.type === "sensor";
  const chartKey = isSensor ? selected?.id : null;

  return (
    <div className="grid grid-cols-12 gap-4 h-full">
      <Panel title={`Device inventory (${filtered.length})`} className="col-span-12 lg:col-span-7 min-h-0">
        <div className="flex gap-2 mb-2 flex-wrap">
          <input placeholder="Search id / name…" value={q} onChange={(e) => setQ(e.target.value)} className="flex-1 min-w-[140px]" />
          <select value={sub} onChange={(e) => setSub(e.target.value)}>
            <option value="all">all subsystems</option>
            {subsystems.map((s: any) => <option key={s} value={s}>{s}</option>)}
          </select>
          <select value={kind} onChange={(e) => setKind(e.target.value)}>
            {["all", "sensor", "actuator"].map((k) => <option key={k} value={k}>{k}</option>)}
          </select>
        </div>
        <div className="overflow-auto flex-1 -mx-1">
          <table className="text-xs">
            <thead className="text-[var(--muted)] sticky top-0 bg-[var(--panel)]">
              <tr className="text-left"><th className="p-1.5">ID</th><th>Name</th><th>Type</th><th>Value</th><th>Status</th></tr>
            </thead>
            <tbody>
              {filtered.map((d: any) => (
                <tr key={d.id} onClick={() => setSel(d.id)}
                  className={`cursor-pointer border-t border-[var(--border)] hover:bg-[#121b2b] ${selected?.id === d.id ? "bg-[#13263c]" : ""}`}>
                  <td className="p-1.5 mono">{d.id}</td>
                  <td className="text-[var(--muted)] max-w-[180px] truncate">{d.name}</td>
                  <td>{d.type}</td>
                  <td className="tnum">{d.field_value ?? d.output ?? "—"}{d.unit && ` ${d.unit}`}</td>
                  <td>
                    <span className="flex items-center gap-1.5">
                      <Dot color={alarmColor(d.alarm_state)} pulse={d.alarm_state === "critical"} />
                      {d.suspicious && <Badge tone="warn">susp</Badge>}
                      {d.quarantined && <Badge tone="danger">quar</Badge>}
                      {d.tripped && <Badge tone="danger">trip</Badge>}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {!filtered.length && <Empty>No devices match the filter.</Empty>}
        </div>
      </Panel>

      <div className="col-span-12 lg:col-span-5 flex flex-col gap-4 min-h-0">
        <Panel title="Device detail">
          {selected ? (
            <div className="space-y-2 text-sm">
              <div className="flex items-center justify-between">
                <span className="mono text-base">{selected.id}</span>
                <Badge tone="info">{selected.type}</Badge>
              </div>
              <div className="text-[var(--muted)]">{selected.name}</div>
              <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs mt-2">
                <Kv k="Subsystem" v={selected.subsystem} />
                <Kv k="Controller" v={selected.controller ?? "—"} />
                <Kv k="Mode" v={selected.mode} />
                <Kv k="Comm" v={selected.comm_status} />
                <Kv k="Alarm" v={selected.alarm_state} />
                <Kv k="Auth" v={selected.auth_state} />
                {isSensor && <Kv k="Field value" v={`${selected.field_value ?? "—"} ${selected.unit}`} />}
                {isSensor && <Kv k="Range" v={selected.range?.join(" … ")} />}
                {selected.type === "actuator" && <Kv k="Output" v={`${selected.output} ${selected.unit}`} />}
                {selected.type === "actuator" && <Kv k="Command" v={`${selected.command}`} />}
                {selected.type === "actuator" && <Kv k="Feedback" v={`${selected.feedback}`} />}
              </div>
              {selected.params && Object.keys(selected.params).length > 0 && (
                <div className="mt-2">
                  <div className="card-title mb-1">Parameters</div>
                  <div className="grid grid-cols-2 gap-x-4 text-xs">
                    {Object.entries(selected.params).map(([k, v]: any) => <Kv key={k} k={k} v={String(v)} />)}
                  </div>
                </div>
              )}
            </div>
          ) : <Empty>Select a device.</Empty>}
        </Panel>

        <Panel title="Telemetry" className="flex-1 min-h-0">
          {chartKey ? <SensorChart id={chartKey} unit={selected.unit} />
            : <Empty>Select a sensor to view its live telemetry.</Empty>}
        </Panel>
      </div>
    </div>
  );
}

function SensorChart({ id, unit }: { id: string; unit: string }) {
  const data = useChartData([id], 1000, 300);
  return <TimeSeries data={data} unit={unit} series={[{ key: id, label: `${id} (${unit})`, color: "#38bdf8" }]} height={200} />;
}
function Kv({ k, v }: { k: string; v: any }) {
  return <><span className="text-[var(--muted)]">{k}</span><span className="text-right mono">{v}</span></>;
}
