import { useState } from "react";
import { usePolling } from "../hooks/usePolling";
import { api } from "../services/api";
import { useApp } from "../App";
import { Panel, Badge, Empty, Dot } from "../components/ui";
import type { Scenario } from "../types/api";

const CAT_TONE: Record<string, string> = {
  process_falsification: "warn", command_injection: "danger", actuator_falsification: "warn",
  availability: "info", policy_violation: "warn", model_tampering: "danger", coordinated: "danger",
};

export function AttackLab() {
  const { snap } = useApp();
  const { data, refresh } = usePolling<any>(api.attacks, 800);
  const { data: resp, refresh: rr } = usePolling<any>(api.response, 1000);
  const [sel, setSel] = useState<string | null>(null);
  const [params, setParams] = useState<string>("{}");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const catalog: Scenario[] = data?.catalog ?? [];
  const running: any[] = data?.running ?? [];
  const runningKeys = new Set(running.map((r) => r.key));
  const selected = catalog.find((c) => c.key === sel) ?? catalog[0];
  const selRunning = running.find((r) => r.key === selected?.key);

  const pickScenario = (s: Scenario) => {
    setSel(s.key); setParams(JSON.stringify(s.default_params, null, 2)); setErr(null);
  };

  const act = async (fn: () => Promise<unknown>) => {
    setBusy(true); setErr(null);
    try { await fn(); await refresh(); await rr(); }
    catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  };

  const start = () => {
    let p = {};
    try { p = JSON.parse(params || "{}"); } catch { setErr("params must be valid JSON"); return; }
    act(() => api.attackStart(selected.key, p));
  };

  const setMode = (m: string) => act(() => api.responseMode(m));

  return (
    <div className="grid grid-cols-12 gap-4 h-full">
      <Panel title="Scenario library" className="col-span-12 lg:col-span-4 min-h-0"
        right={<Badge tone="warn">simulated only</Badge>}>
        <div className="overflow-auto flex-1 space-y-1.5 -mx-1">
          {catalog.map((s) => (
            <div key={s.key} onClick={() => pickScenario(s)}
              className={`panel p-2 cursor-pointer ${selected?.key === s.key ? "border-orange-600" : ""}`}
              style={{ background: "var(--panel2)" }}>
              <div className="flex items-center gap-2">
                {runningKeys.has(s.key) && <Dot color="var(--alarm)" pulse />}
                <span className="text-xs font-medium flex-1">{s.name}</span>
                <Badge tone={CAT_TONE[s.category] ?? "default"}>{s.category.replace(/_/g, " ")}</Badge>
              </div>
              <div className="text-[10px] text-[var(--muted)] mt-0.5 line-clamp-2">{s.description}</div>
            </div>
          ))}
        </div>
      </Panel>

      <div className="col-span-12 lg:col-span-4 flex flex-col gap-4 min-h-0">
        <Panel title="Scenario configuration">
          {selected ? (
            <div className="space-y-2 text-xs">
              <div className="font-semibold text-sm">{selected.name}</div>
              <p className="text-[var(--muted)]">{selected.description}</p>
              <Kv k="Preconditions" v={selected.preconditions} />
              <div><span className="text-[var(--muted)]">Targets:</span> {selected.target_assets.map((a) =>
                <span key={a} className="mono mx-0.5">{a}</span>)}</div>
              <div>
                <div className="text-[var(--muted)] mb-0.5">Expected evidence:</div>
                <ul className="list-disc list-inside text-[11px]">
                  {selected.expected_evidence.map((e, i) => <li key={i}>{e}</li>)}
                </ul>
              </div>
              <div>
                <div className="text-[var(--muted)] mb-1">Parameters (JSON, with recorded seed):</div>
                <textarea value={params} onChange={(e) => setParams(e.target.value)} rows={5}
                  className="w-full mono text-[11px] bg-[var(--panel2)] border border-[var(--border)] rounded p-2" />
              </div>
              {err && <div className="text-red-400 text-[11px]">{err}</div>}
              {selRunning ? (
                <button className="btn btn-ok w-full justify-center" disabled={busy}
                  onClick={() => act(() => api.attackStop(selected.key))}>Stop & recover</button>
              ) : (
                <button className="btn btn-danger w-full justify-center" disabled={busy} onClick={start}>
                  Launch scenario
                </button>
              )}
            </div>
          ) : <Empty>Select a scenario.</Empty>}
        </Panel>

        <Panel title="Defensive response mode">
          <div className="flex gap-1.5">
            {["monitor", "approval", "auto"].map((m) => (
              <button key={m} onClick={() => setMode(m)}
                className={`btn flex-1 justify-center ${resp?.mode === m ? "btn-accent" : ""}`}>{m}</button>
            ))}
          </div>
          <div className="text-[10px] text-[var(--muted)] mt-2">
            monitor = record only · approval = operator confirms · auto = execute on simulated components
          </div>
          {resp?.pending?.length > 0 && (
            <div className="mt-2 space-y-1">
              <div className="card-title">Pending approvals</div>
              {resp.pending.map((p: any) => (
                <div key={p.id} className="flex items-center gap-2 text-[11px] panel p-1.5" style={{ background: "var(--panel2)" }}>
                  <span className="mono text-orange-300 flex-1">{p.action} → {p.target}</span>
                  <button className="btn btn-ok !py-0.5 !px-2" onClick={() => act(() => api.approve(p.id, true))}>✓</button>
                  <button className="btn btn-danger !py-0.5 !px-2" onClick={() => act(() => api.approve(p.id, false))}>✕</button>
                </div>
              ))}
            </div>
          )}
        </Panel>
      </div>

      <div className="col-span-12 lg:col-span-4 flex flex-col gap-4 min-h-0">
        <Panel title="Active scenarios"
          right={running.length ? <button className="btn btn-danger !py-0.5" onClick={() => act(api.attackStopAll)}>stop all</button> : undefined}>
          {running.length ? (
            <div className="space-y-2">
              {running.map((r) => (
                <div key={r.key} className="panel p-2" style={{ background: "var(--panel2)" }}>
                  <div className="flex items-center gap-2">
                    <Dot color="var(--alarm)" pulse />
                    <span className="text-xs font-medium flex-1">{r.name}</span>
                    <Badge tone={r.effect_active ? "danger" : "warn"}>{r.effect_active ? "effect active" : "armed"}</Badge>
                  </div>
                  <div className="text-[10px] text-[var(--muted)] mt-0.5 tnum">
                    seed {r.seed} · t+{r.elapsed?.toFixed(0)}s · targets {r.target_assets.join(", ")}
                  </div>
                  {r.log?.slice(-2).map((l: any, i: number) => (
                    <div key={i} className="text-[10px] text-[var(--muted)] mt-0.5">↳ {l.event}</div>
                  ))}
                </div>
              ))}
            </div>
          ) : <Empty>No active scenarios. Ground truth: {String(snap?.lab.ground_truth)}.</Empty>}
        </Panel>

        <Panel title="Detection outcome (live)" className="flex-1 min-h-0">
          <div className="text-xs space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-[var(--muted)]">Active alerts</span>
              <Badge tone={snap && snap.ids.active_alerts > 0 ? "danger" : "ok"}>{snap?.ids.active_alerts ?? 0}</Badge>
            </div>
            <div className="flex items-center gap-1.5">
              <span className="text-[var(--muted)]">Layers firing:</span>
              {(snap?.ids.active_layers ?? []).length
                ? snap!.ids.active_layers.map((l) => <Badge key={l} tone="danger">{l}</Badge>)
                : <span className="text-[var(--muted)]">none</span>}
            </div>
            <div className="flex items-center justify-between">
              <span className="text-[var(--muted)]">Open incidents</span>
              <Badge tone="info">{snap?.ids.open_incidents ?? 0}</Badge>
            </div>
            {snap?.incidents?.[0] && (
              <div className="panel p-2 mt-1" style={{ background: "var(--panel2)" }}>
                <div className="text-[11px] font-medium">{snap.incidents[0].classification}</div>
                <div className="text-[10px] text-[var(--muted)]">confidence {(snap.incidents[0].confidence * 100).toFixed(0)}% · {snap.incidents[0].status}</div>
              </div>
            )}
            <div className="text-[10px] text-[var(--muted)] pt-2 border-t border-[var(--border)]">
              Detection comes from observed evidence only — starting a scenario does not itself raise an alert, and a
              detector may legitimately miss an attack it has no signal for.
            </div>
          </div>
        </Panel>
      </div>
    </div>
  );
}

function Kv({ k, v }: { k: string; v: any }) {
  return <div><span className="text-[var(--muted)]">{k}: </span>{v}</div>;
}
