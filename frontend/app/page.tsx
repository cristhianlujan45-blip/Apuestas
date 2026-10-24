"use client";
import Link from "next/link";
import { useState } from "react";
import EventTable from "@/components/EventTable";
import { ModelBarChart } from "@/components/charts";
import { Card, Disclaimer, Empty, ErrorBox, Loading, PageHeader, Stat, StatusBadge } from "@/components/ui";
import { num, odds, pct, signedPct } from "@/lib/format";
import { useApi } from "@/lib/useApi";

const PRESETS = [2, 3, 5, 10, 15, 20, 30, 50, 100];

export default function Dashboard() {
  const status = useApi("/status", [], 60000);
  const today = useApi("/events?scope=today&limit=25", [], 120000);
  const value = useApi("/value?min_edge=0.03");
  const models = useApi("/models");
  const alerts = useApi("/alerts");
  const [target, setTarget] = useState(5);

  const run = models.data?.validation_runs?.[0];
  const ranking = run?.metrics?.ensemble?.champion_ranking || {};
  const bars = Object.entries(ranking).map(([k, v]: any) => ({ name: k, value: v, champion: k === run?.metrics?.champion }));

  return (
    <div className="space-y-5">
      <PageHeader title="Centro de inteligencia deportiva"
        subtitle="Modelos estadísticos y de aprendizaje automático entrenados con datos reales, cuotas de operadores autorizados por Coljuegos y optimización de combinadas." />
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Próximos eventos" value={status.data?.counts?.upcoming ?? "—"} hint="en base de datos" />
        <Stat label="En directo" value={status.data?.counts?.live ?? "—"} />
        <Stat label="Cuotas colombianas" value={status.data?.counts?.colombian_quotes ?? "—"}
          hint={status.data?.providers?.odds_api_net?.configured ? "feed odds-api.net activo" : "configure ODDS_API_NET_KEY o cargue cuotas"} />
        <Stat label="Log loss ensemble (validación)" value={run ? num(run.metrics.ensemble?.log_loss, 4) : "—"}
          hint={run ? `${run.n} partidos fuera de muestra` : "entrene el modelo"} />
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <Card title="Buscar mi cuota" className="lg:col-span-1">
          <div className="text-4xl font-semibold num">{target.toFixed(2)}</div>
          <input type="range" className="odds-slider mt-3" min={0} max={PRESETS.length - 1} step={1}
            value={PRESETS.indexOf(target) >= 0 ? PRESETS.indexOf(target) : 2}
            onChange={(e) => setTarget(PRESETS[+e.target.value])} aria-label="Cuota objetivo" />
          <div className="mt-1 flex justify-between text-[10px] text-ink-muted num">{PRESETS.map((p) => <span key={p}>{p}</span>)}</div>
          <Link href={`/parlay?target=${target}`} className="btn-primary mt-4 w-full justify-center">Optimizar combinadas</Link>
          <p className="mt-3 text-xs text-ink-muted">El optimizador maximiza la probabilidad conjunta estimada dentro de la banda de cuota, por operador.</p>
        </Card>
        <Card title="Oportunidades de valor (EV ≥ 3 %)" className="lg:col-span-2"
          right={<Link href="/valor" className="text-xs text-accent">Ver todas</Link>}>
          {value.loading ? <Loading /> : value.error ? <ErrorBox error={value.error} /> : !value.data?.value_bets?.length ? (
            <Empty>Sin selecciones con valor esperado positivo en las cuotas colombianas disponibles.
              {value.data?.report?.events_with_quotes === 0 && " No hay cuotas de operadores colombianos cargadas."}</Empty>
          ) : (
            <table className="data">
              <thead><tr><th>Evento</th><th>Selección</th><th>Operador</th><th>Cuota</th><th>Prob.</th><th>Justa</th><th>EV</th></tr></thead>
              <tbody>
                {value.data.value_bets.slice(0, 6).map((v: any, i: number) => (
                  <tr key={i}><td>{v.event}</td><td>{v.selection}</td><td>{v.operator}</td><td className="num">{odds(v.odds)}</td>
                    <td className="num">{pct(v.probability)}</td><td className="num">{odds(v.fair_odds)}</td><td className="num text-good">{signedPct(v.ev)}</td></tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <Card title="Partidos de hoy" className="lg:col-span-2" right={<Link href="/partidos" className="text-xs text-accent">Ver todos</Link>}>
          {today.loading ? <Loading /> : today.error ? <ErrorBox error={today.error} /> : <EventTable events={today.data?.events || []} empty="No hay partidos hoy en la base de datos. Ejecute la ingesta desde Configuración." />}
        </Card>
        <div className="space-y-4">
          <Card title="Comparación pareada de modelos (log loss, menor es mejor)">
            {bars.length ? <ModelBarChart rows={bars} /> : <Empty>Sin validación todavía.</Empty>}
            {run && <p className="mt-2 text-xs text-ink-muted">Campeón: <b className="text-ink-2">{run.metrics.champion}</b>. Validación temporal walk-forward; las cuotas internacionales sin margen suelen ser el predictor más difícil de superar.</p>}
          </Card>
          <Card title="Alertas">
            {(alerts.data || []).slice(0, 5).map((a: any) => (
              <div key={a.id} className="mb-2 text-xs"><StatusBadge status={a.severity === "critical" ? "critical" : a.severity === "warning" ? "warning" : "info"}>{a.kind}</StatusBadge>
                <p className="mt-1 text-ink-2">{a.message}</p></div>
            ))}
            {!alerts.data?.length && <p className="text-xs text-ink-muted">Sin alertas.</p>}
          </Card>
        </div>
      </div>
      <Disclaimer />
    </div>
  );
}
