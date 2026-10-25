"use client";
import { Check, Plus } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { buildBoard, GROUPS, rowOdds, sameGameCombos, type BoardRow } from "@/lib/board";
import { odds, pct, signedPct } from "@/lib/format";
import { addLegs, loadSlip, toggleLeg, type SlipLeg } from "@/lib/slip";
import { Card, Empty } from "./ui";

function useSlipKeys(eventId: number) {
  const [keys, setKeys] = useState<string[]>([]);
  useEffect(() => {
    const f = () => setKeys(loadSlip().filter((l) => l.event_id === eventId).map((l) => l.selection_key));
    f();
    window.addEventListener("slip", f);
    return () => window.removeEventListener("slip", f);
  }, [eventId]);
  return keys;
}

const toLeg = (ev: any, r: BoardRow): SlipLeg => {
  const o = rowOdds(r);
  return { event_id: ev.id, event: ev.label, start_time: ev.start_time, home: ev.home, away: ev.away, selection_key: r.key,
    label: r.label, odds: o?.odds ?? null, operator: o?.operator ?? null, source: o?.source ?? "manual", p: r.p };
};

/** Todas las cuotas del partido con la mejor casa y un botón para añadir al boleto. */
export default function MatchBoard({ detail }: { detail: any }) {
  const ev = detail.event;
  const rows = useMemo(() => buildBoard(detail), [detail]);
  const groups = GROUPS.filter((g) => rows.some((r) => r.group === g));
  const [group, setGroup] = useState(groups[0] || "Resultado");
  const keys = useSlipKeys(ev.id);
  const [target, setTarget] = useState(3);
  const combos = useMemo(() => sameGameCombos(rows, detail.matrix || undefined, target), [rows, detail.matrix, target]);
  if (!rows.length || ev.status === "finished") return null;
  const hasCO = rows.some((r) => r.best);
  return (
    <>
      <Card title="Cuotas del partido" right={keys.length > 0 && <Link href="/boleto" className="btn-primary px-3 py-1 text-xs">Ver boleto ({keys.length})</Link>}>
        <p className="mb-2 text-xs text-ink-2">Toque <b>+</b> para añadir una selección a su boleto. Puede añadir varias de este partido o de otros.
          {!hasCO && " Aún no hay cuotas de casas colombianas: se muestra la cuota de referencia internacional y la cuota justa del modelo."}</p>
        <div className="mb-2 flex gap-1 overflow-x-auto pb-1">
          {groups.map((g) => <button key={g} className={`tab shrink-0 ${group === g ? "tab-active" : ""}`} onClick={() => setGroup(g)}>{g}</button>)}
        </div>
        <ul className="divide-y divide-line">
          {rows.filter((r) => r.group === group).map((r) => {
            const on = keys.includes(r.key);
            const o = rowOdds(r);
            const ev_ = o && r.p != null ? o.odds * r.p - 1 : null;
            return (
              <li key={r.key} className="flex items-center gap-3 py-2">
                <div className="min-w-0 flex-1">
                  <div className="text-sm font-medium">{r.label}</div>
                  <div className="text-[11px] text-ink-muted num">
                    {r.p != null ? <>Probabilidad {pct(r.p, 0)} · justa {odds(r.fair)}</> : "Sin modelo para este mercado"}
                    {r.best ? <> · mejor en <b className="text-ink-2">{r.best.operator_name}</b></> : r.ref ? " · referencia internacional" : ""}
                  </div>
                </div>
                <div className="w-16 shrink-0 text-right">
                  <div className={`text-base font-semibold num ${r.best ? "" : "text-ink-2"}`}>{o ? odds(o.odds) : "—"}</div>
                  {ev_ != null && <div className={`text-[11px] num ${ev_ > 0 ? "text-good" : "text-ink-muted"}`}>{signedPct(ev_)}</div>}
                </div>
                <button onClick={() => toggleLeg(toLeg(ev, r))} aria-label={on ? "Quitar del boleto" : "Añadir al boleto"}
                  className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border ${on ? "border-accent bg-accent text-white" : "border-line-strong text-ink-2"}`}>
                  {on ? <Check size={18} /> : <Plus size={18} />}
                </button>
              </li>
            );
          })}
        </ul>
        <p className="mt-2 text-[11px] text-ink-muted">El porcentaje verde o gris es la ganancia esperada a largo plazo con esa cuota: verde si paga más de lo justo.</p>
      </Card>

      {detail.matrix && (
        <Card title="Combinada automática de este partido">
          <p className="mb-2 text-xs text-ink-2">Elija la cuota y la app busca 2 o 3 selecciones de este partido con la mayor probabilidad de acertar juntas (calculada con el marcador, no como si fueran independientes).</p>
          <div className="mb-3 grid grid-cols-5 gap-1">
            {[2, 3, 4, 6, 10].map((t) => <button key={t} className={`tab px-0 num ${target === t ? "tab-active" : ""}`} onClick={() => setTarget(t)}>{t}</button>)}
          </div>
          {!combos.length ? <Empty>No hay una combinación de este partido cerca de cuota {target}. Pruebe otra cuota.</Empty> : (
            <ul className="space-y-2">
              {combos.map((c, i) => (
                <li key={i} className="rounded-lg border border-line p-3">
                  <div className="flex items-start justify-between gap-3">
                    <ul className="min-w-0 space-y-0.5 text-sm">{c.legs.map((l) => <li key={l.key}>• {l.label} <span className="text-ink-muted num">{odds(rowOdds(l)!.odds)}</span></li>)}</ul>
                    <div className="shrink-0 text-right"><div className="text-lg font-semibold num">{odds(c.odds)}</div>
                      <div className="text-[11px] text-ink-2 num">acierta {pct(c.p, 0)}</div></div>
                  </div>
                  <div className="mt-2 flex items-center justify-between gap-2">
                    <span className="text-[11px] text-ink-2 num">Vale la pena si su casa paga más de <b className="text-ink">{odds(c.fair)}</b></span>
                    <button className="btn-ghost px-3 py-1 text-xs" onClick={() => addLegs(c.legs.map((l) => toLeg(ev, l)))}>Añadir al boleto</button>
                  </div>
                </li>
              ))}
            </ul>
          )}
          <p className="mt-2 text-[11px] text-ink-muted">La cuota mostrada es el producto de las cuotas sueltas. En el «creador de apuestas» (Bet Builder) de su casa la cuota real suele ser menor, porque las selecciones del mismo partido están relacionadas: compárela con la cuota justa.</p>
        </Card>
      )}
    </>
  );
}
