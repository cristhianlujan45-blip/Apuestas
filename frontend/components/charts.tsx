"use client";
import {
  Bar, BarChart, CartesianGrid, Cell, ComposedChart, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer,
  Scatter, Tooltip, XAxis, YAxis,
} from "recharts";
import { SERIES } from "@/lib/format";

const GRID = "#2c2c2a";
const AXIS = "#383835";
const TICK = { fill: "#898781", fontSize: 11 };

function Tip({ active, payload, label, fmt }: any) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-lg border border-line-strong bg-surface-2 px-3 py-2 text-xs shadow-lg">
      {label != null && <div className="mb-1 text-ink-2">{label}</div>}
      {payload.map((p: any) => (
        <div key={p.dataKey + p.name} className="flex items-center gap-2 num">
          <span className="inline-block h-2 w-2 rounded-sm" style={{ background: p.color || p.fill }} />
          <span className="text-ink-2">{p.name}</span>
          <span className="ml-auto text-ink">{fmt ? fmt(p.value) : p.value}</span>
        </div>
      ))}
    </div>
  );
}

/** Fiabilidad: probabilidad media predicha vs frecuencia observada (diagonal = calibración perfecta). */
export function CalibrationChart({ rows, height = 260 }: { rows: { mean_predicted: number; observed: number; n: number }[]; height?: number }) {
  const data = rows.map((r) => ({ x: +(r.mean_predicted * 100).toFixed(1), y: +(r.observed * 100).toFixed(1), n: r.n }));
  return (
    <ResponsiveContainer width="100%" height={height}>
      <ComposedChart data={data} margin={{ top: 8, right: 12, bottom: 18, left: 0 }}>
        <CartesianGrid stroke={GRID} vertical={false} />
        <XAxis type="number" dataKey="x" domain={[0, 100]} tick={TICK} stroke={AXIS} unit="%"
          label={{ value: "Probabilidad predicha", position: "insideBottom", offset: -10, fill: "#898781", fontSize: 11 }} />
        <YAxis type="number" domain={[0, 100]} tick={TICK} stroke={AXIS} unit="%" width={44} />
        <ReferenceLine segment={[{ x: 0, y: 0 }, { x: 100, y: 100 }]} stroke="#898781" strokeDasharray="4 4" />
        <Tooltip content={({ active, payload }: any) => active && payload?.length ? (
          <div className="rounded-lg border border-line-strong bg-surface-2 px-3 py-2 text-xs num">
            <div>Predicha: {payload[0].payload.x}%</div>
            <div>Observada: {payload[0].payload.y}%</div>
            <div className="text-ink-muted">{payload[0].payload.n} partidos</div>
          </div>) : null} />
        <Line dataKey="y" name="Observada" stroke={SERIES[0]} strokeWidth={2} dot={{ r: 4, fill: SERIES[0], stroke: "#1a1a19", strokeWidth: 2 }} isAnimationActive={false} />
        <Scatter dataKey="y" fill={SERIES[0]} />
      </ComposedChart>
    </ResponsiveContainer>
  );
}

/** Evolución de cuotas por operador (máx. 6 series + leyenda). */
export function OddsHistoryChart({ points, height = 260 }: { points: { operator: string; odds: number; captured_at: string }[]; height?: number }) {
  const ops = Array.from(new Set(points.map((p) => p.operator))).slice(0, 6);
  const byTime = new Map<string, any>();
  for (const p of points) {
    if (!ops.includes(p.operator)) continue;
    const t = new Date(p.captured_at).toLocaleString("es-CO", { timeZone: "America/Bogota", day: "2-digit", hour: "2-digit", minute: "2-digit" });
    const row = byTime.get(t) || { t };
    row[p.operator] = p.odds;
    byTime.set(t, row);
  }
  const data = Array.from(byTime.values());
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data} margin={{ top: 8, right: 12, bottom: 4, left: 0 }}>
        <CartesianGrid stroke={GRID} vertical={false} />
        <XAxis dataKey="t" tick={TICK} stroke={AXIS} />
        <YAxis tick={TICK} stroke={AXIS} domain={["auto", "auto"]} width={44} />
        <Tooltip content={<Tip fmt={(v: number) => v?.toFixed(2)} />} />
        {ops.length > 1 && <Legend wrapperStyle={{ fontSize: 12, color: "#c3c2b7" }} />}
        {ops.map((op, i) => (
          <Line key={op} dataKey={op} name={op} stroke={SERIES[i]} strokeWidth={2} dot={{ r: 3 }} connectNulls isAnimationActive={false} />
        ))}
      </LineChart>
    </ResponsiveContainer>
  );
}

/** Histograma de una distribución simulada. */
export function DistributionChart({ hist, height = 200, unit = "", highlight }: {
  hist: { x: number; p: number }[]; height?: number; unit?: string; highlight?: (x: number) => boolean;
}) {
  const data = hist.map((h) => ({ x: Number.isInteger(h.x) ? h.x : +h.x.toFixed(1), p: +(h.p * 100).toFixed(2) }));
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} margin={{ top: 8, right: 8, bottom: 4, left: 0 }} barCategoryGap={2}>
        <CartesianGrid stroke={GRID} vertical={false} />
        <XAxis dataKey="x" tick={TICK} stroke={AXIS} unit={unit} />
        <YAxis tick={TICK} stroke={AXIS} unit="%" width={40} />
        <Tooltip content={<Tip fmt={(v: number) => `${v}%`} />} cursor={{ fill: "#2c2c2a" }} />
        <Bar dataKey="p" name="Probabilidad" radius={[4, 4, 0, 0]} isAnimationActive={false}>
          {data.map((d, i) => <Cell key={i} fill={highlight && highlight(d.x) ? SERIES[1] : SERIES[0]} />)}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

/** Comparación de modelos por una métrica (menor es mejor). Serie única, sin leyenda. */
export function ModelBarChart({ rows, metric = "Log loss", height }: { rows: { name: string; value: number; champion?: boolean }[]; metric?: string; height?: number }) {
  const data = [...rows].sort((a, b) => a.value - b.value);
  const min = Math.min(...data.map((d) => d.value));
  const max = Math.max(...data.map((d) => d.value));
  const pad = (max - min) * 0.4 || 0.01;
  return (
    <ResponsiveContainer width="100%" height={height ?? Math.max(160, data.length * 30)}>
      <BarChart data={data} layout="vertical" margin={{ top: 4, right: 40, bottom: 4, left: 10 }} barCategoryGap={4}>
        <CartesianGrid stroke={GRID} horizontal={false} />
        <XAxis type="number" domain={[+(min - pad).toFixed(3), +(max + pad / 4).toFixed(3)]} tick={TICK} stroke={AXIS} />
        <YAxis type="category" dataKey="name" tick={{ ...TICK, fill: "#c3c2b7" }} stroke={AXIS} width={130} />
        <Tooltip content={<Tip fmt={(v: number) => v.toFixed(4)} />} cursor={{ fill: "#2c2c2a" }} />
        <Bar dataKey="value" name={metric} radius={[0, 4, 4, 0]} isAnimationActive={false}
          label={{ position: "right", fill: "#c3c2b7", fontSize: 11, formatter: (v: number) => v.toFixed(4) }}>
          {data.map((d, i) => <Cell key={i} fill={d.champion ? SERIES[2] : SERIES[0]} />)}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

export function RollingLine({ values, height = 180, name = "Log loss móvil", reference }: { values: number[]; height?: number; name?: string; reference?: number }) {
  const data = values.map((v, i) => ({ i, v: +v.toFixed(4) }));
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data} margin={{ top: 8, right: 12, bottom: 4, left: 0 }}>
        <CartesianGrid stroke={GRID} vertical={false} />
        <XAxis dataKey="i" tick={TICK} stroke={AXIS} />
        <YAxis tick={TICK} stroke={AXIS} domain={["auto", "auto"]} width={50} />
        <Tooltip content={<Tip fmt={(v: number) => v.toFixed(4)} />} />
        {reference != null && <ReferenceLine y={reference} stroke="#898781" strokeDasharray="4 4" label={{ value: "esperada", fill: "#898781", fontSize: 11 }} />}
        <Line dataKey="v" name={name} stroke={SERIES[0]} strokeWidth={2} dot={false} isAnimationActive={false} />
      </LineChart>
    </ResponsiveContainer>
  );
}

/** Evolución de una banca (COP) con la línea del capital inicial como referencia. */
export function BankrollChart({ points, start, height = 220 }: { points: { label: string; bankroll: number }[]; start: number; height?: number }) {
  const fmt = (v: number) => `$${Math.round(v).toLocaleString("es-CO")}`;
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={points} margin={{ top: 8, right: 12, bottom: 4, left: 0 }}>
        <CartesianGrid stroke={GRID} vertical={false} />
        <XAxis dataKey="label" tick={TICK} stroke={AXIS} minTickGap={40} />
        <YAxis tick={TICK} stroke={AXIS} domain={["auto", "auto"]} width={72} tickFormatter={(v) => `${Math.round(v / 1000)}k`} />
        <Tooltip content={<Tip fmt={fmt} />} />
        <ReferenceLine y={start} stroke="#898781" strokeDasharray="4 4" />
        <Line dataKey="bankroll" name="Banca" stroke={SERIES[2]} strokeWidth={2} dot={false} isAnimationActive={false} />
      </LineChart>
    </ResponsiveContainer>
  );
}
