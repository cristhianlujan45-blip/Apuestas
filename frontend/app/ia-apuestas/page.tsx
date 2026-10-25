"use client";
import Link from "next/link";
import { BankrollChart } from "@/components/charts";
import StakeHint from "@/components/StakeHint";
import { Card, Empty, ErrorBox, Loading, PageHeader, Stat, StatusBadge } from "@/components/ui";
import { addBet } from "@/lib/bets";
import { bogota, cop, odds, pct, signedPct } from "@/lib/format";
import { useApi } from "@/lib/useApi";

const RES: Record<string, [string, any]> = {
  won: ["ganada", "good"], half_won: ["media ganada", "good"], void: ["nula", "info"], half_lost: ["media perdida", "warning"], lost: ["perdida", "critical"],
};
const OUT: Record<string, string> = { home: "Local", draw: "Empate", away: "Visitante" };

export default function AgentPage() {
  const { data, error, loading } = useApi("/agent", [], 120000);
  if (loading && !data) return <Loading />;
  if (error) return <ErrorBox error={error} />;
  const bt = data.backtest || {};
  const oos = bt.out_of_sample || {};
  const rec = data.record || {};
  const pc = data.predictions_check || {};
  const curve = (bt.bankroll_curve || []).map((p: any) => ({ label: p.date, bankroll: p.bankroll }));
  const live = (data.bankroll?.curve || []).map((p: any, i: number) => ({ label: p.date ? bogota(p.date, false) : "inicio", bankroll: p.bankroll, i }));
  return (
    <div className="space-y-4">
      <PageHeader title="IA de apuestas (simulada)"
        subtitle="Un agente que aprende de miles de partidos reales qué apuestas ganan a largo plazo, recomienda antes de cada partido y apuesta en simulado con una banca virtual. Cada recomendación queda sellada antes del partido; después se compara con el resultado real. Nunca coloca apuestas con su dinero." />

      <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
        <Stat label="Banca virtual" value={cop(data.bankroll?.current ?? 0)} hint={`inicial ${cop(data.bankroll?.start ?? 0)}`} />
        <Stat label="Apuestas simuladas" value={rec.bets ?? 0} hint={`${rec.open ?? 0} abiertas · ${rec.settled ?? 0} liquidadas`} />
        <Stat label="ROI real" value={rec.roi == null ? "—" : signedPct(rec.roi)} hint={rec.settled ? `ganancia ${cop(rec.profit)}` : "aún sin liquidar"} />
        <Stat label="CLV real" value={rec.clv == null ? "—" : signedPct(rec.clv)} hint={rec.clv_n ? `${rec.clv_n} con cierre` : "llega 1–3 días después"} />
        <Stat label="Acierto del modelo" value={pc.accuracy == null ? "—" : pct(pc.accuracy, 0)} hint={pc.n ? `ganador acertado en ${pc.n} partidos` : "sin partidos terminados aún"} />
      </div>

      <Card title="Recomendaciones abiertas">
        {!data.open?.length ? (
          <Empty>Ninguna cuota colombiana cumple la política ahora mismo (ventaja ≥ {pct(data.policy?.min_edge ?? 0, 0)} sobre el precio justo de Pinnacle y cuota ≤ {odds(data.policy?.max_odds ?? 0)}). El agente necesita cuotas de casas colombianas: cree el secreto gratuito <code>ODDSPAPI_KEY</code>.</Empty>
        ) : (
          <div className="overflow-x-auto"><table className="data min-w-[900px]">
            <thead><tr><th>Partido</th><th>Recomendación</th><th>Casa</th><th>Cuota</th><th>Prob. justa</th><th>Ventaja</th><th>Simulado</th><th>Para usted</th><th /></tr></thead>
            <tbody>{data.open.map((b: any) => (
              <tr key={b.id}>
                <td><Link className="hover:text-accent" href={`/partido?id=${b.event_id}`}>{b.event}</Link><div className="text-[11px] text-ink-muted">{bogota(b.start_time)}</div></td>
                <td>{b.selection}<div className="text-[11px] text-ink-muted">{b.reason}</div></td>
                <td>{b.operator}</td><td className="num">{odds(b.odds)}</td><td className="num">{pct(b.p_est)}</td>
                <td className="num text-good">{signedPct(b.edge)}</td><td className="num">{cop(b.stake_cop)}</td>
                <td><StakeHint p={b.p_est} odds={b.odds} /></td>
                <td><button className="text-xs text-accent" onClick={() => {
                  const st = Number(prompt("Si la hizo en su casa, ¿cuánto apostó (COP)?", "10000"));
                  if (st > 0) { addBet({ operator: b.operator, stake_cop: st, odds: b.odds, description: `IA: ${b.selection}`, legs: [{ event_id: b.event_id, event: b.event, selection_key: b.selection_key, selection: b.selection, odds: b.odds, start_time: b.start_time }] }); alert("Registrada en Mis apuestas"); }
                }}>La hice</button></td>
              </tr>
            ))}</tbody></table></div>
        )}
        {data.open?.length > 0 && <p className="mt-2 text-xs text-ink-muted">Confirme la cuota en la casa antes de apostar. Última sellada a las {bogota(data.open[0].created_at, false)} · código {data.open[0].hash}.</p>}
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Lo que aprendió de los datos">
          <p className="text-sm text-ink-2">{bt.strategy || "Aún sin entrenar: se entrena en la próxima ejecución del pipeline."}</p>
          {bt.matches && <>
            <div className="mt-3 grid grid-cols-2 gap-2 text-sm">
              <div className="rounded-lg bg-surface-2 p-2"><div className="text-xs text-ink-muted">Regla aprendida</div>
                <div className="num">ventaja ≥ {pct(data.policy.min_edge, 0)} · cuota ≤ {odds(data.policy.max_odds)}</div></div>
              <div className="rounded-lg bg-surface-2 p-2"><div className="text-xs text-ink-muted">Datos</div><div className="num">{bt.matches.toLocaleString("es-CO")} partidos · {bt.from} a {bt.to}</div></div>
              <div className="rounded-lg bg-surface-2 p-2"><div className="text-xs text-ink-muted">Fuera de muestra</div>
                <div className="num">{oos.n} apuestas · ROI {signedPct(oos.roi)} ± {pct(oos.roi_se ?? 0, 1)}</div></div>
              <div className="rounded-lg bg-surface-2 p-2"><div className="text-xs text-ink-muted">Le gana al cierre (CLV)</div><div className="num">{signedPct(oos.clv)} · acierto {pct(oos.hit_rate, 0)}</div></div>
            </div>
            {curve.length > 1 && <><div className="mt-3 text-xs text-ink-muted">Banca simulada en las temporadas que el agente no vio al aprender (Kelly ¼, tope 2 %)</div><BankrollChart points={curve} start={1_000_000} /></>}
            <table className="data mt-3"><thead><tr><th>Temporada</th><th>Umbral</th><th>Apuestas</th><th>ROI</th><th>CLV</th></tr></thead>
              <tbody>{(bt.folds || []).map((f: any) => <tr key={f.season}><td>{f.season}</td><td className="num">{pct(f.threshold, 0)}</td><td className="num">{f.n}</td><td className="num">{f.n ? signedPct(f.roi) : "—"}</td><td className="num">{f.n ? signedPct(f.clv) : "—"}</td></tr>)}</tbody></table>
            {bt.typical_book_same_rule?.n > 0 && <p className="mt-2 text-xs text-warning">Misma regla con la cuota de una casa típica: ROI {signedPct(bt.typical_book_same_rule.roi)} en {bt.typical_book_same_rule.n} apuestas. La ventaja está en buscar la casa que mejor paga.</p>}
            <p className="mt-2 text-xs text-ink-muted">{bt.note} {bt.live_adjustment?.action ? `Ajuste con sus propias apuestas: ${bt.live_adjustment.action}.` : ""}</p>
          </>}
        </Card>
        <Card title="Banca virtual del agente">
          {live.length > 1 ? <BankrollChart points={live} start={data.bankroll.start} /> : <Empty>La curva aparece cuando se liquiden las primeras apuestas simuladas.</Empty>}
          <p className="mt-2 text-xs text-ink-muted">{data.disclaimer}</p>
        </Card>
      </div>

      <Card title="Historial de apuestas simuladas">
        {!data.history?.length ? <Empty>Sin apuestas liquidadas todavía.</Empty> : (
          <div className="overflow-x-auto"><table className="data min-w-[860px]">
            <thead><tr><th>Partido</th><th>Recomendó</th><th>Cuota</th><th>Resultado</th><th>Marcador</th><th>Ganancia</th><th>CLV</th></tr></thead>
            <tbody>{data.history.map((b: any) => (
              <tr key={b.id}><td>{b.event}<div className="text-[11px] text-ink-muted">{bogota(b.start_time)}</div></td><td>{b.selection}</td><td className="num">{odds(b.odds)}</td>
                <td><StatusBadge status={RES[b.result]?.[1] || "info"}>{RES[b.result]?.[0] || b.result}</StatusBadge></td><td className="num">{b.score || "—"}</td>
                <td className={`num ${(b.payout_cop - b.stake_cop) >= 0 ? "text-good" : "text-critical"}`}>{cop(b.payout_cop - b.stake_cop)}</td>
                <td className={`num ${b.clv > 0 ? "text-good" : "text-ink-2"}`}>{b.clv == null ? "—" : signedPct(b.clv)}</td></tr>
            ))}</tbody></table></div>
        )}
      </Card>

      <Card title="¿Coincidió lo que predijo con lo que pasó?">
        <div className="mb-3 flex flex-wrap gap-4 text-sm text-ink-2 num">
          <span>Ganador acertado: <b className="text-ink">{pc.accuracy == null ? "—" : pct(pc.accuracy, 0)}</b></span>
          <span>Más/menos 2.5 acertado: <b className="text-ink">{pc.over_accuracy == null ? "—" : pct(pc.over_accuracy, 0)}</b></span>
          <span>Brier medio: <b className="text-ink">{pc.brier == null ? "—" : pc.brier.toFixed(3)}</b> <span className="text-ink-muted">(0 perfecto · 0.667 azar)</span></span>
        </div>
        {!pc.items?.length ? <Empty>Las comprobaciones aparecen cuando terminen los partidos predichos.</Empty> : (
          <div className="overflow-x-auto"><table className="data min-w-[760px]">
            <thead><tr><th>Partido</th><th>Antes del partido dijo</th><th>Resultado</th><th>¿Coincidió?</th><th>Sellado</th></tr></thead>
            <tbody>{pc.items.slice(0, 100).map((x: any) => (
              <tr key={x.event_id}><td>{x.event}<div className="text-[11px] text-ink-muted">{bogota(x.start_time)}</div></td>
                <td>{OUT[x.predicted]} ({pct(x.p_predicted, 0)}){x.p_over_2_5 != null && <span className="text-xs text-ink-muted"> · {x.p_over_2_5 >= 0.5 ? "más" : "menos"} de 2.5 ({pct(Math.max(x.p_over_2_5, 1 - x.p_over_2_5), 0)})</span>}</td>
                <td className="num">{x.score} · {OUT[x.actual]}</td>
                <td>{x.hit ? <StatusBadge status="good">Sí</StatusBadge> : <StatusBadge status="critical">No</StatusBadge>}</td>
                <td className="num text-[11px] text-ink-muted">{bogota(x.predicted_at, false)} · {x.hash}</td></tr>
            ))}</tbody></table></div>
        )}
        <p className="mt-2 text-xs text-ink-muted">Acertar el ganador no basta para ganar dinero: los favoritos pagan poco. Lo que hace rentable al agente es apostar solo cuando la cuota paga más de lo justo.</p>
      </Card>
    </div>
  );
}
