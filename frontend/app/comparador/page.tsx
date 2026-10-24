"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { Card, Empty, ErrorBox, Loading, PageHeader } from "@/components/ui";
import { api } from "@/lib/api";
import { bogota, odds } from "@/lib/format";
import { useApi } from "@/lib/useApi";

export default function Comparator() {
  const events = useApi("/events?scope=upcoming&limit=300&with_model=false");
  const [ops, setOps] = useState<any[]>([]);
  const [a, setA] = useState("betplay");
  const [b, setB] = useState("wplay");
  const [cmp, setCmp] = useState<any>(null);
  const [err, setErr] = useState<unknown>(null);
  useEffect(() => { api("/operators").then((d) => setOps(d.operators.filter((o: any) => o.status === "authorized"))).catch(() => {}); }, []);
  const compare = () => api(`/odds/operators-compare?a=${a}&b=${b}`).then(setCmp).catch(setErr);
  const withQuotes = (events.data?.events || []).filter((e: any) => e.colombian_operators > 0);

  return (
    <div className="space-y-4">
      <PageHeader title="Comparador inteligente de cuotas" subtitle="Mejor cuota por selección entre operadores autorizados por Coljuegos, diferencias entre casas, margen y evolución. Solo cuotas obtenidas de feeds autorizados o cargadas por el usuario; nunca se inventan." />
      <Card title="Comparar dos operadores">
        <div className="flex flex-wrap items-end gap-3">
          <div><label className="label">Operador A</label><select className="input" value={a} onChange={(e) => setA(e.target.value)}>{ops.map((o) => <option key={o.key} value={o.key}>{o.name}</option>)}</select></div>
          <div><label className="label">Operador B</label><select className="input" value={b} onChange={(e) => setB(e.target.value)}>{ops.map((o) => <option key={o.key} value={o.key}>{o.name}</option>)}</select></div>
          <button className="btn-primary" onClick={compare}>Comparar</button>
        </div>
        <ErrorBox error={err} />
        {cmp && (cmp.common_selections === 0 ? <Empty>No hay selecciones comunes con cuota de ambos operadores.</Empty> : (
          <div className="mt-3 grid grid-cols-2 gap-3 md:grid-cols-5 text-sm">
            <div><div className="text-xs text-ink-muted">Selecciones comunes</div><div className="text-xl num">{cmp.common_selections}</div></div>
            <div><div className="text-xs text-ink-muted">{a} mejor</div><div className="text-xl num">{cmp.a_better}</div></div>
            <div><div className="text-xs text-ink-muted">{b} mejor</div><div className="text-xl num">{cmp.b_better}</div></div>
            <div><div className="text-xs text-ink-muted">Diferencia media A vs B</div><div className="text-xl num">{cmp.avg_pct_difference_a_vs_b?.toFixed(2)} %</div></div>
            <div><div className="text-xs text-ink-muted">Solo en A / solo en B</div><div className="text-xl num">{cmp.only_in_a} / {cmp.only_in_b}</div></div>
          </div>
        ))}
      </Card>
      <Card title="Eventos con cuotas colombianas">
        {events.loading ? <Loading /> : !withQuotes.length ? <Empty>No hay eventos con cuotas de operadores colombianos. Configure ODDS_API_NET_KEY o cargue cuotas en Configuración.</Empty> : (
          <table className="data"><thead><tr><th>Hora</th><th>Evento</th><th>Competición</th><th>Casas</th><th /></tr></thead>
            <tbody>{withQuotes.map((e: any) => (
              <tr key={e.id}><td className="num">{bogota(e.start_time)}</td><td>{e.label}</td><td>{e.competition}</td><td className="num">{e.colombian_operators}</td>
                <td><Link className="text-accent" href={`/partido?id=${e.id}`}>Comparar mercados →</Link></td></tr>
            ))}</tbody></table>
        )}
      </Card>
      <p className="text-xs text-ink-muted">Formatos: todas las cuotas se muestran en decimal ({odds(2.5)}). Conversión a americana/fraccional disponible en la calculadora.</p>
    </div>
  );
}
