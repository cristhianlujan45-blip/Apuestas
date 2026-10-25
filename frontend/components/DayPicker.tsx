"use client";
import { useMemo } from "react";
import { useApi } from "@/lib/useApi";

const todayBogota = () => new Date().toLocaleDateString("en-CA", { timeZone: "America/Bogota" });
const addDays = (d: string, n: number) => {
  const t = new Date(`${d}T12:00:00-05:00`);
  t.setUTCDate(t.getUTCDate() + n);
  return t.toLocaleDateString("en-CA", { timeZone: "America/Bogota" });
};
export function dayLabel(d: string) {
  const t = todayBogota();
  if (d === t) return "Hoy";
  if (d === addDays(t, 1)) return "Mañana";
  if (d === addDays(t, -1)) return "Ayer";
  const s = new Date(`${d}T12:00:00-05:00`).toLocaleDateString("es-CO", { weekday: "short", day: "numeric", month: "short", timeZone: "America/Bogota" });
  return s.charAt(0).toUpperCase() + s.slice(1);
}
export { todayBogota };

/**
 * Selector de días (hora de Colombia) con el número de partidos de cada día.
 * ``multiple``: permite elegir varios días (PARLAY); vacío = todos.
 */
export default function DayPicker({ value, onChange, multiple = false, futureOnly = false, sport }: {
  value: string[]; onChange: (v: string[]) => void; multiple?: boolean; futureOnly?: boolean; sport?: string;
}) {
  const { data } = useApi(`/events/days${sport ? `?sport=${sport}` : ""}`, [sport], 300000);
  const days = useMemo(() => {
    const t = todayBogota();
    return ((data?.days || []) as { date: string; count: number; finished: number }[])
      .filter((d) => !futureOnly || (d.date >= t && d.count > d.finished));
  }, [data, futureOnly]);
  const toggle = (d: string) => {
    if (!multiple) return onChange([d]);
    onChange(value.includes(d) ? value.filter((x) => x !== d) : [...value, d].sort());
  };
  return (
    <div>
      <div className="flex gap-1 overflow-x-auto pb-1">
        {multiple && <button className={`tab shrink-0 ${!value.length ? "tab-active" : ""}`} onClick={() => onChange([])}>Todos los días</button>}
        {days.map((d) => (
          <button key={d.date} onClick={() => toggle(d.date)} className={`tab shrink-0 ${value.includes(d.date) ? "tab-active" : ""}`}>
            {dayLabel(d.date)} <span className="num text-[11px] text-ink-muted">{futureOnly ? d.count - d.finished : d.count}</span>
          </button>
        ))}
      </div>
      <label className="mt-2 flex items-center gap-2 text-xs text-ink-2">Otro día
        <input type="date" className="input w-auto py-1" min={futureOnly ? todayBogota() : undefined}
          onChange={(e) => e.target.value && toggle(e.target.value)} />
      </label>
    </div>
  );
}
