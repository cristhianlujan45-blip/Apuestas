"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { Card, ErrorBox, PageHeader } from "@/components/ui";
import { api } from "@/lib/api";
import { cop, odds, pct } from "@/lib/format";

export default function CalculatorPage() {
  const [stake, setStake] = useState(10000);
  const [o, setO] = useState(10);
  const [profit, setProfit] = useState(90000);
  const [capital, setCapital] = useState(200000);
  const [prob, setProb] = useState<string>("");
  const [res, setRes] = useState<any>(null);
  const [fmt, setFmt] = useState<any>(null);
  const [err, setErr] = useState<unknown>(null);
  useEffect(() => {
    const t = setTimeout(() => {
      api("/calculator", { method: "POST", json: { stake_cop: stake, odds: o, target_profit_cop: profit, capital_cop: capital, probability: prob ? +prob / 100 : null } })
        .then((r) => { setRes(r); setErr(null); }).catch(setErr);
      if (o > 1) api(`/odds/formats?odds=${o}`).then(setFmt).catch(() => {});
    }, 250);
    return () => clearTimeout(t);
  }, [stake, o, profit, capital, prob]);
  return (
    <div className="space-y-4">
      <PageHeader title="Calculadora de ganancias (COP)" subtitle="Retorno, ganancia neta, cuota necesaria para un objetivo y control del capital. Todas las cantidades en pesos colombianos." />
      <div className="grid gap-4 lg:grid-cols-3">
        <Card title="Datos">
          <label className="label">Inversión (COP)</label><input type="number" className="input" value={stake} onChange={(e) => setStake(+e.target.value)} />
          <label className="label mt-3">Cuota</label><input type="number" step="0.01" className="input" value={o} onChange={(e) => setO(+e.target.value)} />
          <label className="label mt-3">Ganancia neta deseada (COP)</label><input type="number" className="input" value={profit} onChange={(e) => setProfit(+e.target.value)} />
          <label className="label mt-3">Capital disponible (COP)</label><input type="number" className="input" value={capital} onChange={(e) => setCapital(+e.target.value)} />
          <label className="label mt-3">Probabilidad estimada (%, opcional)</label><input type="number" className="input" value={prob} onChange={(e) => setProb(e.target.value)} placeholder="del modelo" />
        </Card>
        <Card title="Resultado">
          <ErrorBox error={err} />
          {res?.returns && (<>
            <div className="text-xs text-ink-muted">Retorno potencial</div><div className="text-3xl font-semibold num">{cop(res.returns.potential_return)}</div>
            <div className="mt-2 text-xs text-ink-muted">Ganancia potencial</div><div className="text-2xl num text-good">{cop(res.returns.potential_profit)}</div>
          </>)}
          {res?.expected && <p className="mt-3 text-sm text-ink-2 num">Ganancia esperada según la probabilidad: <b>{cop(res.expected.expected_profit)}</b> · probabilidad de perder {pct(res.expected.probability_of_loss)}</p>}
          {res?.bankroll && (<div className="mt-3 text-sm text-ink-2">
            <p className="num">La inversión es el {pct(res.bankroll.stake_pct_of_capital)} del capital.</p>
            {res.bankroll.warning && <p className="mt-1 text-warning">{res.bankroll.warning}</p>}
            {res.bankroll.kelly_quarter_stake != null && <p className="mt-1 num">Kelly ¼ sugiere {cop(res.bankroll.kelly_quarter_stake)}. {res.bankroll.kelly_note}</p>}
          </div>)}
        </Card>
        <Card title="Buscador inverso">
          {res?.required_odds && (<>
            <p className="text-sm text-ink-2">Para ganar {cop(profit)} invirtiendo {cop(stake)} necesita una cuota de</p>
            <div className="text-4xl font-semibold num">{odds(res.required_odds.required_odds)}</div>
            <p className="text-xs text-ink-muted num">Probabilidad implícita {pct(res.required_odds.implied_probability)}</p>
            <Link className="btn-primary mt-3" href={`/parlay?target=${res.required_odds.required_odds.toFixed(2)}`}>Buscar combinadas para esta cuota</Link>
          </>)}
          {res?.required_stake && <p className="mt-3 text-sm text-ink-2 num">Con cuota {odds(o)}, para ganar {cop(profit)} debe invertir {cop(res.required_stake.required_stake)}.</p>}
          {fmt && <table className="data mt-3"><tbody>{Object.entries(fmt).map(([k, v]: any) => <tr key={k}><td className="text-xs text-ink-muted">{k.replaceAll("_", " ")}</td><td className="num">{String(v)}</td></tr>)}</tbody></table>}
        </Card>
      </div>
    </div>
  );
}
