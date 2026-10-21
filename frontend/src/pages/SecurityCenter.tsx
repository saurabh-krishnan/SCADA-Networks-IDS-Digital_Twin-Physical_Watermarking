import { useMemo, useState } from "react";
import { usePolling } from "../hooks/usePolling";
import { api } from "../services/api";
import { Panel, SevTag, LayerTag, Badge, Empty, Dot } from "../components/ui";
import type { Alert, Incident } from "../types/api";

const LAYERS = ["network", "process", "twin", "watermark"];

export function SecurityCenter() {
  const { data: alertsData, refresh: ra } = usePolling<any>(() => api.alerts(false, 200), 1000);
  const { data: incData } = usePolling<any>(api.incidents, 1000);
  const { data: resp } = usePolling<any>(api.response, 1000);
  const [minSev, setMinSev] = useState("low");
  const [layerFilter, setLayerFilter] = useState<Record<string, boolean>>(
    { network: true, process: true, twin: true, watermark: true });
  const [selInc, setSelInc] = useState<string | null>(null);

  const rank: Record<string, number> = { info: 0, low: 1, medium: 2, high: 3, critical: 4 };
  const alerts: Alert[] = (alertsData?.alerts ?? []).filter((a: Alert) =>
    rank[a.severity] >= rank[minSev] && layerFilter[a.source]);
  const incidents: Incident[] = incData?.incidents ?? [];
  const selected = incidents.find((i) => i.id === selInc) ?? incidents[0];
  const layersEnabled = alertsData?.layers_enabled ?? {};

  const toggleLayer = async (l: string) => {
    const next = { ...layersEnabled, [l]: !layersEnabled[l] };
    await api.toggleLayers(next); ra();
  };

  return (
    <div className="grid grid-cols-12 gap-4 h-full">
      <div className="col-span-12 lg:col-span-7 flex flex-col gap-4 min-h-0">
        <Panel title="Detection layers">
          <div className="flex gap-2 flex-wrap">
            {LAYERS.map((l) => (
              <button key={l} onClick={() => toggleLayer(l)}
                className={`btn ${layersEnabled[l] === false ? "opacity-50" : ""}`}>
                <Dot color={layersEnabled[l] === false ? "#64748b" : "#22c55e"} /> <LayerTag layer={l} />
              </button>
            ))}
            <span className="text-[11px] text-[var(--muted)] self-center ml-2">toggle a layer to compare detection coverage</span>
          </div>
        </Panel>

        <Panel title={`Alert feed (${alerts.length})`} className="flex-1 min-h-0"
          right={<div className="flex items-center gap-2">
            <select value={minSev} onChange={(e) => setMinSev(e.target.value)}>
              {["info", "low", "medium", "high", "critical"].map((s) => <option key={s} value={s}>≥ {s}</option>)}
            </select>
            <a className="btn" href={api.exportUrl("alerts")}>Export CSV</a>
          </div>}>
          <div className="flex gap-1.5 mb-2 flex-wrap">
            {LAYERS.map((l) => (
              <label key={l} className="text-[11px] flex items-center gap-1 text-[var(--muted)]">
                <input type="checkbox" checked={layerFilter[l]} onChange={(e) => setLayerFilter({ ...layerFilter, [l]: e.target.checked })} />
                <LayerTag layer={l} />
              </label>
            ))}
          </div>
          <div className="overflow-auto flex-1 -mx-1 space-y-1.5">
            {alerts.map((a) => (
              <div key={a.id} onClick={() => a.incident_id && setSelInc(a.incident_id)}
                className={`panel p-2 cursor-pointer ${a.incident_id === selected?.id ? "border-orange-600" : ""} ${!a.active ? "opacity-50" : ""}`}
                style={{ background: "var(--panel2)" }}>
                <div className="flex items-center gap-2">
                  <SevTag sev={a.severity} /><LayerTag layer={a.source} />
                  <span className="font-medium text-xs">{a.category}</span>
                  <span className="ml-auto text-[10px] text-[var(--muted)] tnum">t={a.timestamp}s · ×{a.count}</span>
                </div>
                <div className="text-[11px] text-[var(--muted)] mt-1 flex items-center gap-2">
                  <span className="mono text-[var(--txt)]">{a.asset}</span>
                  <span className="mono">{a.rule}</span>
                  {a.score != null && <span>score {a.score.toFixed(2)}</span>}
                  {!a.active && <Badge>cleared</Badge>}
                </div>
                {a.evidence?.detail && <div className="text-[10px] text-[var(--muted)] mt-0.5 italic truncate">{a.evidence.detail}</div>}
              </div>
            ))}
            {!alerts.length && <Empty>No alerts match the current filters. (Clean operation, or layer disabled.)</Empty>}
          </div>
        </Panel>
      </div>

      <div className="col-span-12 lg:col-span-5 flex flex-col gap-4 min-h-0">
        <Panel title="Incidents" right={<Badge tone="info">{incidents.length}</Badge>}>
          <div className="space-y-1.5 max-h-[180px] overflow-auto">
            {incidents.map((i) => (
              <div key={i.id} onClick={() => setSelInc(i.id)}
                className={`panel p-2 cursor-pointer ${selected?.id === i.id ? "border-orange-600" : ""}`}
                style={{ background: "var(--panel2)" }}>
                <div className="flex items-center gap-2">
                  <SevTag sev={i.severity} />
                  <span className="text-xs font-medium flex-1">{i.classification}</span>
                  <Badge tone={i.status === "resolved" ? "ok" : i.status === "responding" ? "info" : "warn"}>{i.status}</Badge>
                </div>
                <div className="text-[10px] text-[var(--muted)] mt-1 flex gap-2 items-center">
                  <span className="mono">{i.id}</span> · {i.zone} · conf {(i.confidence * 100).toFixed(0)}%
                  <span className="flex gap-0.5 ml-auto">{i.layers.map((l) => <LayerTag key={l} layer={l} />)}</span>
                </div>
              </div>
            ))}
            {!incidents.length && <Empty>No incidents.</Empty>}
          </div>
        </Panel>

        <Panel title="Incident detail" className="flex-1 min-h-0">
          {selected ? (
            <div className="overflow-auto flex-1 text-xs space-y-2">
              <div className="flex items-center gap-2">
                <SevTag sev={selected.severity} />
                <span className="font-semibold text-sm">{selected.classification}</span>
              </div>
              <div className="grid grid-cols-2 gap-x-4 gap-y-0.5 text-[11px]">
                <Kv k="Incident" v={selected.id} /><Kv k="Zone" v={selected.zone} />
                <Kv k="Confidence" v={`${(selected.confidence * 100).toFixed(0)}%`} />
                <Kv k="Status" v={selected.status} />
                <Kv k="Assets" v={selected.assets.join(", ")} />
                <Kv k="Layers" v={selected.layers.join(", ")} />
              </div>
              {!selected.acknowledged && selected.status !== "resolved" && (
                <button className="btn" onClick={() => api.ackIncident(selected.id)}>Acknowledge</button>
              )}
              <div>
                <div className="card-title mb-1">Recommended responses</div>
                {selected.recommendations.map((r, i) => (
                  <div key={i} className="flex items-start gap-2 py-0.5">
                    <Dot color="var(--info)" />
                    <span><span className="mono text-orange-300">{r.action}</span> → <span className="mono">{r.target}</span>
                      <span className="text-[var(--muted)]"> · {r.reason}</span></span>
                  </div>
                ))}
              </div>
              <div>
                <div className="card-title mb-1">Timeline</div>
                <div className="space-y-0.5 border-l border-[var(--border)] pl-3">
                  {selected.timeline.slice(-18).map((t: any, i: number) => (
                    <div key={i} className="text-[11px] relative">
                      <span className="absolute -left-[13px] top-1.5 w-1.5 h-1.5 rounded-full bg-orange-500" />
                      <span className="text-[var(--muted)] tnum">t={t.t}s</span> {t.event}
                      {t.severity && <span className="ml-1"><SevTag sev={t.severity} /></span>}
                    </div>
                  ))}
                </div>
              </div>
            </div>
          ) : <Empty>No incident selected.</Empty>}
        </Panel>

        <Panel title="Response status" right={<Badge tone="info">{resp?.mode ?? "—"}</Badge>}>
          <div className="text-[11px] space-y-1 max-h-[120px] overflow-auto">
            {(resp?.history ?? []).slice(0, 8).map((r: any) => (
              <div key={r.id} className="flex items-center gap-2">
                <Badge tone={r.status === "executed" ? "ok" : r.status === "pending_approval" ? "warn" : "default"}>{r.status}</Badge>
                <span className="mono text-orange-300">{r.action}</span>
                <span className="mono text-[var(--muted)]">{r.target}</span>
              </div>
            ))}
            {!resp?.history?.length && <Empty>No responses yet.</Empty>}
          </div>
        </Panel>
      </div>
    </div>
  );
}

function Kv({ k, v }: { k: string; v: any }) {
  return <><span className="text-[var(--muted)]">{k}</span><span className="mono text-right">{v}</span></>;
}
