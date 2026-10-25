"use client";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { Card, Empty, ErrorBox, Loading, PageHeader } from "@/components/ui";
import { api } from "@/lib/api";
import { bonusPlans, coverPlan, type BonusKind } from "@/lib/engine";
import { bogota, cop, odds, pct } from "@/lib/format";
import { useApi } from "@/lib/useApi";

const KIND_LABEL: Record<BonusKind, string> = {
  freebet_snr: "Apuesta gratis (no devuelve el importe)",
  freebet_sr: "Apuesta gratis (devuelve el importe)",
  qualifying: "Apuesta de calificación (dinero real para liberar un bono)",
};

function Manual() {
  const [kind, setKind] = useState<BonusKind>("freebet_snr");
  const [amount, setAmount] = useState(50000);
  const [back, setBack] = useState("3.00");
  const [cover, setCover] = useState("1.50");
  const covers = cover.split(/[\s;/]+/).map((x) => parseFloat(x.replace(",", "."))).filter((x) => x > 1);
  const b = parseFloat(back.replace(",", "."));
  const plan = b > 1 && covers.length ? coverPlan(kind, amount, b, covers) : null;
  return (
    <Card title="Calculadora manual">
      <div className="grid gap-3 sm:grid-cols-2">
        <div><label className="label">Tipo</label>
          <select className="input" value={kind} onChange={(e) => setKind(e.target.value as BonusKind)}>
            {Object.entries(KIND_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></div>
        <div><label className="label">Importe (COP)</label><input type="number" className="input" value={amount} onChange={(e) => setAmount(+e.target.value)} /></div>
        <div><label className="label">Cuota en la casa del bono</label><input className="input" inputMode="decimal" value={back} onChange={(e) => setBack(e.target.value)} /></div>
        <div><label className="label">Cuota(s) de cobertura en otra casa (1X2: dos cuotas separadas por espacio)</label>
          <input className="input" value={cover} onChange={(e) => setCover(e.target.value)} /></div>
      </div>
      {plan && (
        <div className="mt-3 grid gap-2 text-sm sm:grid-cols-3">
          <div className="rounded-lg bg-surface-2 p-2"><div className="text-xs text-ink-muted">Cubrir con</div>
            {plan.covers.map((c, i) => <div key={i} className="num">{cop(c.stake)} a {odds(c.odds)}</div>)}</div>
          <div className="rounded-lg bg-surface-2 p-2"><div className="text-xs text-ink-muted">{kind === "qualifying" ? "Resultado (pérdida mínima)" : "Ganancia asegurada"}</div>
            <div className={`num text-lg ${plan.result >= 0 ? "text-good" : "text-warning"}`}>{cop(plan.result)}</div></div>
          <div className="rounded-lg bg-surface-2 p-2"><div className="text-xs text-ink-muted">{kind === "qualifying" ? "Costo sobre lo apostado" : "Conversión del bono"}</div>
            <div className="num text-lg">{pct(plan.conversion)}</div></div>
        </div>
      )}
    </Card>
  );
}

export default function Bonos() {
  const { data, error, loading } = useApi("/quotes", [], 300000);
  const [operators, setOperators] = useState<any[]>([]);
  const [op, setOp] = useState("betplay");
  const [kind, setKind] = useState<BonusKind>("freebet_snr");
  const [amount, setAmount] = useState(50000);
  const [minOdds, setMinOdds] = useState(1.5);
  const [same, setSame] = useState(false);
  useEffect(() => { api("/operators").then((d) => setOperators(d.operators.filter((o: any) => o.status === "authorized"))).catch(() => {}); }, []);
  const names = useMemo(() => Object.fromEntries(operators.map((o) => [o.key, o.name])), [operators]);
  const plans = useMemo(() => data?.quotes ? bonusPlans(data.quotes, { operator: op, kind, amount, min_odds: minOdds, same_house_cover: same }, names) : [], [data, op, kind, amount, minOdds, same, names]);
  const houses = new Set((data?.quotes || []).map((q: any) => q.operator));

  return (
    <div className="space-y-4">
      <PageHeader title="Bonos y apuestas gratis"
        subtitle="Las casas autorizadas regalan bonos de bienvenida y apuestas gratis. Cubriendo la apuesta con el resultado contrario en otra casa, el resultado es el mismo pase lo que pase: así una apuesta gratis se convierte en saldo con muy poco riesgo." />
      <Card title="Su bono">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
          <div><label className="label">Casa del bono</label>
            <select className="input" value={op} onChange={(e) => setOp(e.target.value)}>
              {operators.map((o) => <option key={o.key} value={o.key}>{o.name}{houses.has(o.key) ? "" : " (sin cuotas)"}</option>)}</select></div>
          <div className="lg:col-span-2"><label className="label">Tipo</label>
            <select className="input" value={kind} onChange={(e) => setKind(e.target.value as BonusKind)}>
              {Object.entries(KIND_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></div>
          <div><label className="label">Importe (COP)</label><input type="number" className="input" value={amount} onChange={(e) => setAmount(+e.target.value)} /></div>
          <div><label className="label">Cuota mínima exigida</label><input type="number" step="0.05" className="input" value={minOdds} onChange={(e) => setMinOdds(+e.target.value)} /></div>
        </div>
        <label className="mt-3 flex items-center gap-2 text-sm text-ink-2"><input type="checkbox" checked={same} onChange={(e) => setSame(e.target.checked)} /> Permitir cubrir en la misma casa (algunas casas lo prohíben en las condiciones del bono)</label>
        <p className="mt-2 text-xs text-ink-muted">Lea las condiciones del bono: cuota mínima, mercados válidos, plazo y si el importe se devuelve. Una apuesta gratis rinde más a cuotas altas; una apuesta de calificación, a cuotas bajas con poca diferencia entre casas.</p>
      </Card>

      <Card title="Mejores coberturas con las cuotas disponibles">
        {loading ? <Loading /> : error ? <ErrorBox error={error} /> : !plans.length ? (
          <Empty>No hay combinaciones con cuotas de {names[op] || op} y de otra casa para el mismo mercado. Hacen falta cuotas de al menos dos casas colombianas (secreto <code>ODDSPAPI_KEY</code> o <Link className="text-accent underline" href="/captura">cuotas desde foto</Link>). Mientras tanto use la calculadora manual.</Empty>
        ) : (
          <div className="overflow-x-auto"><table className="data min-w-[900px]">
            <thead><tr><th>Evento</th><th>Apostar con el bono</th><th>Cubrir</th><th>Efectivo necesario</th><th>{kind === "qualifying" ? "Resultado" : "Ganancia asegurada"}</th><th>Conversión</th></tr></thead>
            <tbody>{plans.map((p, i) => (
              <tr key={i}>
                <td><Link className="hover:text-accent" href={`/partido?id=${p.event_id}`}>{p.event}</Link><div className="text-[11px] text-ink-muted">{bogota(p.start_time)}</div></td>
                <td className="text-sm">{p.back.selection}<div className="num text-xs text-ink-2">{cop(p.back.stake)} a {odds(p.back.odds)} en {p.back.operator_name}</div></td>
                <td className="text-sm">{p.covers.map((c: any, j: number) => <div key={j}>{c.selection}<div className="num text-xs text-ink-2">{cop(c.stake)} a {odds(c.odds)} en {c.operator_name}</div></div>)}</td>
                <td className="num">{cop(p.cash_needed)}</td>
                <td className={`num ${p.result >= 0 ? "text-good" : "text-warning"}`}>{cop(p.result)}</td>
                <td className="num">{pct(p.conversion)}</td>
              </tr>
            ))}</tbody></table></div>
        )}
        <p className="mt-2 text-xs text-ink-muted">Confirme cada cuota en las casas antes de apostar y haga primero la apuesta del bono. Las casas pueden limitar cuentas que solo usan promociones. Juegue con responsabilidad: la plataforma no coloca apuestas ni mueve dinero.</p>
      </Card>
      <Manual />
    </div>
  );
}
