"use client";
import Link from "next/link";
import { useState } from "react";
import { Card, Empty, ErrorBox, Loading, PageHeader } from "@/components/ui";
import { bogota, odds, pct, signedPct } from "@/lib/format";
import { useApi } from "@/lib/useApi";

export default function Value() {
  const [edge, setEdge] = useState(0.02);
  const { data, error, loading } = useApi(`/value?min_edge=${edge}`, [edge]);
  return (
    <div className="space-y-4">
      <PageHeader title="Detector de valor estadístico"
        subtitle="Compara la probabilidad del modelo con la probabilidad implícita de cada cuota colombiana. Valor esperado positivo NO es lo mismo que alta probabilidad de acierto: una selección al 30 % puede tener valor y una al 80 % puede no tenerlo." />
      <Card title="Umbral de ventaja mínima" right={<span className="num text-sm">{pct(edge, 0)}</span>}>
        <input type="range" min={0} max={0.15} step={0.01} value={edge} onChange={(e) => setEdge(+e.target.value)} className="odds-slider" aria-label="EV mínimo" />
      </Card>
      <Card>
        {loading ? <Loading /> : error ? <ErrorBox error={error} /> : !data?.value_bets?.length ? (
          <Empty>No hay selecciones con EV ≥ {pct(edge, 0)}. {data?.report?.events_with_quotes === 0 ? "No hay cuotas colombianas cargadas." : "El mercado colombiano está alineado con el modelo para los eventos disponibles."}</Empty>
        ) : (
          <div className="overflow-x-auto"><table className="data min-w-[900px]">
            <thead><tr><th>Evento</th><th>Selección</th><th>Operador</th><th>Cuota</th><th>Prob. implícita</th><th>Prob. modelo</th><th>Cuota justa</th><th>EV</th><th>Kelly ¼</th><th>Consulta</th></tr></thead>
            <tbody>{data.value_bets.map((v: any, i: number) => (
              <tr key={i}><td><Link className="hover:text-accent" href={`/partido/${v.event_id}`}>{v.event}</Link><div className="text-[11px] text-ink-muted">{bogota(v.start_time)}</div></td>
                <td>{v.selection}</td><td>{v.operator}</td><td className="num">{odds(v.odds)}</td><td className="num">{pct(v.implied_probability)}</td>
                <td className="num">{pct(v.probability)}{v.probability_low != null && <span className="text-ink-muted"> ({pct(v.probability_low, 0)}–{pct(v.probability_high, 0)})</span>}</td>
                <td className="num">{odds(v.fair_odds)}</td><td className="num text-good">{signedPct(v.ev)}</td><td className="num">{pct(v.kelly_quarter)}</td><td className="num text-ink-muted">{bogota(v.captured_at, false)}</td></tr>
            ))}</tbody></table></div>
        )}
        <p className="mt-2 text-xs text-ink-muted">{data?.note} El ROI histórico real de estas señales se mide en «Rendimiento de modelos».</p>
      </Card>
    </div>
  );
}
