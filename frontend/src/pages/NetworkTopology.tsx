import { useEffect, useMemo, useState } from "react";
import {
  ReactFlow, Background, Controls, Handle, Position, type Node, type Edge,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { usePolling } from "../hooks/usePolling";
import { api } from "../services/api";
import { Panel, Badge, Empty, LayerTag } from "../components/ui";
import type { TopoNode, TopoLink } from "../types/api";

const KIND_STYLE: Record<string, { bg: string; br: string; ic: string }> = {
  server: { bg: "#0c2b3f", br: "#0ea5e9", ic: "🖥" }, workstation: { bg: "#102a1e", br: "#22c55e", ic: "💻" },
  plc: { bg: "#2a2410", br: "#eab308", ic: "⚙" }, rtu: { bg: "#2a1f10", br: "#f59e0b", ic: "📡" },
  switch: { bg: "#1a2232", br: "#64748b", ic: "⇄" }, firewall: { bg: "#2a1015", br: "#ef4444", ic: "🛡" },
  gateway: { bg: "#241a2e", br: "#a855f7", ic: "🌐" }, ids: { bg: "#0d2a2a", br: "#14b8a6", ic: "🔍" },
  broker: { bg: "#182a1a", br: "#84cc16", ic: "📨" }, sensor: { bg: "#111a26", br: "#38bdf8", ic: "" },
  actuator: { bg: "#1a1626", br: "#818cf8", ic: "" }, attacker: { bg: "#2a0d0d", br: "#dc2626", ic: "☠" },
  external: { bg: "#1a1a1a", br: "#737373", ic: "?" },
};

function DeviceNode({ data }: { data: any }) {
  const st = KIND_STYLE[data.kind] ?? KIND_STYLE.external;
  const field = data.kind === "sensor" || data.kind === "actuator";
  return (
    <div style={{
      background: st.bg, border: `1.5px solid ${data.suspicious ? "#f59e0b" : data.quarantined ? "#dc2626" : st.br}`,
      borderRadius: 8, padding: field ? "3px 6px" : "5px 9px", minWidth: field ? 54 : 92,
      boxShadow: data.suspicious || data.quarantined ? `0 0 10px ${data.quarantined ? "#dc2626" : "#f59e0b"}` : undefined,
    }} className={data.quarantined ? "alarm-pulse" : ""}>
      <Handle type="target" position={Position.Top} style={{ opacity: 0 }} />
      <Handle type="source" position={Position.Bottom} style={{ opacity: 0 }} />
      <div style={{ fontSize: field ? 9 : 11, fontWeight: 700, color: "#e2e8f0" }}>
        {st.ic} {data.label}
      </div>
      {!field && data.ip && <div style={{ fontSize: 8, color: "#64748b" }} className="mono">{data.ip}</div>}
      {data.quarantined && <div style={{ fontSize: 8, color: "#fca5a5" }}>QUARANTINED</div>}
      {data.suspicious && !data.quarantined && <div style={{ fontSize: 8, color: "#fcd34d" }}>suspicious</div>}
    </div>
  );
}
const nodeTypes = { dev: DeviceNode };

export function NetworkTopology() {
  const { data: topo } = usePolling<any>(api.topology, 1500);
  const { data: tr } = usePolling<any>(() => api.traffic(80), 1000);
  const [selEdge, setSelEdge] = useState<string | null>(null);
  const [showField, setShowField] = useState(true);

  const { nodes, edges } = useMemo(() => {
    if (!topo) return { nodes: [] as Node[], edges: [] as Edge[] };
    const nmap = new Map<string, TopoNode>(topo.nodes.map((n: TopoNode) => [n.id, n]));
    const nodes: Node[] = topo.nodes
      .filter((n: TopoNode) => !n.hidden || !n.known || true)
      .filter((n: TopoNode) => showField || (n.kind !== "sensor" && n.kind !== "actuator"))
      .map((n: TopoNode) => ({
        id: n.id, type: "dev", position: { x: n.x, y: n.y },
        data: { ...n, suspicious: n.hidden && !n.known, quarantined: topo.quarantined?.includes(n.id) },
        hidden: n.hidden && n.known === false ? false : undefined,
      }));
    const edges: Edge[] = topo.links
      .filter((l: TopoLink) => {
        if (showField) return true;
        const a = nmap.get(l.a), b = nmap.get(l.b);
        return a?.kind !== "sensor" && a?.kind !== "actuator" && b?.kind !== "sensor" && b?.kind !== "actuator";
      })
      .map((l: TopoLink) => {
        const rate = l.rate?.msgs_s ?? 0;
        const active = rate > 0 && l.up;
        return {
          id: l.id, source: l.a, target: l.b,
          animated: active && rate > 1,
          style: {
            stroke: !l.up ? "#dc2626" : l.suspicious ? "#f59e0b" : l.extra_delay_ms > 0 ? "#f59e0b" : active ? "#0ea5e9" : "#334155",
            strokeWidth: l.suspicious || l.extra_delay_ms > 0 ? 2.5 : Math.min(3, 1 + rate / 60),
          },
        };
      });
    return { nodes, edges };
  }, [topo, showField]);

  const link = topo?.links.find((l: TopoLink) => l.id === selEdge);
  const msgs = tr?.messages ?? [];
  const labels = tr?.labels ?? {};

  return (
    <div className="grid grid-cols-12 gap-4 h-full">
      <Panel title="Industrial network (Purdue-zoned)" className="col-span-12 lg:col-span-8 min-h-0"
        right={<label className="text-xs flex items-center gap-1.5 text-[var(--muted)]">
          <input type="checkbox" checked={showField} onChange={(e) => setShowField(e.target.checked)} /> field devices
        </label>}>
        <div className="flex-1 min-h-[420px] rounded-lg overflow-hidden border border-[var(--border)]">
          <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} fitView
            onEdgeClick={(_, e) => setSelEdge(e.id)} minZoom={0.3} maxZoom={1.8}
            proOptions={{ hideAttribution: true }} colorMode="dark">
            <Background color="#3a3a40" gap={18} />
            <Controls showInteractive={false} />
          </ReactFlow>
        </div>
        <div className="flex gap-3 mt-2 text-[10px] text-[var(--muted)] flex-wrap">
          <Legend color="#0ea5e9" t="active link" /><Legend color="#334155" t="idle" />
          <Legend color="#f59e0b" t="degraded / suspicious" /><Legend color="#dc2626" t="down / quarantined" />
        </div>
      </Panel>

      <div className="col-span-12 lg:col-span-4 flex flex-col gap-4 min-h-0">
        <Panel title="Link inspector">
          {link ? (
            <div className="space-y-1 text-xs">
              <div className="mono text-sm">{link.a} ↔ {link.b}</div>
              <Kv k="Medium" v={link.medium} />
              <Kv k="Base latency" v={`${link.latency_ms} ms`} />
              <Kv k="Added delay" v={`${link.extra_delay_ms} ms`} />
              <Kv k="Loss" v={`${((link.loss + link.extra_loss) * 100).toFixed(2)}%`} />
              <Kv k="Rate" v={`${link.rate?.msgs_s ?? 0} msg/s · ${link.rate?.bytes_s ?? 0} B/s`} />
              <Kv k="Avg latency" v={`${link.rate?.lat_ms ?? 0} ms`} />
              <Kv k="State" v={link.up ? "up" : "DOWN"} />
            </div>
          ) : <Empty>Click a link to inspect it.</Empty>}
        </Panel>

        <Panel title="Live traffic (SPAN mirror)" className="flex-1 min-h-0"
          right={<Badge tone="info">{msgs.length}</Badge>}>
          <div className="overflow-auto flex-1 -mx-1 text-[11px]">
            <table>
              <thead className="text-[var(--muted)] sticky top-0 bg-[var(--panel)]">
                <tr className="text-left"><th className="p-1">t</th><th>src→dst</th><th>proto</th><th>msg</th></tr>
              </thead>
              <tbody>
                {msgs.map((m: any) => {
                  const flagged = labels[m.id] || m.gt_attack;
                  return (
                    <tr key={m.id} className={`border-t border-[var(--border)] ${flagged ? "bg-[#2a0d0d]" : m.dropped ? "opacity-50" : ""}`}>
                      <td className="p-1 tnum text-[var(--muted)]">{m.t?.toFixed(1)}</td>
                      <td className="mono">{short(m.src)}→{short(m.dst)}</td>
                      <td>{m.protocol?.replace("_tcp", "")}</td>
                      <td className="max-w-[150px] truncate" title={m.kind}>
                        {m.dropped ? <span className="text-red-400">✕ {m.dropped}</span> : m.kind}
                        {flagged && <span className="ml-1 text-amber-400">⚑</span>}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </Panel>
      </div>
    </div>
  );
}

const short = (s: string) => s.replace("PLC-", "P").replace("SCADA-01", "SCADA").replace("-01", "");
function Legend({ color, t }: { color: string; t: string }) {
  return <span className="flex items-center gap-1"><span className="w-4 h-0.5" style={{ background: color }} />{t}</span>;
}
function Kv({ k, v }: { k: string; v: any }) {
  return <div className="flex justify-between"><span className="text-[var(--muted)]">{k}</span><span className="mono">{v}</span></div>;
}
