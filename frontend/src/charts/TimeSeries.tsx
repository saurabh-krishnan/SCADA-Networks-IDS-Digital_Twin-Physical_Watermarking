import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend, ReferenceLine } from "recharts";

export interface Series { key: string; label: string; color: string; dash?: string; }

export function TimeSeries({ data, series, height = 220, unit, yDomain, refLines }: {
  data: any[]; series: Series[]; height?: number; unit?: string;
  yDomain?: [number | string, number | string]; refLines?: { y: number; color: string; label?: string }[];
}) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data} margin={{ top: 6, right: 12, bottom: 2, left: -8 }}>
        <CartesianGrid stroke="#3a3a40" strokeDasharray="2 4" />
        <XAxis dataKey="t" stroke="#71717a" tick={{ fontSize: 10 }} minTickGap={40}
          tickFormatter={(v) => `${v}s`} />
        <YAxis stroke="#71717a" tick={{ fontSize: 10 }} width={46} domain={yDomain ?? ["auto", "auto"]}
          tickFormatter={(v) => (typeof v === "number" ? v.toFixed(v < 10 ? 1 : 0) : v)} />
        <Tooltip contentStyle={{ background: "#202023", border: "1px solid #3a3a40", borderRadius: 8, fontSize: 12 }}
          labelFormatter={(v) => `t = ${v}s`} formatter={(val: any, name: any) => [
            typeof val === "number" ? val.toFixed(3) : val, name]} />
        {series.length > 1 && <Legend wrapperStyle={{ fontSize: 11 }} />}
        {refLines?.map((r, i) => (
          <ReferenceLine key={i} y={r.y} stroke={r.color} strokeDasharray="4 4"
            label={{ value: r.label, fill: r.color, fontSize: 10, position: "insideTopRight" }} />
        ))}
        {series.map((s) => (
          <Line key={s.key} type="monotone" dataKey={s.key} name={s.label} stroke={s.color}
            dot={false} strokeWidth={1.6} strokeDasharray={s.dash} isAnimationActive={false}
            connectNulls unit={unit} />
        ))}
      </LineChart>
    </ResponsiveContainer>
  );
}
