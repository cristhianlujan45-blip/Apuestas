"use client";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { Card, Empty, PageHeader, Stat, StatusBadge } from "@/components/ui";
import { addBet, deleteBet, evaluate, loadBets, setManualResult, summary, type Bet, type Result } from "@/lib/bets";
import { bogota, cop, odds, pct, signedPct } from "@/lib/format";
import { currentBankroll, loadBankroll, storeBankrollNow } from "@/lib/bankroll";

const ST: Record<string, any> = { ganada: "good", perdida: "critical", pendiente: "info", nula: "info", parcial: "warning", "liquidar a mano": "warning" };

export default function MyBets() {
  const [bets, setBets] = useState<Bet[]>([]);
  const [results, setResults] = useState<Record<number, Result>>({});
  const [f, setF] = useState({ operator: "betplay", description: "", stake_cop: 10000, odds: 2 });
  const reload = () => setBets(loadBets());
  useEffect(() => {
    reload();
    import("@/lib/staticApi").then((m) => m.route("/results")).then((r) => {
      setResults(Object.fromEntries((r.results || []).map((x: Result) => [x.event_id, x])));
    }).catch(() => {});
  }, []);
  const evals = useMemo(() => bets.map((b) => evaluate(b, results)), [bets, results]);
  const s = summary(evals);
  const bk = loadBankroll();
  useEffect(() => { storeBankrollNow(s.profit); }, [s.profit]);
  return (
    <div className="space-y-4">
      <PageHeader title="Mis apuestas"
        subtitle="Registre lo que apostó en su casa. La app las liquida con los resultados reales y mide el CLV: si consiguió mejor cuota que la de cierre justa (Pinnacle sin margen). Un CLV positivo sostenido es la mejor señal de ventaja real, antes incluso que el saldo." />
      <div className="grid grid-cols-2 gap-3 md:grid-cols-6">
        <Stat label="Banca actual" value={bk.initial_cop ? cop(currentBankroll(bk, s.profit)) : "—"} hint={bk.initial_cop ? `inicial ${cop(bk.initial_cop)}` : <Link className="text-accent" href="/configuracion">configurar banca</Link>} />
        <Stat label="Apuestas" value={s.total} hint={`${s.settled} liquidadas`} />
        <Stat label="Invertido" value={cop(s.staked)} />
        <Stat label="Ganancia" value={<span className={s.profit >= 0 ? "text-good" : "text-critical"}>{cop(s.profit)}</span>} />
        <Stat label="ROI" value={s.roi == null ? "—" : signedPct(s.roi)} />
        <Stat label="CLV medio" value={s.avg_clv == null ? "—" : signedPct(s.avg_clv)} hint={s.beat_close == null ? "sin cierre disponible aún" : `supera el cierre en ${pct(s.beat_close, 0)} de ${s.clv_n}`} />
      </div>
      <Card title="Registrar una apuesta simple o manual">
        <div className="grid grid-cols-2 gap-2 md:grid-cols-5">
          <div><label className="label">Casa</label><input className="input" value={f.operator} onChange={(e) => setF({ ...f, operator: e.target.value })} /></div>
          <div className="col-span-2"><label className="label">Descripción</label><input className="input" value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} /></div>
          <div><label className="label">Inversión (COP)</label><input type="number" className="input" value={f.stake_cop} onChange={(e) => setF({ ...f, stake_cop: +e.target.value })} /></div>
          <div><label className="label">Cuota</label><input type="number" step="0.01" className="input" value={f.odds} onChange={(e) => setF({ ...f, odds: +e.target.value })} /></div>
        </div>
        <button className="btn-primary mt-3" onClick={() => { addBet({ ...f, legs: [] }); reload(); }}>Registrar</button>
        <p className="mt-2 text-xs text-ink-muted">Para liquidación y CLV automáticos, registre desde PARLAY AI, Detector de valor o la ficha del partido: así la app conoce el partido y la selección exacta.</p>
      </Card>
      <Card title="Historial">
        {!evals.length ? <Empty>Sin apuestas registradas.</Empty> : (
          <div className="overflow-x-auto"><table className="data min-w-[860px]">
            <thead><tr><th>Fecha</th><th>Apuesta</th><th>Casa</th><th>Cuota</th><th>Inversión</th><th>Estado</th><th>Resultado</th><th>CLV</th><th /></tr></thead>
            <tbody>{evals.map((b) => (
              <tr key={b.id}>
                <td className="num text-ink-2">{bogota(b.placed_at)}</td>
                <td className="text-xs">{b.legs.length ? b.legs.map((l: any, i: number) => (
                  <div key={i}><Link className="hover:text-accent" href={`/partido?id=${l.event_id}`}>{l.event}</Link>: {l.selection} @ {odds(l.odds)} <span className="text-ink-muted">· {l.status}{l.score ? ` (${l.score})` : ""}{l.clv != null ? ` · CLV ${signedPct(l.clv)}` : ""}</span></div>
                )) : b.description}</td>
                <td>{b.operator}</td><td className="num">{odds(b.odds)}</td><td className="num">{cop(b.stake_cop)}</td>
                <td><StatusBadge status={ST[b.status] || "info"}>{b.status}</StatusBadge>
                  {b.status === "liquidar a mano" && <div className="mt-1 flex gap-1 text-[11px]">
                    {(["won", "lost", "void"] as const).map((r) => <button key={r} className="text-accent" onClick={() => { setManualResult(b.id, r); reload(); }}>{{ won: "ganó", lost: "perdió", void: "nula" }[r]}</button>)}</div>}</td>
                <td className={`num ${b.profit != null && b.profit >= 0 ? "text-good" : "text-ink-2"}`}>{b.profit == null ? "—" : cop(b.profit)}</td>
                <td className={`num ${b.clv != null && b.clv > 0 ? "text-good" : "text-ink-2"}`}>{b.clv == null ? "—" : signedPct(b.clv)}</td>
                <td><button className="text-xs text-critical" onClick={() => { if (confirm("¿Borrar esta apuesta?")) { deleteBet(b.id); reload(); } }}>Borrar</button></td>
              </tr>
            ))}</tbody></table></div>
        )}
        <p className="mt-2 text-xs text-ink-muted">El cierre de referencia se publica cuando football-data.co.uk incorpora el resultado (normalmente 1–3 días después del partido). Se guarda solo en este dispositivo; use Configuración → Copia de seguridad para moverlo a otro.</p>
      </Card>
    </div>
  );
}
