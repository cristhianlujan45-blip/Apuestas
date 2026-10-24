"use client";
import Link from "next/link";
import { Card, Empty, ErrorBox, Loading, PageHeader, ProbBar, StatusBadge } from "@/components/ui";
import { bogota, STATUS_LABEL } from "@/lib/format";
import { useApi } from "@/lib/useApi";

export default function Predictions() {
  const { data, error, loading } = useApi("/predictions?limit=300");
  return (
    <div>
      <PageHeader title="Predicciones registradas"
        subtitle="Cada predicción se guarda antes del partido, de forma inmutable y encadenada por hash. Nunca se modifica después para aparentar mayor precisión."
        right={data?.chain && (data.chain.valid ? <StatusBadge status="good">Cadena íntegra · {data.chain.checked}</StatusBadge> : <StatusBadge status="critical">Cadena rota en #{data.chain.broken_at}</StatusBadge>)} />
      <Card>
        {loading ? <Loading /> : error ? <ErrorBox error={error} /> : !data.predictions.length ? <Empty>Aún no hay predicciones registradas. El worker las registra cada hora para los próximos 3 días.</Empty> : (
          <div className="overflow-x-auto"><table className="data min-w-[860px]">
            <thead><tr><th>Registrada</th><th>Evento</th><th>Inicio</th><th className="w-64">Probabilidades</th><th>Resultado</th><th>Versión</th><th>Hash</th></tr></thead>
            <tbody>{data.predictions.map((p: any) => (
              <tr key={p.id}><td className="num text-ink-2">{bogota(p.created_at)}</td><td><Link className="hover:text-accent" href={`/partido?id=${p.event_id}`}>{p.event}</Link></td>
                <td className="num text-ink-2">{bogota(p.start_time)}</td><td>{p.probs ? <ProbBar probs={p.probs} /> : "—"}</td>
                <td className="num">{p.score || STATUS_LABEL[p.status] || p.status}</td><td className="text-[11px] text-ink-muted">{p.model_version}</td><td className="font-mono text-[11px] text-ink-muted">{p.hash}</td></tr>
            ))}</tbody></table></div>
        )}
      </Card>
    </div>
  );
}
