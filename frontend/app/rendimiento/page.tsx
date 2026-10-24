"use client";
import { CalibrationChart, RollingLine } from "@/components/charts";
import { Card, Empty, ErrorBox, Loading, PageHeader, Stat, StatusBadge } from "@/components/ui";
import { num, pct, signedPct } from "@/lib/format";
import { useApi } from "@/lib/useApi";

export default function Performance() {
  const { data, error, loading } = useApi("/models/performance");
  if (loading) return <Loading />;
  if (error) return <ErrorBox error={error} />;
  return (
    <div className="space-y-4">
      <PageHeader title="Rendimiento real de los modelos"
        subtitle="Solo cuentan predicciones registradas ANTES del inicio de cada partido y ya liquidadas. Esta página demuestra con resultados reales si el sistema mejora." />
      {!data.n ? <Empty>{data.message}</Empty> : (
        <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
            <Stat label="Partidos evaluados" value={data.n} />
            <Stat label="Log loss" value={num(data.log_loss, 4)} hint={data.degradation?.expected_log_loss ? `esperada ${num(data.degradation.expected_log_loss, 4)}` : undefined} />
            <Stat label="Brier" value={num(data.brier, 4)} />
            <Stat label="RPS" value={num(data.rps, 4)} />
            <Stat label="ROI señales de valor" value={data.value_bets ? signedPct(data.value_bets.roi) : "—"} hint={data.value_bets ? `${data.value_bets.bets} apuestas, acierto ${pct(data.value_bets.hit_rate)}` : "sin señales"} />
          </div>
          <div className="grid gap-4 lg:grid-cols-2">
            <Card title="Calibración (victoria local)"><CalibrationChart rows={data.calibration_home} /></Card>
            <Card title="Log loss móvil" right={data.degradation?.status === "alerta" ? <StatusBadge status="warning">Degradación</StatusBadge> : <StatusBadge status="good">Sin alerta</StatusBadge>}>
              {data.rolling_log_loss?.length ? <RollingLine values={data.rolling_log_loss} reference={data.degradation?.expected_log_loss} /> : <Empty>Pocos datos.</Empty>}
            </Card>
          </div>
          {data.mae_total_goals != null && <Card title="Goles totales"><p className="text-sm num">MAE {num(data.mae_total_goals, 3)} · RMSE {num(data.rmse_total_goals, 3)}</p></Card>}
          <Card title="Por versión de modelo"><table className="data"><tbody>{Object.entries(data.by_version).map(([v, r]: any) => <tr key={v}><td className="font-mono text-xs">{v}</td><td className="num">{r.n}</td><td className="num">{num(r.log_loss, 4)}</td></tr>)}</tbody></table></Card>
        </>
      )}
    </div>
  );
}
