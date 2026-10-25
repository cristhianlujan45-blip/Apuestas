"use client";
import { Trash2 } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import StakeHint from "@/components/StakeHint";
import { Card, Empty, PageHeader } from "@/components/ui";
import { api } from "@/lib/api";
import { addBet } from "@/lib/bets";
import { bogota, cop, odds, pct, signedPct } from "@/lib/format";
import { clearSlip, evaluateSlip, loadSlip, removeLeg, setLegOdds, type SlipEval, type SlipLeg } from "@/lib/slip";

export default function Boleto() {
  const [legs, setLegs] = useState<SlipLeg[]>([]);
  const [ev, setEv] = useState<SlipEval | null>(null);
  const [stake, setStake] = useState(10000);
  const [names, setNames] = useState<Record<string, string>>({});
  useEffect(() => {
    const f = () => setLegs(loadSlip());
    f();
    window.addEventListener("slip", f);
    api("/operators").then((d) => setNames(Object.fromEntries(d.operators.map((o: any) => [o.key, o.name])))).catch(() => {});
    return () => window.removeEventListener("slip", f);
  }, []);
  useEffect(() => { evaluateSlip(legs, names).then(setEv).catch(() => setEv(null)); }, [legs, names]);
  const byEvent = legs.reduce((m: Record<number, SlipLeg[]>, l) => ((m[l.event_id] ||= []).push(l), m), {});
  const house = ev?.houses[0];

  return (
    <div className="space-y-4">
      <PageHeader title="Mi boleto" subtitle="Las selecciones que usted eligió, de uno o varios partidos. Vea la cuota total, la probabilidad real de acertar todas y cuánto ganaría." />
      {!legs.length ? (
        <Card><Empty>Su boleto está vacío. Entre a un partido y toque <b>+</b> en las cuotas que quiera.
          <div className="mt-3"><Link href="/partidos" className="btn-primary">Ver partidos</Link></div></Empty></Card>
      ) : (
        <div className="grid gap-4 lg:grid-cols-3">
          <div className="space-y-3 lg:col-span-2">
            {Object.values(byEvent).map((ls) => (
              <Card key={ls[0].event_id}>
                <div className="mb-2 flex items-center justify-between gap-2">
                  <Link href={`/partido?id=${ls[0].event_id}`} className="min-w-0 truncate font-medium hover:text-accent">{ls[0].event}</Link>
                  <span className="shrink-0 text-[11px] text-ink-muted">{bogota(ls[0].start_time)}</span>
                </div>
                <ul className="divide-y divide-line">
                  {ls.map((l) => (
                    <li key={l.selection_key} className="flex items-center gap-3 py-2">
                      <div className="min-w-0 flex-1">
                        <div className="text-sm">{l.label}</div>
                        <div className="text-[11px] text-ink-muted">{l.p != null && `Probabilidad ${pct(l.p, 0)} · `}
                          {l.source === "casa" ? `cuota de ${names[l.operator || ""] || l.operator}` : l.source === "referencia" ? "cuota de referencia: confírmela" : "cuota escrita por usted"}</div>
                      </div>
                      <input className="input !w-20 shrink-0 text-right num" inputMode="decimal" aria-label="Cuota" defaultValue={l.odds ?? ""} placeholder="cuota"
                        onBlur={(e) => { const v = parseFloat(e.target.value.replace(",", ".")); setLegOdds(l.event_id, l.selection_key, v > 1 ? v : null); }} />
                      <button className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border border-line-strong text-ink-muted" aria-label="Quitar"
                        onClick={() => removeLeg(l.event_id, l.selection_key)}><Trash2 size={16} /></button>
                    </li>
                  ))}
                </ul>
              </Card>
            ))}
            <div className="flex flex-wrap gap-2">
              <Link href="/partidos" className="btn-ghost">+ Añadir de otro partido</Link>
              <button className="btn-ghost" onClick={() => { if (confirm("¿Vaciar el boleto?")) clearSlip(); }}>Vaciar boleto</button>
            </div>
          </div>

          <div className="space-y-3">
            <Card title="Resumen">
              <div className="grid grid-cols-2 gap-2 text-sm">
                <div className="rounded-lg bg-surface-2 p-2"><div className="text-xs text-ink-muted">Cuota total</div><div className="text-2xl font-semibold num">{ev?.total_odds ? odds(ev.total_odds) : "—"}</div></div>
                <div className="rounded-lg bg-surface-2 p-2"><div className="text-xs text-ink-muted">Probabilidad de acertar todas</div><div className="text-2xl font-semibold num">{ev?.p_win != null ? pct(ev.p_win) : "—"}</div></div>
                <div className="rounded-lg bg-surface-2 p-2"><div className="text-xs text-ink-muted">{ev?.same_event ? "Ganancia esperada*" : "Ganancia esperada"}</div>
                  <div className={`text-lg font-semibold num ${ev?.ev != null && ev.ev > 0 ? "text-good" : ""}`}>{ev?.ev != null ? signedPct(ev.ev) : "—"}</div></div>
                <div className="rounded-lg bg-surface-2 p-2"><div className="text-xs text-ink-muted">Cuota justa</div><div className="text-lg font-semibold num">{ev?.p_win ? odds(1 / ev.p_win) : "—"}</div></div>
              </div>
              <label className="label mt-3">Cuánto apostar (COP)</label>
              <input type="number" className="input" value={stake} onChange={(e) => setStake(+e.target.value)} />
              {ev?.same_event && ev.p_win ? <p className="mt-2 text-[11px] text-ink-muted">* Con selecciones del mismo partido, la casa calcula su propia cuota (suele ser menor). Vale la pena si le paga más de <b className="text-ink-2 num">{odds(1 / ev.p_win)}</b>.</p> : null}
              {ev?.total_odds && <p className="mt-2 text-sm num">Si acierta recibe <b>{cop(stake * ev.total_odds)}</b> (gana {cop(stake * (ev.total_odds - 1))})</p>}
              {ev?.p_win != null && ev.total_odds && <div className="mt-1"><StakeHint p={ev.p_win} odds={ev.total_odds} /></div>}
              <button className="btn-primary mt-3 w-full justify-center" disabled={!ev?.total_odds}
                onClick={() => {
                  addBet({ operator: house?.operator || legs.find((l) => l.operator)?.operator || "otra", stake_cop: stake, odds: ev!.total_odds!,
                    description: legs.length > 1 ? `Combinada de ${legs.length}` : legs[0].label,
                    legs: legs.map((l) => ({ event_id: l.event_id, event: l.event, selection_key: l.selection_key, selection: l.label, odds: l.odds || 0, start_time: l.start_time })) });
                  alert("Registrada en Mis apuestas. La app no coloca apuestas: regístrela solo si la hizo en su casa.");
                }}>Ya la hice: registrar en Mis apuestas</button>
            </Card>
            {ev && ev.houses.length > 0 && (
              <Card title="¿Qué casa paga más por este boleto?">
                <ul className="space-y-1 text-sm">{ev.houses.map((h, i) => (
                  <li key={h.operator} className="flex justify-between"><span>{i === 0 ? "🏆 " : ""}{h.name}</span><span className="num">{odds(h.total_odds)}</span></li>
                ))}</ul>
                <p className="mt-2 text-[11px] text-ink-muted">Solo aparecen las casas que ofrecen todas las selecciones. La combinada se hace en una sola casa.</p>
              </Card>
            )}
            {ev && ev.warnings.length > 0 && (
              <Card title="Tenga en cuenta">
                <ul className="list-disc space-y-1 pl-4 text-xs text-ink-2">{ev.warnings.map((w) => <li key={w}>{w}</li>)}</ul>
              </Card>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
