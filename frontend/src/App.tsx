import { useEffect, useMemo, useState, createContext, useContext } from "react";
import {
  Activity, Boxes, Network, GitCompareArrows, ShieldAlert, Waves, FlaskConical, BarChart3,
  Play, Pause, RotateCcw, Zap, Gauge, Wifi, WifiOff, AlertTriangle,
} from "lucide-react";
import clsx from "clsx";
import { useWebSocket } from "./hooks/useWebSocket";
import { api } from "./services/api";
import type { Snapshot } from "./types/api";
import { PlantOverview } from "./pages/PlantOverview";
import { DeviceExplorer } from "./pages/DeviceExplorer";
import { NetworkTopology } from "./pages/NetworkTopology";
import { DigitalTwinPage } from "./pages/DigitalTwinPage";
import { SecurityCenter } from "./pages/SecurityCenter";
import { Watermarking } from "./pages/Watermarking";
import { AttackLab } from "./pages/AttackLab";
import { Experiments } from "./pages/Experiments";

interface Ctx { snap: Snapshot | null; meta: any; }
const AppCtx = createContext<Ctx>({ snap: null, meta: null });
export const useApp = () => useContext(AppCtx);

const PAGES = [
  { id: "overview", label: "Plant Overview", icon: Activity, el: PlantOverview },
  { id: "devices", label: "Device Explorer", icon: Boxes, el: DeviceExplorer },
  { id: "network", label: "Network Topology", icon: Network, el: NetworkTopology },
  { id: "twin", label: "Digital Twin", icon: GitCompareArrows, el: DigitalTwinPage },
  { id: "ids", label: "Security Center", icon: ShieldAlert, el: SecurityCenter },
  { id: "watermark", label: "Watermarking", icon: Waves, el: Watermarking },
  { id: "attacks", label: "Attack Lab", icon: FlaskConical, el: AttackLab },
  { id: "experiments", label: "Experiments", icon: BarChart3, el: Experiments },
];

export function App() {
  const { snapshot, status, progress } = useWebSocket();
  const [page, setPage] = useState("overview");
  const [meta, setMeta] = useState<any>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => { api.meta().then(setMeta).catch(() => {}); }, []);

  const act = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    try { await fn(); } catch (e) { console.error(e); } finally { setBusy(false); }
  };

  const running = snapshot?.running ?? false;
  const speed = snapshot?.speed ?? 1;
  const tripped = snapshot?.mode === "tripped";
  const alertCount = snapshot?.ids.active_alerts ?? 0;
  const Page = PAGES.find((p) => p.id === page)!.el;

  const ctx = useMemo(() => ({ snap: snapshot, meta }), [snapshot, meta]);

  return (
    <AppCtx.Provider value={ctx}>
      <div className="h-full flex flex-col">
        {/* top control bar */}
        <header className="flex items-center gap-3 px-4 h-14 border-b border-[var(--border)] bg-[var(--bg)] shrink-0">
          <div className="flex items-center gap-2 pr-3">
            <div className="w-8 h-8 rounded-xl bg-gradient-to-br from-[#ff6a3d] to-[#f1502f] grid place-items-center shadow-[0_2px_10px_-2px_rgba(241,80,47,0.6)]">
              <Gauge size={18} className="text-white" />
            </div>
            <div className="leading-tight">
              <div className="font-semibold text-sm">SCADA · Digital-Twin Security</div>
              <div className="text-[10px] text-[var(--muted)]">Liquid-metal boiler testbed · simulated</div>
            </div>
          </div>

          <div className="flex items-center gap-2 ml-2">
            {running ? (
              <button className="btn btn-accent" disabled={busy} onClick={() => act(api.simPause)}>
                <Pause size={15} /> Pause
              </button>
            ) : (
              <button className="btn btn-ok" disabled={busy} onClick={() => act(api.simStart)}>
                <Play size={15} /> {snapshot && snapshot.t > 0 ? "Resume" : "Start"}
              </button>
            )}
            <button className="btn" disabled={busy} onClick={() => act(() => api.simReset())}>
              <RotateCcw size={15} /> Reset
            </button>
            <div className="flex items-center gap-1.5 ml-1">
              <Gauge size={14} className="text-[var(--muted)]" />
              <select value={speed} onChange={(e) => act(() => api.simSpeed(Number(e.target.value)))}
                className="w-[70px]">
                {[0.5, 1, 2, 4, 8].map((s) => <option key={s} value={s}>{s}×</option>)}
              </select>
            </div>
            <button className="btn btn-danger" disabled={busy} onClick={() => act(api.esd)} title="Independent safety emergency shutdown">
              <Zap size={15} /> ESD
            </button>
          </div>

          <div className="ml-auto flex items-center gap-4 text-sm">
            {progress.running && (
              <span className="text-xs text-orange-400">experiment {Math.round((progress.progress ?? 0) * 100)}%</span>
            )}
            <div className="flex items-center gap-1.5">
              <span className="text-[var(--muted)] text-xs">t</span>
              <span className="tnum font-medium">{(snapshot?.t ?? 0).toFixed(1)}s</span>
            </div>
            {tripped && (
              <span className="tag sev-critical alarm-pulse flex items-center gap-1"><AlertTriangle size={13} /> SAFETY TRIP</span>
            )}
            <div className={clsx("flex items-center gap-1.5 text-xs", alertCount > 0 ? "text-red-400" : "text-[var(--muted)]")}>
              <ShieldAlert size={14} /> {alertCount} active
            </div>
            <div className="flex items-center gap-1.5 text-xs">
              {status === "open" ? <Wifi size={14} className="text-green-400" /> : <WifiOff size={14} className="text-red-400" />}
              <span className="text-[var(--muted)]">{status}</span>
            </div>
          </div>
        </header>

        <div className="flex flex-1 min-h-0">
          {/* sidebar nav */}
          <nav className="w-64 border-r border-[var(--border)] bg-[var(--bg)] p-2.5 flex flex-col gap-1.5 shrink-0">
            {PAGES.map((p) => {
              const Icon = p.icon;
              const active = page === p.id;
              const badge = p.id === "ids" && alertCount > 0 ? alertCount :
                p.id === "attacks" && snapshot?.lab.running.length ? snapshot.lab.running.length : null;
              return (
                <button key={p.id} onClick={() => setPage(p.id)}
                  className={clsx("flex items-center gap-3 px-4 py-3 rounded-2xl text-[15px] font-medium transition-all text-left border",
                    active
                      ? "bg-[#1f1f23] text-white border-[#2c2c31] shadow-[0_1px_0_rgba(255,255,255,0.04)_inset]"
                      : "text-[var(--muted)] border-transparent hover:bg-[#161619] hover:text-[var(--txt)]")}>
                  <Icon size={21} className={active ? "text-[var(--accent)]" : ""} />
                  <span className="flex-1">{p.label}</span>
                  {badge && <span className="tag sev-high !px-2 !py-0.5 text-[11px]">{badge}</span>}
                </button>
              );
            })}
            <div className="mt-auto px-3 py-2.5 text-[11px] text-[var(--muted)] leading-relaxed border-t border-[var(--border)]">
              Educational simulation. All devices, telemetry and attacks are synthetic and local.
            </div>
          </nav>

          {/* page */}
          <main className="relative flex-1 min-w-0 overflow-auto p-4">
            {/* soft ambient top-light glow (Vaulto-style) */}
            <div aria-hidden className="ambient-glow" />
            <div aria-hidden className="ambient-glow ambient-glow--right" />
            <div className="relative z-10">
              {snapshot ? <Page /> : (
                <div className="h-full grid place-items-center text-[var(--muted)]">
                  {status === "open" ? "Loading simulation…" : "Connecting to backend…"}
                </div>
              )}
            </div>
          </main>
        </div>
      </div>
    </AppCtx.Provider>
  );
}
