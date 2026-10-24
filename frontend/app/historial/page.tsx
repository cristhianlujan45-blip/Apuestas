"use client";
import { Card, Empty, ErrorBox, Loading, PageHeader, StatusBadge } from "@/components/ui";
import { bogota, odds, pct, signedPct, STATUS_LABEL } from "@/lib/format";
import { useApi } from "@/lib/useApi";

const ST: Record<string, any> = { won: "good", lost: "critical", open: "info", void: "info", partial_void: "warning", won_partial: "warning" };

export default function HistoryPage() {
  const { data, error, loading } = useApi("/parlays");
  if (loading) return <Loading />;
  if (error) return <ErrorBox error={error} />;
  const s = data.stats;
  return (
    <div className="space-y-4">
      <PageHeader title="Historial de combinadas" subtitle="Todas las combinadas generadas quedan guardadas y se liquidan con los resultados reales." />
      {s?.settled ? <Card><p className="text-sm num">Liquidadas: {s.settled} · ganadas {s.won} ({pct(s.hit_rate)}) · aciertos esperados según el modelo {s.expected_hits.toFixed(1)} · ROI plano {signedPct(s.roi_flat)}</p></Card> : null}
      <Card>
        {!data.parlays.length ? <Empty>Aún no se han generado combinadas.</Empty> : (
          <div className="overflow-x-auto"><table className="data min-w-[900px]">
            <thead><tr><th>Fecha</th><th>Parlay</th><th>Casa</th><th>Selecciones</th><th>Cuota</th><th>Prob.</th><th>EV</th><th>Estado</th></tr></thead>
            <tbody>{data.parlays.map((p: any) => (
              <tr key={p.id}><td className="num text-ink-2">{bogota(p.created_at)}</td><td>{p.label} · {p.mode}</td><td>{p.operator}</td>
                <td className="text-xs">{p.legs.map((l: any) => `${l.event}: ${l.selection} @ ${odds(l.odds)}`).join(" | ")}</td>
                <td className="num">{odds(p.total_odds)}</td><td className="num">{pct(p.joint_probability)}</td><td className="num">{signedPct(p.ev)}</td>
                <td><StatusBadge status={ST[p.status] || "info"}>{STATUS_LABEL[p.status] || p.status}</StatusBadge></td></tr>
            ))}</tbody></table></div>
        )}
      </Card>
    </div>
  );
}
