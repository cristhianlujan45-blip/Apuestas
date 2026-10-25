"use client";
import { useMemo, useState } from "react";
import { DistributionChart, OddsHistoryChart } from "@/components/charts";
import { Badge, Card, Empty, ErrorBox, Loading, PageHeader, ProbBar, StatusBadge } from "@/components/ui";
import { bogota, num, odds, pct, signedPct, STATUS_LABEL } from "@/lib/format";
import { useApi } from "@/lib/useApi";
import { COUNT_MARKETS, fairOdds, pEff, priceCounts, type CountParams } from "@/lib/engine";

const COUNT_ROWS: { market: string; label: string; lines: number[] }[] = [
  { market: "corners_total", label: "Córners totales", lines: [7.5, 8.5, 9.5, 10.5, 11.5] },
  { market: "corners_home", label: "Córners del local", lines: [3.5, 4.5, 5.5, 6.5] },
  { market: "corners_away", label: "Córners del visitante", lines: [2.5, 3.5, 4.5, 5.5] },
  { market: "cards_total", label: "Tarjetas totales", lines: [2.5, 3.5, 4.5, 5.5] },
  { market: "shots_on_target_total", label: "Tiros al arco totales", lines: [6.5, 7.5, 8.5, 9.5] },
];

function CountsCard({ counts, home, away }: { counts: CountParams; home: string; away: string }) {
  const rows = COUNT_ROWS.filter((r) => counts[COUNT_MARKETS[r.market][0]]);
  if (!rows.length) return null;
  return (
    <Card title="Córners, tarjetas y tiros: cuota justa del modelo">
      <div className="mb-2 flex flex-wrap gap-3 text-xs text-ink-2 num">
        {counts.corners && <span>Córners esperados: {home} {num(counts.corners.home, 1)} · {away} {num(counts.corners.away, 1)}</span>}
        {counts.cards && <span>Tarjetas esperadas: {num(counts.cards.home + counts.cards.away, 1)}</span>}
      </div>
      <div className="overflow-x-auto">
        <table className="data min-w-[560px]">
          <thead><tr><th>Mercado</th><th>Línea</th><th>P(más)</th><th>Cuota justa más</th><th>P(menos)</th><th>Cuota justa menos</th></tr></thead>
          <tbody>{rows.flatMap((r) => r.lines.map((l) => {
            const o = priceCounts(counts, { market: r.market, selection: "over", line: l, player: null, period: "ft" });
            const u = priceCounts(counts, { market: r.market, selection: "under", line: l, player: null, period: "ft" });
            if (!o || !u) return null;
            return <tr key={r.market + l}><td>{r.label}</td><td className="num">{l}</td><td className="num">{pct(pEff(o))}</td><td className="num">{odds(fairOdds(o))}</td>
              <td className="num">{pct(pEff(u))}</td><td className="num">{odds(fairOdds(u))}</td></tr>;
          }))}</tbody>
        </table>
      </div>
      <p className="mt-2 text-[11px] text-ink-muted">Modelo de fuerza por equipo (binomial negativa) entrenado con los córners, tarjetas y tiros reales de cada liga. Si su casa paga más que la cuota justa, la apuesta tiene valor esperado positivo; cargue esa cuota en «Cuotas desde foto» o en Configuración para valorarla.</p>
    </Card>
  );
}

const COMPONENT_LABEL: Record<string, string> = {
  dixon_coles: "Dixon-Coles (MAP bayesiano)", poisson: "Poisson", bivariate_poisson: "Poisson bivariado",
  elo: "Elo + logit ordenado", glicko2: "Glicko-2", logreg: "Regresión logística", lightgbm: "LightGBM",
  lightgbm_mkt: "LightGBM + mercado", xgboost: "XGBoost", catboost: "CatBoost", random_forest: "Random Forest",
  torch_mlp: "Red neuronal (PyTorch)", market: "Mercado internacional sin margen",
};

export default function EventView({ id }: { id: string }) {
  const { data, error, loading } = useApi(`/events/${id}`, [id], 60000);
  const sim = useApi(`/events/${id}/simulate`, [id]);
  const [selKey, setSelKey] = useState<string | null>(null);
  const [market, setMarket] = useState("");
  const hist = useApi(selKey ? `/events/${id}/odds-history?selection_key=${encodeURIComponent(selKey)}` : null, [selKey]);

  const markets = useMemo(() => Array.from(new Set((data?.markets || []).map((m: any) => m.market_label))) as string[], [data]);
  if (loading && !data) return <Loading />;
  if (error) return <ErrorBox error={error} />;
  const ev = data.event;
  const m = data.model || {};
  const rows = (data.markets || []).filter((r: any) => !market || r.market_label === market);

  return (
    <div className="space-y-4">
      <PageHeader title={ev.label}
        subtitle={<>{ev.competition || ev.sport} · {bogota(ev.start_time)} (hora Colombia) · {ev.status === "live" ? `EN VIVO ${ev.minute ?? ""}'` : STATUS_LABEL[ev.status] || ev.status}
          {ev.home_score != null && <b className="ml-2 text-ink">{ev.home_score}-{ev.away_score}</b>}</>}
        right={data.data_sufficient ? <StatusBadge status="good">Datos suficientes</StatusBadge> : <StatusBadge status="warning">Datos limitados</StatusBadge>} />
      {data.model_note && <Empty>{data.model_note}</Empty>}

      {m.probs && (
        <div className="grid gap-4 lg:grid-cols-3">
          <Card title="Probabilidad del ensemble" className="lg:col-span-1">
            <ProbBar probs={m.live?.probs || m.probs} labels={[ev.home, "Empate", ev.away]} />
            {m.uncertainty?.home && (
              <p className="mt-3 text-xs text-ink-muted num">
                Intervalo 80 % (incertidumbre de parámetros): local {pct(m.uncertainty.home[0], 0)}–{pct(m.uncertainty.home[1], 0)},
                empate {pct(m.uncertainty.draw[0], 0)}–{pct(m.uncertainty.draw[1], 0)}, visitante {pct(m.uncertainty.away[0], 0)}–{pct(m.uncertainty.away[1], 0)}
              </p>
            )}
            <div className="mt-3 grid grid-cols-2 gap-2 text-sm">
              <div><div className="text-xs text-ink-muted">Goles esperados {ev.home}</div><div className="num text-lg">{num(m.expected_goals?.home, 2)}</div></div>
              <div><div className="text-xs text-ink-muted">Goles esperados {ev.away}</div><div className="num text-lg">{num(m.expected_goals?.away, 2)}</div></div>
            </div>
            {m.live && <p className="mt-2 text-xs text-ink-2">Modelo en vivo: {num(m.live.remaining_minutes, 0)} min restantes · goles finales esperados {num(m.live.expected_final.home, 2)}–{num(m.live.expected_final.away, 2)}</p>}
            <p className="mt-2 text-[11px] text-ink-muted">Versión: {data.model_version}</p>
          </Card>
          <Card title="Modelos individuales" className="lg:col-span-2">
            <table className="data">
              <thead><tr><th>Modelo</th><th>Peso</th><th className="w-72">L / E / V</th></tr></thead>
              <tbody>
                {Object.entries(m.components || {}).map(([k, v]: any) => (
                  <tr key={k}><td>{COMPONENT_LABEL[k] || k}</td><td className="num text-ink-2">{m.weights?.[k] != null ? pct(m.weights[k], 0) : "—"}</td>
                    <td><ProbBar probs={{ home: v[0], draw: v[1], away: v[2] }} /></td></tr>
                ))}
              </tbody>
            </table>
            {m.data_quality?.issues?.length > 0 && <ul className="mt-2 list-disc pl-5 text-xs text-warning">{m.data_quality.issues.map((i: string) => <li key={i}>{i}</li>)}</ul>}
          </Card>
        </div>
      )}

      {sim.data && (
        <div className="grid gap-4 lg:grid-cols-3">
          <Card title={`Simulación Monte Carlo · total (${sim.data.samples.toLocaleString("es-CO")} escenarios${sim.data.exact ? ", exacto" : ""})`}>
            {sim.data.variables.total && <DistributionChart hist={sim.data.variables.total.histogram.slice(0, 12)} highlight={(x) => x >= 3} />}
            <p className="text-xs text-ink-muted num">Media {num(sim.data.variables.total?.mean, 2)} · P5–P95 {sim.data.variables.total?.p05}–{sim.data.variables.total?.p95}</p>
          </Card>
          <Card title="Diferencia de marcador (local − visitante)">
            {sim.data.variables.margin && <DistributionChart hist={sim.data.variables.margin.histogram.filter((h: any) => Math.abs(h.x) <= 6)} highlight={(x) => x > 0} />}
          </Card>
          <Card title="Resultados más probables">
            {m.top_scores ? (
              <table className="data"><tbody>{m.top_scores.map((s: any) => <tr key={s.score}><td className="num">{s.score}</td><td className="num">{pct(s.p)}</td></tr>)}</tbody></table>
            ) : sim.data.variables.corners_home ? null : <Empty>—</Empty>}
            {sim.data.epistemic && <p className="mt-2 text-xs text-ink-muted num">P(local) P10–P90: {pct(sim.data.epistemic.home.p10)}–{pct(sim.data.epistemic.home.p90)}</p>}
            {sim.data.variables.corners_home && <p className="mt-2 text-xs text-ink-2 num">Córners esperados: {num(sim.data.variables.corners_home.mean, 1)} – {num(sim.data.variables.corners_away.mean, 1)}</p>}
          </Card>
        </div>
      )}

      {m.counts && <CountsCard counts={m.counts} home={ev.home} away={ev.away} />}

      <Card title="Mercados: modelo vs operadores colombianos" right={
        <select className="input max-w-xs" value={market} onChange={(e) => setMarket(e.target.value)}>
          <option value="">Todos los mercados</option>{markets.map((x) => <option key={x}>{x}</option>)}
        </select>}>
        {!rows.length ? <Empty>No hay cuotas de operadores para este evento. Configure el feed de cuotas o cárguelas manualmente en Configuración.</Empty> : (
          <div className="overflow-x-auto">
            <table className="data min-w-[900px]">
              <thead><tr><th>Selección</th><th>Prob. modelo</th><th>Cuota justa</th><th>Mejor cuota CO</th><th>EV</th><th>Diferencia</th><th>Operadores</th><th>Referencia</th></tr></thead>
              <tbody>
                {rows.map((r: any) => (
                  <tr key={r.selection_key} className="cursor-pointer" onClick={() => setSelKey(r.selection_key)}>
                    <td>{r.label}</td>
                    <td className="num">{r.model ? <>{pct(r.model.p)}{r.model.interval?.low != null && <span className="text-ink-muted"> ({pct(r.model.interval.low, 0)}–{pct(r.model.interval.high, 0)})</span>}</> : "—"}</td>
                    <td className="num">{r.model ? odds(r.model.fair_odds) : "—"}</td>
                    <td className="num">{r.best ? <>{odds(r.best.odds)} <span className="text-xs text-ink-muted">{r.best.operator}</span>{r.best.stale && <StatusBadge status="warning">desactualizada</StatusBadge>}</> : "—"}</td>
                    <td className={`num ${r.model?.ev_best > 0 ? "text-good" : "text-ink-2"}`}>{r.model?.ev_best != null ? signedPct(r.model.ev_best) : "—"}</td>
                    <td className="num text-ink-2">{r.spread_pct != null ? `${r.spread_pct.toFixed(1)} %` : "—"}</td>
                    <td className="text-xs text-ink-2">{r.offers.map((o: any) => `${o.operator} ${odds(o.odds)}`).join(" · ")}
                      {r.missing_operators?.length > 0 && <div className="text-ink-muted">No ofrecen: {r.missing_operators.join(", ")}</div>}</td>
                    <td className="text-xs text-ink-muted">{r.reference?.map((o: any) => `${o.operator} ${odds(o.odds)}`).join(" · ") || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="mt-2 text-xs text-ink-muted">Las cuotas de referencia (Pinnacle / consenso internacional) no son de operadores autorizados en Colombia: solo sirven para estimar la probabilidad justa. Haga clic en una fila para ver la evolución.</p>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Evolución de la cuota seleccionada">
          {!selKey ? <Empty>Seleccione una fila de la tabla de mercados.</Empty> : hist.loading ? <Loading /> :
            hist.data?.length ? <OddsHistoryChart points={hist.data} /> : <Empty>Sin historial.</Empty>}
        </Card>
        <Card title="Margen del operador por mercado">
          {data.margins?.length ? (
            <table className="data"><thead><tr><th>Operador</th><th>Mercado</th><th>Línea</th><th>Margen</th></tr></thead>
              <tbody>{data.margins.slice(0, 20).map((x: any, i: number) => <tr key={i}><td>{x.operator}</td><td>{x.market}</td><td className="num">{x.line || "—"}</td><td className="num">{x.margin_pct.toFixed(2)} %</td></tr>)}</tbody></table>
          ) : <Empty>Se necesita el mercado completo de un operador para calcular su margen.</Empty>}
          {data.operators_with_quotes?.length > 0 && <div className="mt-2 flex flex-wrap gap-1">{data.operators_with_quotes.map((o: string) => <Badge key={o}>{o}</Badge>)}</div>}
        </Card>
      </div>
    </div>
  );
}
