import type { PlantState } from "../types/api";
import { alarmColor } from "./ui";

/** Schematic P&ID of the primary loop + IHX + secondary loop + generator.
 *  Live sensor values and actuator outputs drive colour, labels and flow animation. */
export function ProcessFlow({ ps }: { ps: PlantState | null }) {
  const S = (id: string) => ps?.sensors[id];
  const A = (id: string) => ps?.actuators[id];
  const val = (id: string, d = 1) => {
    const s = S(id); return s?.value != null ? s.value.toFixed(d) : "—";
  };
  const col = (id: string) => { const s = S(id); return s ? alarmColor(s.alarm) : "#64748b"; };
  const flowing = (id: string, thr = 2) => (A(id)?.output ?? 0) > thr;
  const running = !!ps?.running;

  const pumpColor = (id: string) => (flowing(id) && running ? "#22c55e" : "#475569");

  return (
    <svg viewBox="0 0 920 440" className="w-full" style={{ maxHeight: 440 }}>
      <defs>
        <linearGradient id="hot" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0" stopColor="#ef4444" /><stop offset="1" stopColor="#f97316" />
        </linearGradient>
        <marker id="arrow" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto">
          <path d="M0,0 L6,3 L0,6 Z" fill="#64748b" />
        </marker>
      </defs>

      {/* ---------------- primary loop ---------------- */}
      <Pipe d="M170,110 L170,70 L300,70" active={flowing("P-101") && running} color="#ef4444" />
      <Pipe d="M300,70 L300,120" active={flowing("P-101") && running} color="#ef4444" />
      <Pipe d="M300,230 L300,300 L170,300 L170,240" active={flowing("P-101") && running} color="#38bdf8" />
      <Pipe d="M110,210 L110,300 L130,300" active={flowing("P-101") && running} color="#38bdf8" />
      <Pipe d="M110,160 L110,110 L130,110" active={flowing("P-101") && running} color="#ef4444" />

      {/* boiler vessel */}
      <g>
        <rect x="40" y="110" width="70" height="100" rx="8" fill="#1a1016" stroke={col("TT-103")} strokeWidth="2" />
        <rect x="46" y={130} width="58" height={74} rx="4" fill="url(#hot)" opacity="0.25" />
        {/* heater coil */}
        <path d="M52,195 h46 M52,185 h46 M52,175 h46" stroke={(A("HTR-101")?.output ?? 0) > 5 ? "#f97316" : "#52525b"}
          strokeWidth="2.5" fill="none" />
        <Label x={75} y={100} text="Boiler" />
        <Value x={75} y={160} text={`${val("TT-103")}°C`} color={col("TT-103")} />
        <Value x={75} y={226} text={`${val("PT-102", 2)} bar`} small />
      </g>

      {/* primary pump */}
      <Pump cx={170} cy={225} color={pumpColor("P-101")} spin={flowing("P-101") && running} />
      <Label x={170} y={258} text="P-101" />
      <Value x={170} y={272} text={`${(A("P-101")?.output ?? 0).toFixed(0)}% · ${val("FT-101", 1)}kg/s`} small />

      {/* flow control valve */}
      <Valve cx={300} cy={175} open={(A("FCV-101")?.output ?? 0) > 5} />
      <Label x={330} y={178} text="FCV-101" anchor="start" />

      {/* hot-leg sensor */}
      <SensorTag x={250} y={55} id="TT-101" text={`${val("TT-101")}°C`} color={col("TT-101")} susp={S("TT-101")?.suspicious} />

      {/* ---------------- intermediate heat exchanger ---------------- */}
      <g>
        <rect x="300" y="120" width="54" height="110" rx="6" fill="#2a2a2e" stroke="#52525b" strokeWidth="1.5" />
        <path d="M312,130 v90 M327,130 v90 M342,130 v90" stroke="#475569" strokeWidth="1.5" />
        <Label x={327} y={248} text="IHX" />
      </g>

      {/* ---------------- secondary loop ---------------- */}
      <Pipe d="M354,145 L440,145 L440,120" active={flowing("P-201") && running} color="#f59e0b" />
      <Pipe d="M440,230 L440,205 M354,205 L440,205" active={flowing("P-201") && running} color="#38bdf8" />
      <Pipe d="M500,110 L560,110" active={flowing("P-201") && running} color="#f59e0b" />
      <Pipe d="M560,215 L500,215 L500,215" active={flowing("P-201") && running} color="#38bdf8" />
      <Pipe d="M440,215 L440,260 L410,260" active={flowing("P-201") && running} color="#38bdf8" />

      {/* secondary pump */}
      <Pump cx={390} cy={260} color={pumpColor("P-201")} spin={flowing("P-201") && running} r={16} />
      <Label x={390} y={288} text="P-201" />

      {/* air cooler */}
      <g>
        <rect x="440" y="95" width="60" height="120" rx="6" fill="#2a2a2e" stroke="#52525b" strokeWidth="1.5" />
        <Fan cx={470} cy={125} spin={(A("FAN-201")?.output ?? 0) > 5 && running} />
        <Label x={470} y={208} text="Air cooler" />
        <Value x={470} y={160} text={`${val("TT-202")}°C`} color={col("TT-202")} small />
      </g>
      <SensorTag x={395} y={185} id="TT-201" text={`${val("TT-201")}°C`} color={col("TT-201")} />

      {/* ---------------- turbine + generator ---------------- */}
      <g>
        <path d="M560,95 L600,80 L600,140 L560,125 Z" fill="#1e293b" stroke="#475569" />
        <Label x={580} y={70} text="Turbine" />
        <circle cx={660} cy={110} r={32} fill="#2a2a2e" stroke="#34d399" strokeWidth="2" />
        <text x={660} y={106} textAnchor="middle" fontSize="11" fill="#34d399" fontWeight="700">GEN</text>
        <text x={660} y={120} textAnchor="middle" fontSize="12" fill="#e2e8f0" className="tnum">{val("JT-201", 0)}kW</text>
        <Pipe d="M600,110 L628,110" active={running} color="#34d399" />
        <text x={660} y={158} textAnchor="middle" fontSize="10" fill="#64748b" className="tnum">
          {val("ST-201", 0)} rpm
        </text>
      </g>

      {/* ---------------- balance of plant (compact) ---------------- */}
      <BopBox x={40} y={330} w={190} title="Water treatment" rows={[
        [`Treated level`, `${val("LT-302", 2)} m`, col("LT-302")],
        [`Turbidity`, `${val("AT-301", 2)} NTU`, col("AT-301")],
        [`Chlorine`, `${val("AT-302", 2)} mg/L`, col("AT-302")],
      ]} />
      <BopBox x={250} y={330} w={190} title="Chemical mixing" rows={[
        [`Reactor temp`, `${val("TT-401")}°C`, col("TT-401")],
        [`Level`, `${val("LT-401", 0)}%`, col("LT-401")],
        [`Agitator I`, `${val("IT-401", 1)} A`, col("IT-401")],
      ]} />
      <BopBox x={460} y={330} w={190} title="Pipeline / tanks" rows={[
        [`Flow`, `${val("FT-501", 0)} m³/h`, col("FT-501")],
        [`Tank 501`, `${val("LT-501", 2)} m`, col("LT-501")],
        [`Disch. press.`, `${val("PT-501", 1)} bar`, col("PT-501")],
      ]} />
      <BopBox x={670} y={330} w={210} title="Motor / generator" rows={[
        [`Gen output`, `${val("JT-201", 0)} kW`, col("JT-201")],
        [`Gen speed`, `${val("ST-201", 0)} rpm`, col("ST-201")],
        [`Xfer motor T`, `${val("TT-501")}°C`, col("TT-501")],
      ]} />

      {/* heater readout */}
      <g>
        <rect x={668} y={200} width={212} height={64} rx={8} fill="#202023" stroke="#3a3a40" />
        <text x={678} y={220} fontSize="10" fill="#7d8aa0">HEATER (SCR) HTR-101</text>
        <text x={678} y={244} fontSize="20" fill="#f97316" fontWeight="700" className="tnum">
          {(A("HTR-101")?.output ?? 0).toFixed(0)}%
        </text>
        <text x={760} y={244} fontSize="12" fill="#94a3b8" className="tnum">{val("JT-101", 0)} kW</text>
        {A("HTR-101")?.tripped && <text x={830} y={244} fontSize="11" fill="#ef4444" fontWeight="700">TRIP</text>}
      </g>
    </svg>
  );
}

function Pipe({ d, active, color }: { d: string; active: boolean; color: string }) {
  return (
    <>
      <path d={d} fill="none" stroke="#3f3f46" strokeWidth="6" strokeLinecap="round" />
      {active && <path d={d} fill="none" stroke={color} strokeWidth="3" strokeLinecap="round" className="flow-anim" opacity="0.9" />}
    </>
  );
}
function Pump({ cx, cy, color, spin, r = 18 }: { cx: number; cy: number; color: string; spin: boolean; r?: number }) {
  return (
    <g>
      <circle cx={cx} cy={cy} r={r} fill="#2a2a2e" stroke={color} strokeWidth="2.5" />
      <g style={{ transformOrigin: `${cx}px ${cy}px`, animation: spin ? "spin 1.1s linear infinite" : undefined }}>
        <path d={`M${cx},${cy - r + 3} L${cx},${cy + r - 3} M${cx - r + 3},${cy} L${cx + r - 3},${cy}`}
          stroke={color} strokeWidth="2.5" />
      </g>
      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </g>
  );
}
function Fan({ cx, cy, spin }: { cx: number; cy: number; spin: boolean }) {
  return (
    <g style={{ transformOrigin: `${cx}px ${cy}px`, animation: spin ? "spin 0.8s linear infinite" : undefined }}>
      <circle cx={cx} cy={cy} r={14} fill="none" stroke="#475569" strokeWidth="1.5" />
      <path d={`M${cx},${cy} L${cx},${cy - 12} M${cx},${cy} L${cx + 10},${cy + 6} M${cx},${cy} L${cx - 10},${cy + 6}`}
        stroke={spin ? "#38bdf8" : "#475569"} strokeWidth="2.5" />
      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </g>
  );
}
function Valve({ cx, cy, open }: { cx: number; cy: number; open: boolean }) {
  return (
    <g>
      <path d={`M${cx - 10},${cy - 8} L${cx + 10},${cy + 8} L${cx + 10},${cy - 8} L${cx - 10},${cy + 8} Z`}
        fill={open ? "#14532d" : "#450a0a"} stroke={open ? "#22c55e" : "#ef4444"} strokeWidth="1.5" />
    </g>
  );
}
function Label({ x, y, text, anchor = "middle" }: { x: number; y: number; text: string; anchor?: string }) {
  return <text x={x} y={y} textAnchor={anchor as any} fontSize="10" fill="#7d8aa0" fontWeight="600">{text}</text>;
}
function Value({ x, y, text, color = "#e2e8f0", small }: { x: number; y: number; text: string; color?: string; small?: boolean }) {
  return <text x={x} y={y} textAnchor="middle" fontSize={small ? 10 : 13} fill={color} fontWeight="700" className="tnum">{text}</text>;
}
function SensorTag({ x, y, id, text, color, susp }: { x: number; y: number; id: string; text: string; color: string; susp?: boolean }) {
  return (
    <g>
      <rect x={x - 32} y={y - 12} width={64} height={24} rx={5} fill="#202023"
        stroke={susp ? "#f59e0b" : color} strokeWidth={susp ? 2 : 1} strokeDasharray={susp ? "3 2" : undefined} />
      <text x={x} y={y - 2} textAnchor="middle" fontSize="8" fill="#64748b">{id}</text>
      <text x={x} y={y + 8} textAnchor="middle" fontSize="10" fill={color} fontWeight="700" className="tnum">{text}</text>
    </g>
  );
}
function BopBox({ x, y, w, title, rows }: { x: number; y: number; w: number; title: string; rows: [string, string, string][] }) {
  return (
    <g>
      <rect x={x} y={y} width={w} height={96} rx={8} fill="#202023" stroke="#3a3a40" />
      <text x={x + 10} y={y + 17} fontSize="10" fill="#7d8aa0" fontWeight="700" style={{ textTransform: "uppercase", letterSpacing: "0.05em" }}>{title}</text>
      {rows.map((r, i) => (
        <g key={i}>
          <text x={x + 10} y={y + 38 + i * 19} fontSize="11" fill="#94a3b8">{r[0]}</text>
          <text x={x + w - 10} y={y + 38 + i * 19} textAnchor="end" fontSize="11" fill={r[2]} fontWeight="600" className="tnum">{r[1]}</text>
        </g>
      ))}
    </g>
  );
}
