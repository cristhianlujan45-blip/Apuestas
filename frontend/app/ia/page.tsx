"use client";
import { CalibrationChart, ModelBarChart } from "@/components/charts";
import { Card, Empty, ErrorBox, Loading, PageHeader, StatusBadge } from "@/components/ui";
import { bogota, num, pct, signedPct } from "@/lib/format";
import { useApi } from "@/lib/useApi";

const LABEL: Record<string, string> = {
  dixon_coles: "Dixon-Coles", poisson: "Poisson", bivariate_poisson: "Poisson bivariado", elo: "Elo", glicko2: "Glicko-2",
  logreg: "Reg. logística", lightgbm: "LightGBM", lightgbm_mkt: "LightGBM + mercado", xgboost: "XGBoost", catboost: "CatBoost",
  random_forest: "Random Forest", torch_mlp: "MLP PyTorch", market: "Mercado sin margen", ensemble: "Ensemble",
};

export default function AI() {
  const { data, error, loading } = useApi("/models");
  if (loading) return <Loading />;
  if (error) return <ErrorBox error={error} />;
  const run = data.validation_runs?.[0];
  const m = run?.metrics;
  return (
    <div className="space-y-4">
      <PageHeader title="Inteligencia artificial · motor multimodelo"
        subtitle="Cada modelo se evalúa con validación temporal walk-forward: las predicciones de cada semana se generan con modelos entrenados solo con partidos anteriores. El sistema elige pesos del ensemble por apilamiento (stacking) sobre esas predicciones fuera de muestra." />
      {!run ? <Empty>No hay validaciones. Entrene el modelo desde Configuración o con <code>python -m app.cli train-football</code>.</Empty> : (
        <>
          <div className="grid gap-3 md:grid-cols-4">
            <Card title="Periodo validado"><div className="text-sm num">{bogota(run.from)} → {bogota(run.to)}</div><div className="text-xs text-ink-muted">{run.n} partidos · {run.scope}</div></Card>
            <Card title="Campeón"><div className="text-lg font-semibold">{LABEL[m.champion] || m.champion}</div></Card>
            <Card title="Ensemble (todas las ligas)"><div className="text-sm num">Log loss {num(m.ensemble?.log_loss, 4)} · RPS {num(m.ensemble?.rps, 4)}</div><div className="text-xs text-ink-muted num">Brier {num(m.ensemble?.brier, 4)} · acierto {pct(m.ensemble?.accuracy)}</div></Card>
            <Card title="Degradación">{m.roi?.degradation ? (m.roi.degradation.alarm ? <StatusBadge status="warning">Alarma (z={num(m.roi.degradation.z, 1)})</StatusBadge> : <StatusBadge status="good">Estable</StatusBadge>) : "—"}</Card>
          </div>
          <div className="grid gap-4 lg:grid-cols-2">
            <Card title={`Log loss pareado · ${m.ensemble?.champion_scope || "conjunto común"}${m.ensemble?.market_subset ? ` (${m.ensemble.market_subset.n} partidos)` : ""}`}>
              <ModelBarChart rows={Object.entries(m.ensemble?.champion_ranking || {}).map(([k, v]: any) => ({ name: LABEL[k] || k, value: v, champion: k === m.champion }))} />
              <p className="mt-2 text-xs text-ink-muted">Todos los modelos se comparan sobre exactamente los mismos partidos. Menor es mejor.</p>
            </Card>
            <Card title="Calibración del ensemble (victoria local)">
              {m.ensemble?.calibration_home ? <CalibrationChart rows={m.ensemble.calibration_home.filter((r: any) => r.n >= 20)} /> : <Empty>—</Empty>}
              <p className="mt-1 text-xs text-ink-muted">Tramos con al menos 20 partidos. Diagonal = calibración perfecta.</p>
            </Card>
          </div>
          <Card title="Métricas por modelo">
            <div className="overflow-x-auto"><table className="data min-w-[820px]">
              <thead><tr><th>Modelo</th><th>Log loss</th><th>Brier</th><th>RPS</th><th>Acierto</th><th>ECE local</th><th>Cobertura</th><th>Log loss común</th><th>Peso ensemble</th></tr></thead>
              <tbody>{Object.entries(m.per_model).map(([k, v]: any) => (
                <tr key={k}><td>{LABEL[k] || k}</td><td className="num">{num(v.log_loss, 4)}</td><td className="num">{num(v.brier, 4)}</td><td className="num">{num(v.rps, 4)}</td>
                  <td className="num">{pct(v.accuracy)}</td><td className="num">{num(v.ece_home, 3)}</td><td className="num">{pct(v.coverage, 0)}</td><td className="num">{num(v.common_log_loss, 4)}</td><td className="num">{m.weights?.[k] != null ? pct(m.weights[k]) : "—"}</td></tr>
              ))}</tbody></table></div>
            {m.ensemble?.weights_no_market && <p className="mt-2 text-xs text-ink-muted">Pesos sin cuotas de referencia: {Object.entries(m.ensemble.weights_no_market).filter(([, w]: any) => w > 0.005).map(([k, w]: any) => `${LABEL[k] || k} ${pct(w, 0)}`).join(" · ")}</p>}
          </Card>
          <div className="grid gap-4 lg:grid-cols-2">
            <Card title="Totales de goles">
              <p className="text-sm text-ink-2 num">MAE {num(m.totals?.mae_total_goals, 3)} · RMSE {num(m.totals?.rmse_total_goals, 3)} · Brier más de 2.5 {num(m.totals?.brier_over_2_5, 4)} · log loss {num(m.totals?.log_loss_over_2_5, 4)}</p>
              {m.totals?.calibration_over_2_5 && <CalibrationChart rows={m.totals.calibration_over_2_5} height={220} />}
            </Card>
            <Card title="Rentabilidad simulada (cuotas internacionales, EV > 3 %)">
              <table className="data"><thead><tr><th>Modelo</th><th>Cuotas</th><th>Apuestas</th><th>ROI</th><th>IC 95 %</th><th>CLV</th></tr></thead>
                <tbody>{Object.entries(m.roi || {}).filter(([k]) => !["degradation", "rolling_log_loss"].includes(k)).flatMap(([k, v]: any) =>
                  Object.entries(v).map(([kind, r]: any) => (
                    <tr key={k + kind}><td>{LABEL[k] || k}</td><td>{kind === "avg_odds" ? "promedio" : "máxima"}</td><td className="num">{r.bets}</td>
                      <td className="num">{r.roi != null ? signedPct(r.roi) : "—"}</td><td className="num">{r.roi_ci ? `${signedPct(r.roi_ci[0])} / ${signedPct(r.roi_ci[1])}` : "—"}</td><td className="num">{r.clv != null ? signedPct(r.clv) : "—"}</td></tr>
                  )))}</tbody></table>
              <p className="mt-2 text-xs text-ink-muted">Resultado honesto: superar al mercado es difícil. Un ROI negativo indica que el modelo, por sí solo, no encuentra ventaja frente a esas cuotas.</p>
            </Card>
          </div>
        </>
      )}
      <Card title="Versiones de modelos">
        <table className="data"><thead><tr><th>Modelo</th><th>Versión</th><th>Estado</th><th>Creado</th></tr></thead>
          <tbody>{data.versions.map((v: any) => <tr key={v.id}><td>{v.name}</td><td className="font-mono text-xs">{v.version}</td>
            <td>{v.status === "champion" ? <StatusBadge status="good">campeón</StatusBadge> : <StatusBadge status="info">{v.status}</StatusBadge>}</td><td className="num">{bogota(v.created_at)}</td></tr>)}</tbody></table>
        <p className="mt-2 text-xs text-ink-muted">Reentrenamiento controlado: un candidato solo reemplaza al campeón si su log loss de validación no empeora.</p>
      </Card>
    </div>
  );
}
