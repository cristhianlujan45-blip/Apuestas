"use client";
import Link from "next/link";
import { useState } from "react";
import { Card, Empty, ErrorBox, Loading, PageHeader, StatusBadge } from "@/components/ui";
import { addBet } from "@/lib/bets";
import { bogota, odds, pct, signedPct } from "@/lib/format";
import { useApi } from "@/lib/useApi";
import StakeHint from "@/components/StakeHint";

export default function StaleLines() {
  const [edge, setEdge] = useState(0.02);
  const { data, error, loading } = useApi(`/stale-lines?min_edge=${edge}`, [edge], 120000);
  const lines: any[] = data?.lines || [];
  const late = lines.filter((l) => l.status === "retrasada");
  return (
    <div className="space-y-4">
      <PageHeader title="Cuotas retrasadas"
        subtitle="Pinnacle y el mercado internacional ajustan sus cuotas en cuanto entra dinero informado; las casas colombianas suelen tardar. Aquí aparecen las cuotas colombianas que pagan más que el precio justo de ese mercado, sin depender de ningún modelo propio." />
      <Card title="Ventaja mínima frente al mercado" right={<span className="num text-sm">{pct(edge, 0)}</span>}>
        <input type="range" min={0} max={0.1} step={0.005} value={edge} onChange={(e) => setEdge(+e.target.value)} className="odds-slider" aria-label="Ventaja mínima" />
        <p className="mt-2 text-xs text-ink-muted">
          <b>Retrasada</b>: la referencia se movió (≥ 2 puntos de probabilidad) después del último cambio de la casa colombiana. <b>Sobre el mercado</b>: la casa simplemente paga más que el precio justo.
        </p>
      </Card>
      <Card title={`${late.length} retrasadas · ${lines.length - late.length} sobre el mercado`}>
        {loading ? <Loading /> : error ? <ErrorBox error={error} /> : !lines.length ? (
          <Empty>Ninguna cuota colombiana supera el precio justo del mercado en {pct(edge, 0)} o más. Hacen falta cuotas colombianas (secreto <code>ODDSPAPI_KEY</code>, o cárguelas con una foto) y cuotas de referencia del mismo partido.</Empty>
        ) : (
          <div className="overflow-x-auto"><table className="data min-w-[960px]">
            <thead><tr><th>Estado</th><th>Evento</th><th>Selección</th><th>Casa</th><th>Cuota</th><th>Cuota justa</th><th>Ventaja</th><th>Referencia</th><th>Consulta</th><th /></tr></thead>
            <tbody>{lines.map((l, i) => (
              <tr key={i}>
                <td>{l.status === "retrasada" ? <StatusBadge status="good">Retrasada</StatusBadge> : <StatusBadge status="info">Sobre el mercado</StatusBadge>}</td>
                <td><Link className="hover:text-accent" href={`/partido?id=${l.event_id}`}>{l.event}</Link><div className="text-[11px] text-ink-muted">{bogota(l.start_time)}</div></td>
                <td>{l.selection}</td><td>{l.operator_name}</td><td className="num">{odds(l.odds)}</td><td className="num">{odds(l.fair_odds)}</td>
                <td className="num text-good">{signedPct(l.edge)}<div><StakeHint p={l.p_fair} odds={l.odds} /></div></td>
                <td className="text-xs text-ink-2">{l.explanation}{l.ref_changed_at && <div className="text-ink-muted">movimiento: {bogota(l.ref_changed_at, false)}</div>}</td>
                <td className="num text-ink-muted">{bogota(l.captured_at, false)}</td>
                <td><button className="text-xs text-accent" onClick={() => {
                  const st = Number(prompt("¿Cuánto apostó (COP)?", "10000"));
                  if (st > 0) { addBet({ operator: l.operator, stake_cop: st, odds: l.odds, description: l.selection, legs: [{ event_id: l.event_id, event: l.event, selection_key: l.selection_key, selection: l.selection, odds: l.odds, start_time: l.start_time }] }); alert("Registrada en Mis apuestas"); }
                }}>Registrar</button></td>
              </tr>
            ))}</tbody></table></div>
        )}
        <p className="mt-2 text-xs text-ink-muted">Confirme la cuota en la casa antes de apostar: si ya la corrigió, la ventaja desaparece. Las casas pueden limitar cuentas que aprovechan cuotas retrasadas. La plataforma no coloca apuestas.</p>
      </Card>
    </div>
  );
}
