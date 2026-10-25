"use client";
import { SPORT_LABEL } from "@/lib/format";
import { useApi } from "@/lib/useApi";

export const SPORTS = ["football", "basketball", "tennis", "baseball", "volleyball"];

/**
 * Elegir uno o varios deportes. Muestra cuántos partidos por jugar tiene cada uno; los que no
 * tienen datos se ven atenuados y explican qué falta.
 */
export default function SportPicker({ value, onChange, multiple = true, allLabel }: {
  value: string[]; onChange: (v: string[]) => void; multiple?: boolean; allLabel?: string;
}) {
  const { data } = useApi("/sports", [], 300000);
  const info = data?.sports || {};
  const toggle = (s: string) => {
    if (!multiple) return onChange(value[0] === s ? [] : [s]);
    onChange(value.includes(s) ? value.filter((x) => x !== s) : [...value, s]);
  };
  const empty = SPORTS.filter((s) => info[s] && info[s].upcoming === 0);
  return (
    <div>
      <div className="flex flex-wrap gap-1">
        {allLabel && <button className={`tab ${!value.length ? "tab-active" : ""}`} onClick={() => onChange([])}>{allLabel}</button>}
        {SPORTS.map((s) => {
          const n = info[s]?.upcoming;
          return (
            <button key={s} onClick={() => toggle(s)} title={n === 0 ? "Sin partidos en los datos" : undefined}
              className={`tab ${value.includes(s) ? "tab-active" : ""} ${n === 0 ? "tab-off" : ""}`}>
              {SPORT_LABEL[s]}{n != null && <span className="ml-1 num text-[11px] text-ink-muted">{n}</span>}
            </button>
          );
        })}
      </div>
      {empty.length > 0 && (
        <p className="mt-1 text-[11px] text-ink-muted">
          {empty.map((s) => SPORT_LABEL[s]).join(", ")}: sin partidos por ahora. Llegan con el feed multideporte de cuotas
          colombianas (<code>ODDS_API_NET_KEY</code>); sin modelo propio se valoran con el consenso sin margen de las casas.
        </p>
      )}
    </div>
  );
}
