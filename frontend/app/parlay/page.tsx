"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { Badge, Card, Disclaimer, Empty, ErrorBox, Loading, PageHeader, StatusBadge } from "@/components/ui";
import { api } from "@/lib/api";
import { addBet } from "@/lib/bets";
import StakeHint from "@/components/StakeHint";
import { bogota, cop, odds, pct, signedPct, SPORT_LABEL } from "@/lib/format";

const PRESETS = [2, 3, 5, 10, 15, 20, 30, 50, 100];
const SPORTS = ["football", "basketball", "tennis", "baseball", "volleyball"];
const MODE_LABEL: Record<string, string> = { conservative: "Conservador", balanced: "Equilibrado", value: "Valor", min_legs: "Mínimas selecciones" };

function sliderToOdds(v: number) {
  // Escala logarítmica 1.5 → 100
  return +Math.exp(Math.log(1.5) + (Math.log(100) - Math.log(1.5)) * (v / 1000)).toFixed(2);
}
function oddsToSlider(o: number) {
  return Math.round(((Math.log(o) - Math.log(1.5)) / (Math.log(100) - Math.log(1.5))) * 1000);
}

function ParlayCard({ k, a, stake }: { k: string; a: any; stake: number }) {
  const [showCmp, setShowCmp] = useState(false);
  if (!a.available) return (
    <Card title={`Parlay ${k} · ${a.label}`}><Empty>No hay una combinación suficientemente sólida para este criterio.</Empty></Card>
  );
  const v = a.validation;
  return (
    <Card title={`Parlay ${k} · ${a.label}`} right={a.reference ? <StatusBadge status="warning">Cuotas de referencia</StatusBadge> : v.valid ? <StatusBadge status="good">Validada</StatusBadge> : <StatusBadge status="warning">Revisar validación</StatusBadge>}>
      {a.reference && <p className="mb-3 rounded-lg border border-warning/40 bg-warning/10 p-2 text-xs text-warning">Cuotas promedio de casas internacionales, no de una casa colombiana. Busque estas mismas selecciones en su casa y compare: si allá pagan menos, el valor esperado baja.</p>}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <div><div className="text-xs text-ink-muted">Operador</div><div className="font-semibold">{a.operator_name}</div></div>
        <div><div className="text-xs text-ink-muted">Cuota total</div><div className="text-2xl font-semibold num">{odds(a.total_odds)}</div></div>
        <div><div className="text-xs text-ink-muted">Prob. conjunta estimada</div><div className="text-2xl font-semibold num">{pct(a.joint_probability)}</div>
          {a.joint_probability_low != null && <div className="text-[11px] text-ink-muted num">intervalo {pct(a.joint_probability_low)}–{pct(a.joint_probability_high)}</div>}</div>
        <div><div className="text-xs text-ink-muted">Valor esperado</div><div className={`text-2xl font-semibold num ${a.ev > 0 ? "text-good" : "text-ink-2"}`}>{signedPct(a.ev)}</div>
          <div className="text-[11px] text-ink-muted num">cuota justa {odds(a.fair_total_odds)}</div>
          <StakeHint p={a.joint_probability} odds={a.total_odds} /></div>
      </div>
      <p className="mt-2 text-xs text-ink-muted">{a.explanation}</p>
      <table className="data mt-3">
        <thead><tr><th>Evento</th><th>Selección</th><th>Cuota</th><th>Prob.</th><th>EV</th><th>Hora consulta</th></tr></thead>
        <tbody>
          {a.legs.map((l: any, i: number) => (
            <tr key={i}>
              <td>{l.event}<div className="text-[11px] text-ink-muted">{SPORT_LABEL[l.sport]} · {l.competition} · {bogota(l.start_time)}</div></td>
              <td>{l.selection}{l.components && <div className="text-[11px] text-warning">{l.same_event_note}</div>}</td>
              <td className="num">{odds(l.odds)}</td><td className="num">{pct(l.probability)}</td>
              <td className={`num ${l.ev > 0 ? "text-good" : "text-ink-2"}`}>{signedPct(l.ev)}</td>
              <td className="num text-ink-muted">{bogota(l.captured_at, false)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="mt-3 grid gap-2 text-sm sm:grid-cols-3">
        <div className="rounded-lg bg-surface-2 p-2"><div className="text-xs text-ink-muted">Inversión</div><div className="num">{cop(stake)}</div></div>
        <div className="rounded-lg bg-surface-2 p-2"><div className="text-xs text-ink-muted">Retorno potencial</div><div className="num">{cop(stake * a.total_odds)}</div></div>
        <div className="rounded-lg bg-surface-2 p-2"><div className="text-xs text-ink-muted">Ganancia potencial</div><div className="num">{cop(stake * (a.total_odds - 1))}</div></div>
      </div>
      <details className="mt-3">
        <summary className="cursor-pointer text-xs text-ink-2">Validación ({v.checks.filter((c: any) => c.ok).length}/{v.checks.length} controles)</summary>
        <ul className="mt-2 space-y-1 text-xs">
          {v.checks.map((c: any) => (
            <li key={c.check}><StatusBadge status={c.ok ? (c.level === "info" ? "info" : "good") : c.level === "warning" ? "warning" : "critical"}>{c.check.replaceAll("_", " ")}</StatusBadge> <span className="text-ink-2">{c.detail}</span></li>
          ))}
        </ul>
      </details>
      <div className="mt-3 flex flex-wrap gap-2">
        <button className="btn-ghost" onClick={() => setShowCmp(!showCmp)}>{showCmp ? "Ocultar" : "Comparar casas"}</button>
        <button className="btn-ghost" onClick={() => {
          const legs = a.legs.flatMap((l: any) => l.components || [l]).map((l: any) => ({ event_id: l.event_id, event: l.event, selection_key: l.selection_key, selection: l.selection, odds: l.odds, start_time: l.start_time }));
          addBet({ operator: a.operator, stake_cop: stake, odds: a.total_odds, legs, description: `Parlay ${k} (${a.label})` });
          alert("Registrada en Mis apuestas. Recuerde: la plataforma no coloca apuestas; regístrela solo si la hizo en su casa.");
        }}>Registrar como apostada</button>
      </div>
      {showCmp && <Comparison cmp={a.comparison} />}
    </Card>
  );
}

function Comparison({ cmp }: { cmp: any }) {
  const ops = Object.keys(cmp.per_operator_totals);
  return (
    <div className="mt-3 overflow-x-auto">
      <table className="data min-w-[640px]">
        <thead><tr><th>Selección</th>{ops.map((o) => <th key={o}>{cmp.per_operator_totals[o].name}</th>)}</tr></thead>
        <tbody>
          {cmp.rows.map((r: any, i: number) => (
            <tr key={i}><td className="text-xs">{r.event}<br /><span className="text-ink-2">{r.selection}</span></td>
              {ops.map((o) => <td key={o} className={`num ${r.best_operator === o ? "font-semibold text-good" : ""}`}>{r.offers[o] ? odds(r.offers[o].odds) : <span className="text-ink-muted">no ofrece</span>}</td>)}
            </tr>
          ))}
          <tr><td className="font-semibold">Cuota total en una casa</td>
            {ops.map((o) => <td key={o} className={`num font-semibold ${cmp.best_single_operator === o ? "text-good" : ""}`}>{cmp.per_operator_totals[o].complete ? odds(cmp.per_operator_totals[o].total_odds) : "incompleta"}</td>)}</tr>
        </tbody>
      </table>
      <p className="mt-1 text-[11px] text-ink-muted">{cmp.note}</p>
    </div>
  );
}

export default function ParlayPage() {
  const [target, setTarget] = useState(5);
  const [manual, setManual] = useState("5");
  const [minOdds, setMinOdds] = useState("");
  const [maxOdds, setMaxOdds] = useState("");
  const [minLegs, setMinLegs] = useState(2);
  const [maxLegs, setMaxLegs] = useState(6);
  const [risk, setRisk] = useState<"low" | "medium" | "high">("medium");
  const [sports, setSports] = useState<string[]>(["football"]);
  const [ops, setOps] = useState<string[]>([]);
  const [operators, setOperators] = useState<any[]>([]);
  const [markets, setMarkets] = useState<Record<string, any>>({});
  const [selMarkets, setSelMarkets] = useState<string[]>([]);
  const [sameEvent, setSameEvent] = useState(false);
  const [sameDay, setSameDay] = useState(false);
  const [useRef, setUseRef] = useState(true);
  const [hours, setHours] = useState(72);
  const [stake, setStake] = useState(10000);
  const [res, setRes] = useState<any>(null);
  const [err, setErr] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const t = Number(new URLSearchParams(window.location.search).get("target"));
    if (t > 1) { setTarget(t); setManual(String(t)); }
    api("/operators").then((d) => setOperators(d.operators.filter((o: any) => o.status === "authorized"))).catch(() => {});
    api("/markets").then((d) => setMarkets(d.markets)).catch(() => {});
  }, []);

  const search = async () => {
    setBusy(true); setErr(null);
    try {
      setRes(await api("/parlay/search", { method: "POST", json: {
        target_odds: target, min_odds: minOdds ? +minOdds : null, max_odds: maxOdds ? +maxOdds : null,
        min_legs: minLegs, max_legs: maxLegs, risk, sports: sports.length ? sports : null, operators: ops.length ? ops : null,
        markets: selMarkets.length ? selMarkets : null, allow_same_event: sameEvent, same_day_only: sameDay, max_hours_ahead: hours,
        use_reference: useRef,
      } }));
    } catch (e) { setErr(e); setRes(null); } finally { setBusy(false); }
  };
  useEffect(() => {
    setSelMarkets((sel) => sel.filter((k) => !sports.length || sports.includes(markets[k]?.sport)));
  }, [sports, markets]);
  const toggle = (arr: string[], set: (x: string[]) => void, v: string) => set(arr.includes(v) ? arr.filter((x) => x !== v) : [...arr, v]);

  return (
    <div className="space-y-4">
      <PageHeader title="PARLAY AI · BUSCAR MI CUOTA"
        subtitle="Indique la cuota que quiere alcanzar. El sistema evalúa todas las selecciones con cuota de operadores autorizados, las valora con los modelos y resuelve de forma exacta qué combinación maximiza la probabilidad conjunta (o el valor esperado) dentro de la banda pedida." />
      <div className="grid gap-4 xl:grid-cols-3">
        <Card title="Cuota objetivo" className="xl:col-span-1">
          <div className="flex items-baseline gap-3">
            <div className="text-5xl font-semibold num">{target.toFixed(2)}</div>
            <input className="input w-24" value={manual} inputMode="decimal" aria-label="Cuota manual"
              onChange={(e) => { setManual(e.target.value); const v = parseFloat(e.target.value.replace(",", ".")); if (v > 1.01 && v <= 1000) setTarget(v); }} />
          </div>
          <input type="range" min={0} max={1000} className="odds-slider mt-3" value={oddsToSlider(Math.min(Math.max(target, 1.5), 100))}
            onChange={(e) => { const v = sliderToOdds(+e.target.value); setTarget(v); setManual(String(v)); }} aria-label="Barra de cuota objetivo" />
          <div className="mt-2 flex flex-wrap gap-1">
            {PRESETS.map((p) => <button key={p} className={`tab num ${target === p ? "tab-active" : ""}`} onClick={() => { setTarget(p); setManual(String(p)); }}>{p.toFixed(2)}</button>)}
          </div>
          <div className="mt-4 grid grid-cols-2 gap-3">
            <div><label className="label">Cuota mínima</label><input className="input" placeholder={(target * 0.9).toFixed(2)} value={minOdds} onChange={(e) => setMinOdds(e.target.value)} /></div>
            <div><label className="label">Cuota máxima</label><input className="input" placeholder={(target * 1.15).toFixed(2)} value={maxOdds} onChange={(e) => setMaxOdds(e.target.value)} /></div>
            <div><label className="label">Mín. selecciones</label><input type="number" min={1} max={15} className="input" value={minLegs} onChange={(e) => setMinLegs(+e.target.value)} /></div>
            <div><label className="label">Máx. selecciones</label><input type="number" min={1} max={15} className="input" value={maxLegs} onChange={(e) => setMaxLegs(+e.target.value)} /></div>
            <div><label className="label">Riesgo aceptado</label>
              <select className="input" value={risk} onChange={(e) => setRisk(e.target.value as any)}>
                <option value="low">Bajo (selecciones ≥ 55 %)</option><option value="medium">Medio (≥ 40 %)</option><option value="high">Alto (≥ 20 %)</option>
              </select></div>
            <div><label className="label">Horizonte (horas)</label><input type="number" className="input" value={hours} onChange={(e) => setHours(+e.target.value)} /></div>
            <div className="col-span-2"><label className="label">Inversión (COP)</label><input type="number" className="input" value={stake} onChange={(e) => setStake(+e.target.value)} /></div>
          </div>
        </Card>
        <Card title="Filtros" className="xl:col-span-2">
          <label className="label">Deportes (seleccione varios para parlays mixtos)</label>
          <div className="mb-3 flex flex-wrap gap-1">{SPORTS.map((s) => <button key={s} className={`tab ${sports.includes(s) ? "tab-active" : ""}`} onClick={() => toggle(sports, setSports, s)}>{SPORT_LABEL[s]}</button>)}</div>
          <label className="label">Operadores autorizados (vacío = todos)</label>
          <div className="mb-3 flex flex-wrap gap-1">{operators.map((o) => <button key={o.key} className={`tab ${ops.includes(o.key) ? "tab-active" : ""}`} onClick={() => toggle(ops, setOps, o.key)}>{o.name}</button>)}</div>
          <label className="label">Mercados (vacío = todos)</label>
          <div className="mb-3 flex flex-wrap gap-1">{Object.entries(markets).filter(([, m]: any) => !sports.length || sports.includes(m.sport)).map(([k, m]: any) => <button key={k} className={`tab text-xs ${selMarkets.includes(k) ? "tab-active" : ""}`} onClick={() => toggle(selMarkets, setSelMarkets, k)}>{m.label}</button>)}</div>
          <div className="flex flex-wrap gap-4 text-sm text-ink-2">
            <label className="flex items-center gap-2"><input type="checkbox" checked={sameDay} onChange={(e) => setSameDay(e.target.checked)} /> Solo partidos de hoy</label>
            <label className="flex items-center gap-2"><input type="checkbox" checked={useRef} onChange={(e) => setUseRef(e.target.checked)} /> Si no hay cuotas colombianas, usar cuotas de referencia internacionales (para verificar en su casa)</label>
            <label className="flex items-center gap-2"><input type="checkbox" checked={sameEvent} onChange={(e) => setSameEvent(e.target.checked)} /> Permitir mercados del mismo partido (solo casas que lo permiten; probabilidad conjunta simulada)</label>
          </div>
          <button className="btn-primary mt-4" onClick={search} disabled={busy}>{busy ? "Analizando…" : "BUSCAR MI CUOTA"}</button>
        </Card>
      </div>

      {busy && <Loading label="Consultando eventos, valorando mercados con los modelos y optimizando…" />}
      <ErrorBox error={err} />
      {res && (
        <>
          <Card title="Resumen del análisis">
            <div className="flex flex-wrap gap-2 text-xs">
              <Badge>Banda {odds(res.band[0])} – {odds(res.band[1])}</Badge>
              <Badge>{res.considered.candidates_in} selecciones valoradas</Badge>
              <Badge>{res.considered.candidates_used} cumplen filtros</Badge>
              {res.reference ? <Badge>Cuotas de referencia internacional</Badge> : <Badge>{res.model_report.events_with_quotes} eventos con cuotas CO</Badge>}
              {!res.reference && <Badge>Operadores: {res.considered.operators.join(", ") || "ninguno"}</Badge>}
            </div>
            {res.messages.map((m: string) => <p key={m} className="mt-2 text-sm text-warning">{m}</p>)}
            {res.model_report.events_with_quotes === 0 && <p className="mt-2 text-sm text-ink-2">Todavía no llegan cuotas de casas colombianas. Para recibirlas solas, el administrador debe crear el secreto gratuito <code>ODDSPAPI_KEY</code> (BetPlay y Rushbet). Mientras tanto puede cargar las cuotas de su casa con <Link className="text-accent underline" href="/captura">una foto</Link> o en Configuración → Mis cuotas.</p>}
            {Object.keys(res.considered.discarded || {}).length > 0 && (
              <details className="mt-2 text-xs text-ink-2"><summary className="cursor-pointer">Selecciones descartadas</summary>
                <ul className="mt-1">{Object.entries(res.considered.discarded).map(([k, v]: any) => <li key={k}>{k}: {v}</li>)}</ul></details>
            )}
            {res.modes_comparison.length > 0 && (
              <table className="data mt-3"><thead><tr><th>Parlay</th><th>Modo</th><th>Casa</th><th>Selecciones</th><th>Cuota</th><th>Prob. conjunta</th><th>EV</th></tr></thead>
                <tbody>{res.modes_comparison.map((r: any) => (
                  <tr key={r.parlay}><td>{r.parlay}</td><td>{MODE_LABEL[r.mode]}</td><td>{r.operator}</td><td className="num">{r.n_legs}</td><td className="num">{odds(r.total_odds)}</td><td className="num">{pct(r.joint_probability)}</td><td className="num">{signedPct(r.ev)}</td></tr>
                ))}</tbody></table>
            )}
          </Card>
          <div className="grid gap-4 xl:grid-cols-2">
            {["A", "B", "C", "D"].map((k) => <ParlayCard key={k} k={k} a={res.alternatives[k]} stake={stake} />)}
          </div>
          <Disclaimer />
        </>
      )}
    </div>
  );
}
