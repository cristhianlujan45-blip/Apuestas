"use client";
import Link from "next/link";
import { useState } from "react";
import { Card, Empty, ErrorBox, Loading, PageHeader, StatusBadge } from "@/components/ui";
import { bogota, cop, odds, pct, signedPct } from "@/lib/format";
import { useApi } from "@/lib/useApi";

export default function Edge() {
  const [stake, setStake] = useState(100000);
  const sb = useApi(`/surebets?stake=${stake}`, [stake], 120000);
  const value = useApi("/value?min_edge=0.02", [], 120000);
  return (
    <div className="space-y-4">
      <PageHeader title="Surebets y ventaja frente a las casas"
        subtitle="Tres fuentes de ventaja medibles: arbitraje entre casas (beneficio garantizado), cuotas por encima de la probabilidad justa (valor esperado positivo) y elegir siempre la casa que mejor paga. Nada de esto garantiza ganancias: las cuotas cambian y las casas pueden limitar cuentas." />
      <div className="grid gap-3 md:grid-cols-3">
        <Card title="1 · Surebets (arbitraje)"><p className="text-xs text-ink-2">Si la suma de 1/cuota de todas las salidas, cada una en la casa que más paga, es menor que 1, repartir la inversión asegura ganancia sea cual sea el resultado.</p></Card>
        <Card title="2 · Valor esperado"><p className="text-xs text-ink-2">La probabilidad justa se estima con el ensemble (que incluye el mercado internacional sin margen). Una cuota colombiana por encima de la cuota justa tiene EV positivo a largo plazo.</p></Card>
        <Card title="3 · Mejor precio"><p className="text-xs text-ink-2">Para la misma apuesta, las casas pagan distinto. El comparador muestra siempre la mejor cuota disponible; en combinadas, la diferencia se multiplica.</p></Card>
      </div>
      <Card title="Surebets entre operadores autorizados" right={
        <div className="flex items-center gap-2 text-xs text-ink-2">Inversión total <input type="number" className="input w-32" value={stake} onChange={(e) => setStake(+e.target.value || 0)} /></div>}>
        {sb.loading && !sb.data ? <Loading /> : sb.error ? <ErrorBox error={sb.error} /> : !sb.data?.surebets?.length ? (
          <Empty>No hay surebets en este momento entre las cuotas colombianas disponibles. Son poco frecuentes y duran minutos; aparecen cuando hay cuotas de varias casas (feed odds-api.net o cuotas que usted cargue en Configuración).</Empty>
        ) : (
          <div className="space-y-3">
            {sb.data.surebets.map((s: any, i: number) => (
              <div key={i} className="rounded-lg border border-good/40 p-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <Link href={`/partido?id=${s.event_id}`} className="font-semibold hover:text-accent">{s.event}</Link>
                  <StatusBadge status="good">Beneficio garantizado {s.profit_pct.toFixed(2)} %</StatusBadge>
                </div>
                <div className="mt-1 text-xs text-ink-muted">{s.market}{s.line != null ? ` · línea ${s.line}` : ""}</div>
                <div className="overflow-x-auto"><table className="data mt-2 min-w-[520px]"><thead><tr><th>Selección</th><th>Casa</th><th>Cuota</th><th>Apostar</th><th>Retorno</th><th>Consulta</th></tr></thead>
                  <tbody>{s.legs.map((l: any, j: number) => (
                    <tr key={j}><td>{l.selection_label}</td><td>{l.operator}</td><td className="num">{odds(l.odds)}</td><td className="num">{cop(l.stake_cop)}</td><td className="num">{cop(l.return_cop)}</td><td className="num text-ink-muted">{bogota(l.captured_at, false)}</td></tr>
                  ))}</tbody></table></div>
                <p className="mt-2 text-sm num">Invierte {cop(s.total_stake_cop)} → retorno asegurado ≈ {cop(s.guaranteed_return_cop)} (ganancia {cop(s.guaranteed_return_cop - s.total_stake_cop)})</p>
                <p className="mt-1 text-[11px] text-warning">{s.warning}</p>
              </div>
            ))}
          </div>
        )}
      </Card>
      <Card title="Mejores oportunidades de valor esperado" right={<Link href="/valor" className="text-xs text-accent">Ver todas</Link>}>
        {value.loading && !value.data ? <Loading /> : !value.data?.value_bets?.length ? <Empty>Sin selecciones con EV ≥ 2 % en las cuotas colombianas disponibles.</Empty> : (
          <div className="overflow-x-auto"><table className="data min-w-[560px]"><thead><tr><th>Evento</th><th>Selección</th><th>Casa</th><th>Cuota</th><th>Justa</th><th>Prob.</th><th>EV</th></tr></thead>
            <tbody>{value.data.value_bets.slice(0, 10).map((v: any, i: number) => (
              <tr key={i}><td>{v.event}</td><td>{v.selection}</td><td>{v.operator}</td><td className="num">{odds(v.odds)}</td><td className="num">{odds(v.fair_odds)}</td><td className="num">{pct(v.probability)}</td><td className="num text-good">{signedPct(v.ev)}</td></tr>
            ))}</tbody></table></div>
        )}
      </Card>
      <Card title="Lo que dicen los datos">
        <p className="text-sm text-ink-2">En la validación con miles de partidos reales, el precio de mercado sin margen y el ensemble de la plataforma predicen prácticamente igual, y mejor que cualquier modelo aislado. Por eso la ventaja real no está en "adivinar" mejor que el mercado, sino en encontrar casas colombianas cuya cuota supera ese precio justo, en el arbitraje y en no aceptar nunca una cuota peor que la mejor disponible. Las combinadas multiplican el margen de la casa: úselas solo cuando cada selección tenga valor.</p>
      </Card>
    </div>
  );
}
