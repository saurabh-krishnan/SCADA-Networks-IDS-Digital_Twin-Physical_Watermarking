import type { ReactNode } from "react";
import clsx from "clsx";

export function Panel({ title, right, children, className }: {
  title?: string; right?: ReactNode; children: ReactNode; className?: string;
}) {
  return (
    <div className={clsx("panel p-3 flex flex-col", className)}>
      {(title || right) && (
        <div className="flex items-center justify-between mb-2">
          {title && <span className="card-title">{title}</span>}
          {right}
        </div>
      )}
      {children}
    </div>
  );
}

const SEV_RANK: Record<string, number> = { info: 0, low: 1, medium: 2, high: 3, critical: 4, cleared: 0 };
export function sevClass(sev: string) {
  return `tag sev-${sev in SEV_RANK ? sev : "info"}`;
}

export function SevTag({ sev }: { sev: string }) {
  return <span className={sevClass(sev)}>{sev.toUpperCase()}</span>;
}

export function Dot({ color, pulse }: { color: string; pulse?: boolean }) {
  return <span className={clsx("inline-block w-2.5 h-2.5 rounded-full", pulse && "alarm-pulse")}
    style={{ background: color }} />;
}

export const alarmColor = (s: string) =>
  s === "critical" ? "var(--crit)" : s === "alarm" ? "var(--alarm)" :
  s === "warning" ? "var(--warn)" : "var(--ok)";

export function Stat({ label, value, unit, sub, color }: {
  label: string; value: ReactNode; unit?: string; sub?: ReactNode; color?: string;
}) {
  return (
    <div className="panel p-4">
      <div className="card-title">{label}</div>
      <div className="flex items-baseline gap-1 mt-1.5">
        <span className="text-2xl font-semibold tnum" style={{ color: color ?? "var(--txt)" }}>{value}</span>
        {unit && <span className="text-xs text-[var(--muted)]">{unit}</span>}
      </div>
      {sub && <div className="text-xs text-[var(--muted)] mt-1">{sub}</div>}
    </div>
  );
}

export function Badge({ children, tone = "default" }: { children: ReactNode; tone?: string }) {
  const tones: Record<string, string> = {
    default: "bg-[#1a2537] text-[var(--muted)]",
    ok: "bg-[#14532d] text-green-300",
    warn: "bg-[#422006] text-amber-300",
    danger: "bg-[#450a0a] text-red-300",
    info: "bg-[#3a2a18] text-orange-200",
  };
  return <span className={clsx("px-2.5 py-0.5 rounded-full text-[11px] font-medium", tones[tone] ?? tones.default)}>{children}</span>;
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="text-center text-[var(--muted)] text-sm py-8">{children}</div>;
}

export function LayerTag({ layer }: { layer: string }) {
  const c: Record<string, string> = { network: "#60a5fa", process: "#a78bfa", twin: "#34d399", watermark: "#fbbf24" };
  return <span className="px-1.5 py-0.5 rounded text-[10px] font-semibold uppercase"
    style={{ background: (c[layer] ?? "#64748b") + "22", color: c[layer] ?? "#94a3b8" }}>{layer}</span>;
}
