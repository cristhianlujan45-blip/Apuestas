/**
 * Modo app (estático): responde a las mismas rutas que la API usando los JSON que
 * publica el pipeline de datos y calculando en el dispositivo (lib/engine.ts).
 */
import {
  band, calculator, comparison, describe, evOf, fairOdds, MARKET_LABEL, oddsFormats, optimize, parseKey, pEff, priceAny, priceMatrix, staleLimit, staleLines,
  selKey, surebets, validate, type Cand, type OpInfo, type Req, type Sol,
} from "./engine";

export const DEFAULT_DATA_URL =
  process.env.NEXT_PUBLIC_DATA_URL || "https://raw.githubusercontent.com/cristhianlujan45-blip/Apuestas/datos/data";
const STALE_SEC = 900;
// Las cuotas de referencia (promedio internacional) se publican con cada ejecución del pipeline
const REF_STALE_SEC = 12 * 3600;
export const REFERENCE_NAME = "Referencia internacional (no es casa colombiana)";
const REFERENCE_NOTE = "No hay cuotas de casas colombianas para estos filtros. Se usaron cuotas de REFERENCIA (promedio de casas internacionales): su casa puede pagar distinto. Verifique cada cuota antes de apostar o cárguela en «Cuotas desde foto» para revaluar la combinada.";

// ------------------------------------------------------------------ almacenamiento local
function load<T>(key: string, fallback: T): T {
  try {
    const v = localStorage.getItem(key);
    return v ? (JSON.parse(v) as T) : fallback;
  } catch {
    return fallback;
  }
}
function save(key: string, v: unknown) {
  try {
    localStorage.setItem(key, JSON.stringify(v));
  } catch {
    /* almacenamiento lleno o bloqueado */
  }
}
export const dataUrl = () => load<string>("data_url", DEFAULT_DATA_URL) || DEFAULT_DATA_URL;
export const setDataUrl = (u: string) => save("data_url", u.replace(/\/+$/, ""));

const mem: Record<string, { t: number; v: any }> = {};
export function clearCache() {
  Object.keys(mem).forEach((k) => delete mem[k]);
}
async function file<T = any>(name: string, maxAgeMs = 5 * 60e3): Promise<T> {
  const hit = mem[name];
  if (hit && Date.now() - hit.t < maxAgeMs) return hit.v;
  try {
    const r = await fetch(`${dataUrl()}/${name}?v=${Math.floor(Date.now() / 300e3)}`, { cache: "no-store" });
    if (!r.ok) throw new Error(`${r.status}`);
    const v = await r.json();
    mem[name] = { t: Date.now(), v };
    if (["events.json", "candidates.json", "quotes.json", "operators.json", "status.json", "matrices.json"].includes(name)) save(`cache:${name}`, v);
    return v;
  } catch (e) {
    const cached = load<T | null>(`cache:${name}`, null);
    if (cached) return cached;
    throw new HttpError(503, `Sin conexión con la fuente de datos (${name}). Revise su internet o la URL de datos en Configuración.`);
  }
}

export class HttpError extends Error {
  status: number;
  detail: unknown;
  constructor(status: number, detail: unknown) {
    super(typeof detail === "string" ? detail : (detail as any)?.message || `Error ${status}`);
    this.status = status;
    this.detail = detail;
  }
}

// ------------------------------------------------------------------ cuotas manuales
export type Manual = {
  id: string; event_id: number; operator: string; market: string; selection: string; line: number | null; odds: number; captured_at: string;
};
const manualAll = () => load<Manual[]>("manual_quotes", []);

async function ctx() {
  const [events, cands, quotes, ops, matrices, counts] = await Promise.all([
    file("events.json"), file("candidates.json"), file("quotes.json"), file("operators.json"), file("matrices.json").catch(() => ({})),
    file("counts.json").catch(() => ({})),
  ]);
  const evById: Record<string, any> = {};
  events.events.forEach((e: any) => { evById[e.id] = e; });
  const opList: OpInfo[] = ops.operators;
  const names = Object.fromEntries(opList.map((o) => [o.key, o.name]));
  const manual = manualAll().filter((m) => evById[m.event_id]);
  const manualCands: Cand[] = [];
  const manualQuotes: any[] = [];
  for (const m of manual) {
    const ev = evById[m.event_id];
    const sel = { market: m.market, selection: m.selection, line: m.line, player: null, period: "ft" };
    const key = selKey(sel);
    const label = describe(sel, ev.home, ev.away);
    const age = (Date.now() - new Date(m.captured_at).getTime()) / 1000;
    manualQuotes.push({ event_id: m.event_id, event: ev.label, operator: m.operator, market: m.market, selection: m.selection, selection_key: key,
      selection_label: label, line: m.line, player: null, odds: m.odds, source: "manual", captured_at: m.captured_at, provider_ts: m.captured_at,
      age_seconds: age, stale: age > staleLimit("manual", STALE_SEC), live: false });
    const pr = priceAny(matrices[String(m.event_id)], counts[String(m.event_id)], sel);
    if (!pr) continue;
    manualCands.push({ event_id: m.event_id, event: ev.label, sport: ev.sport, competition: ev.competition, start_time: ev.start_time,
      selection_key: key, selection: label, operator: m.operator, odds: m.odds, captured_at: m.captured_at, probability: pEff(pr),
      probability_low: null, probability_high: null, fair_odds: fairOdds(pr), ev: evOf(pr, m.odds), pricing: pr,
      data_sufficient: !!ev.data_sufficient, is_live: ev.status === "live", source: "manual" });
  }
  // Una cuota manual reemplaza a la del feed para el mismo operador/selección
  const mk = new Set(manualCands.map((c) => `${c.event_id}|${c.selection_key}|${c.operator}`));
  const allCands: Cand[] = cands.candidates.filter((c: Cand) => !mk.has(`${c.event_id}|${c.selection_key}|${c.operator}`)).concat(manualCands);
  const mq = new Set(manualQuotes.map((q) => `${q.event_id}|${q.selection_key}|${q.operator}`));
  const allQuotes = quotes.quotes.filter((q: any) => !mq.has(`${q.event_id}|${q.selection_key}|${q.operator}`)).concat(manualQuotes);
  const refOps = new Set(opList.filter((o) => o.status === "reference_only").map((o) => o.key));
  const refCands: Cand[] = [];
  for (const q of quotes.quotes) {
    if (!refOps.has(q.operator)) continue;
    const ev = evById[q.event_id];
    if (!ev) continue;
    const pr = priceAny(matrices[String(q.event_id)], counts[String(q.event_id)], parseKey(q.selection_key));
    if (!pr) continue;
    refCands.push({ event_id: q.event_id, event: ev.label, sport: ev.sport, competition: ev.competition, start_time: ev.start_time,
      selection_key: q.selection_key, selection: q.selection_label, operator: q.operator, odds: q.odds, captured_at: q.captured_at,
      probability: pEff(pr), probability_low: null, probability_high: null, fair_odds: fairOdds(pr), ev: evOf(pr, q.odds), pricing: pr,
      data_sufficient: !!ev.data_sufficient, is_live: false, source: "referencia" });
  }
  const authorized = new Set(opList.filter((o) => o.status === "authorized").map((o) => o.key));
  const coQuotes = allQuotes.filter((q: any) => authorized.has(q.operator));
  return { events, evById, counts, cands: allCands, refCands, quotes: allQuotes, coQuotes, ops: opList, names, matrices, manual };
}

// ------------------------------------------------------------------ límites locales
type Limits = { daily_stake_cop: number | null; weekly_stake_cop: number | null; monthly_stake_cop: number | null; session_minutes: number | null;
  self_excluded_until: string | null; pending_changes: Record<string, number | null>; pending_effective_at: string | null };
const LIMIT_KEYS = ["daily_stake_cop", "weekly_stake_cop", "monthly_stake_cop", "session_minutes"] as const;
function limits(): Limits {
  const l = load<Limits>("limits", { daily_stake_cop: null, weekly_stake_cop: null, monthly_stake_cop: null, session_minutes: null,
    self_excluded_until: null, pending_changes: {}, pending_effective_at: null });
  if (l.pending_effective_at && new Date(l.pending_effective_at).getTime() <= Date.now()) {
    Object.assign(l, l.pending_changes);
    l.pending_changes = {}; l.pending_effective_at = null;
    save("limits", l);
  }
  return l;
}
function limitsDict() {
  const l = limits();
  const bets = load<any[]>("bets", []);
  const since = (d: number) => bets.filter((b) => Date.now() - new Date(b.placed_at).getTime() < d * 86400e3).reduce((s, b) => s + b.stake_cop, 0);
  return { ...l, usage_cop: { day: since(1), week: since(7), month: since(30) } };
}
function gate() {
  const d = limitsDict();
  if (d.self_excluded_until && new Date(d.self_excluded_until).getTime() > Date.now())
    return { blocked: true, reason: "self_excluded", until: d.self_excluded_until, message: "Autoexclusión activa. Las herramientas de análisis de apuestas están bloqueadas." };
  for (const [k, p] of [["daily_stake_cop", "day"], ["weekly_stake_cop", "week"], ["monthly_stake_cop", "month"]] as const) {
    const cap = d[k];
    if (cap != null && d.usage_cop[p] >= cap) return { blocked: true, reason: `limit_${p}`, message: `Alcanzó su límite de gasto (${p}). Las combinadas se reactivan cuando termine el periodo.` };
  }
  const start = load<number>("session_start", 0);
  if (d.session_minutes && start && (Date.now() - start) / 60e3 > d.session_minutes)
    return { blocked: true, reason: "session_time", message: `Superó su tiempo de sesión de ${d.session_minutes} minutos. Tómese un descanso.` };
  return null;
}
export function touchSession() {
  const last = load<number>("session_last", 0);
  if (!last || Date.now() - last > 30 * 60e3) save("session_start", Date.now());
  save("session_last", Date.now());
}

// ------------------------------------------------------------------ utilidades
const sim = (a: string, b: string) => {
  const n = (s: string) => s.toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/[^a-z0-9 ]/g, " ").trim();
  const x = n(a), y = n(b);
  if (x === y) return 1;
  if (x && y && (x.includes(y) || y.includes(x))) return 0.9;
  const tx = new Set(x.split(/\s+/)), ty = new Set(y.split(/\s+/));
  const inter = [...tx].filter((t) => ty.has(t)).length;
  return inter / new Set([...tx, ...ty]).size;
};
export const bogotaDate = (t: string | number | Date) => new Date(t).toLocaleDateString("en-CA", { timeZone: "America/Bogota" });
const within = (e: any, scope: string) => {
  const t = new Date(e.start_time).getTime(), now = Date.now();
  if (scope === "live") return e.status === "live";
  if (scope === "today") return t >= now - 3 * 3600e3 && t < now + 24 * 3600e3;
  if (scope === "upcoming") return e.status === "scheduled" && t >= now;
  if (scope === "finished") return e.status === "finished";
  return true;
};

async function search(req: Req) {
  const g = gate();
  if (g) throw new HttpError(423, g);
  const c = await ctx();
  let res = optimize(c.cands, req, c.ops, c.matrices, STALE_SEC);
  let reference = false, cands = c.cands, ops = c.ops, stale = STALE_SEC;
  if (req.use_reference !== false && res.considered.candidates_used === 0 && c.refCands.length) {
    const refOps = c.ops.filter((o) => o.status === "reference_only").map((o) => ({ ...o, status: "authorized", capabilities: { parlays: true } }));
    const r2 = optimize(c.refCands, { ...req, operators: null, allow_same_event: false }, refOps, c.matrices, REF_STALE_SEC);
    if (r2.considered.candidates_used) {
      res = r2; reference = true; cands = c.refCands; ops = refOps; stale = REF_STALE_SEC;
      res.messages.unshift(REFERENCE_NOTE);
    }
  }
  const LABELS: Record<string, string> = { A: "Mayor probabilidad estimada", B: "Equilibrio probabilidad / valor", C: "Mejor valor esperado", D: "Menor número de selecciones" };
  const EXPL: Record<string, string> = {
    conservative: "Maximiza la probabilidad conjunta usando la cota inferior de la incertidumbre del modelo.",
    balanced: "Maximiza log P + ½·log(retorno esperado): equilibra acierto y valor.",
    value: "Solo selecciones con EV positivo; maximiza el retorno esperado de la combinada.",
    min_legs: "Busca el menor número de selecciones que alcanza la cuota y, entre ellas, la de mayor probabilidad.",
  };
  const alternatives: Record<string, any> = {};
  const history = load<any[]>("parlays", []);
  for (const [k, sol] of Object.entries(res.alternatives) as [string, Sol | null][]) {
    if (!sol) { alternatives[k] = { label: LABELS[k], available: false }; continue; }
    const v = validate(sol, c.evById, ops.find((o) => o.key === sol.operator), c.matrices, stale);
    const entry = { label: LABELS[k], available: true, explanation: EXPL[sol.mode], reference,
      operator_name: reference ? REFERENCE_NAME : c.names[sol.operator] || sol.operator, ...sol,
      legs: sol.legs, validation: v, comparison: comparison(sol, cands, c.names), parlay_id: `${Date.now()}-${k}` };
    alternatives[k] = entry;
    history.unshift({ id: entry.parlay_id, created_at: new Date().toISOString(), label: k, mode: sol.mode, operator: sol.operator,
      total_odds: sol.total_odds, joint_probability: sol.joint_probability, ev: sol.ev, status: "open",
      legs: sol.legs.map((l) => ({ event: l.event, event_id: l.event_id, selection: l.selection, selection_key: l.selection_key, odds: l.odds })) });
  }
  save("parlays", history.slice(0, 300));
  const evQuotes = new Set(c.cands.map((x) => x.event_id));
  return {
    request: req, band: res.considered.band, alternatives, reference, messages: res.messages, considered: res.considered,
    modes_comparison: Object.entries(alternatives).filter(([, a]) => a.available).map(([k, a]) => ({ parlay: k, mode: a.mode, operator: a.operator, n_legs: a.n_legs, total_odds: a.total_odds, joint_probability: a.joint_probability, ev: a.ev })),
    model_report: { events_with_quotes: evQuotes.size, events_modeled: evQuotes.size },
    generated_at: new Date().toISOString(),
    disclaimer: "Estimaciones estadísticas, no garantías. Juega con responsabilidad.",
  };
}

async function eventDetail(id: string) {
  const [d, c] = await Promise.all([file(`events/${id}.json`, 120e3), ctx()]);
  const ev = c.evById[id];
  const manual = c.manual.filter((m) => String(m.event_id) === id);
  if (!manual.length) return d;
  const rows = [...(d.markets || [])];
  for (const m of manual) {
    const sel = { market: m.market, selection: m.selection, line: m.line, player: null, period: "ft" };
    const key = selKey(sel);
    let row = rows.find((r: any) => r.selection_key === key);
    if (!row) {
      const pr = priceAny(d.matrix, d.model?.counts, sel);
      row = { selection_key: key, market: m.market, market_label: MARKET_LABEL[m.market] || m.market, selection: m.selection, line: m.line,
        label: describe(sel, ev?.home, ev?.away), offers: [], reference: [], missing_operators: [],
        model: pr ? { ...pr, p: pEff(pr), fair_odds: fairOdds(pr), interval: {} } : undefined };
      rows.push(row);
    }
    row.offers = row.offers.filter((o: any) => o.operator !== m.operator);
    const age = (Date.now() - new Date(m.captured_at).getTime()) / 1000;
    row.offers.push({ operator: m.operator, operator_name: c.names[m.operator] || m.operator, odds: m.odds, source: "manual",
      captured_at: m.captured_at, provider_ts: m.captured_at, age_seconds: age, stale: age > staleLimit("manual", STALE_SEC), live: false });
    row.offers.sort((a: any, b: any) => b.odds - a.odds);
    const best = row.offers[0];
    row.best = { ...best };
    row.spread_pct = row.offers.length > 1 ? (best.odds / row.offers[row.offers.length - 1].odds - 1) * 100 : null;
    if (row.model) {
      const pr = { p_win: row.model.p_win, p_half_win: row.model.p_half_win, p_push: row.model.p_push, p_half_lose: row.model.p_half_lose, p_lose: row.model.p_lose };
      row.model.ev_best = evOf(pr, best.odds);
    }
  }
  return { ...d, markets: rows };
}

function teamLookup(teams: Record<string, any>, q: string) {
  let best: string | null = null, score = 0;
  for (const t of Object.keys(teams)) { const s = sim(q, t); if (s > score) { score = s; best = t; } }
  return best && score >= 0.5 ? teams[best] : { error: `Sin histórico reciente para '${q}' (solo equipos con partidos próximos)` };
}

// ------------------------------------------------------------------ asistente local
async function assistant(messages: { role: string; content: string }[]) {
  const g = gate();
  if (g) throw new HttpError(423, g);
  const text = (messages.filter((m) => m.role === "user").pop()?.content || "").toLowerCase();
  const pct = (v: number) => `${(v * 100).toFixed(1)} %`;
  const m = text.match(/cuota\s*(?:de|a|objetivo)?\s*(\d+(?:[.,]\d+)?)/);
  if (m || text.includes("parlay") || text.includes("combinada")) {
    const target = m ? +m[1].replace(",", ".") : 5;
    const legs = text.match(/m[aá]ximo\s+(\d+)\s+selecci/);
    const req: Req = { target_odds: target, min_legs: legs ? Math.min(2, +legs[1]) : 2, max_legs: legs ? +legs[1] : 6, risk: text.includes("mayor probabilidad") ? "low" : "medium",
      sports: text.includes("mixto") ? ["football", "basketball", "tennis", "baseball", "volleyball"] : null };
    const r = await search(req);
    const lines: string[] = [];
    for (const [k, a] of Object.entries(r.alternatives) as [string, any][]) {
      if (!a.available) { lines.push(`**Parlay ${k} (${a.label})**: no disponible.`); continue; }
      lines.push(`**Parlay ${k} — ${a.label}** · ${a.operator_name} · cuota ${a.total_odds.toFixed(2)} · prob. estimada ${pct(a.joint_probability)} · EV ${(a.ev * 100).toFixed(1)} %`);
      a.legs.forEach((l: any) => lines.push(`  - ${l.event}: ${l.selection} @ ${l.odds.toFixed(2)} (p=${pct(l.probability)})`));
    }
    r.messages.forEach((x: string) => lines.push(`_${x}_`));
    if (!r.model_report.events_with_quotes) lines.push("_No hay cuotas de operadores colombianos: cárguelas en Configuración (cuotas manuales) o active el feed._");
    return { answer: lines.join("\n"), tools_used: ["buscar_mi_cuota"], engine: "local" };
  }
  const ops = ["betplay", "wplay", "betsson", "betano", "rushbet", "codere", "bwin", "stake", "rivalo", "luckia", "sportium", "zamba", "yajuego", "mryoker"].filter((o) => text.includes(o));
  if (text.includes("compar") && ops.length >= 2) {
    const r = await route(`/odds/operators-compare?a=${ops[0]}&b=${ops[1]}`);
    const answer = r.common_selections ? `**${ops[0]}** vs **${ops[1]}** en ${r.common_selections} selecciones comunes: ${ops[0]} paga más en ${r.a_better}, ${ops[1]} en ${r.b_better}. Diferencia media ${r.avg_pct_difference_a_vs_b?.toFixed(2)} %.`
      : `No hay selecciones con cuota de ${ops[0]} y ${ops[1]} a la vez.`;
    return { answer, tools_used: ["comparar_operadores"], engine: "local" };
  }
  const last = text.match(/[uú]ltimos\s+(\d+|diez|cinco)\s+partidos\s+(?:de|del)\s+(.+)/);
  if (last) {
    const r = teamLookup(await file("teams.json"), last[2].replace(/[?.]/g, "").trim());
    if (r.error) return { answer: `⚠️ ${r.error}`, tools_used: ["ultimos_partidos"], engine: "local" };
    const lines = [`**${r.team}**: ${r.summary.wins}G ${r.summary.draws}E ${r.summary.losses}P`, ...r.matches.slice().reverse().map((x: any) => `- ${x.date} ${x.venue} vs ${x.opponent}: ${x.score} (${x.result})`)];
    return { answer: lines.join("\n"), tools_used: ["ultimos_partidos"], engine: "local" };
  }
  if (text.includes("surebet") || text.includes("arbitraje") || text.includes("ventaja")) {
    const c = await ctx();
    const sb = surebets(c.coQuotes);
    const answer = sb.length ? sb.slice(0, 5).map((s) => `**${s.event}** (${s.market}): beneficio garantizado ${s.profit_pct.toFixed(2)} % — ${s.legs.map((l: any) => `${l.selection_label} @ ${l.odds} en ${l.operator}`).join(" · ")}`).join("\n")
      : "No hay surebets entre las cuotas colombianas disponibles ahora mismo.";
    return { answer, tools_used: ["surebets"], engine: "local" };
  }
  if (text.includes("valor") || text.includes("oportunidad")) {
    const r = await route("/value?min_edge=0.02");
    const answer = r.value_bets.length ? r.value_bets.slice(0, 10).map((v: any) => `- ${v.event}: ${v.selection} @ ${v.odds.toFixed(2)} (${v.operator}) · p=${pct(v.probability)} · EV ${(v.ev * 100).toFixed(1)} %`).join("\n")
      : "No hay selecciones con valor esperado positivo en las cuotas colombianas disponibles.";
    return { answer, tools_used: ["oportunidades_valor"], engine: "local" };
  }
  const scope = text.includes("directo") || text.includes("en vivo") ? "live" : text.includes("próximos") || text.includes("proximos") ? "upcoming" : "today";
  if (text.includes("analiza") || text.includes("hoy") || scope !== "today") {
    const r = await route(`/events?scope=${scope}`);
    const answer = r.events.length ? r.events.slice(0, 25).map((e: any) => {
      const p = e.live?.probs || e.probs;
      return `- ${new Date(e.start_time).toLocaleString("es-CO", { timeZone: "America/Bogota", hour: "2-digit", minute: "2-digit" })} ${e.label}${p ? ` · L ${pct(p.home)} / E ${pct(p.draw || 0)} / V ${pct(p.away)}` : ""}`;
    }).join("\n") : "No hay partidos en ese rango.";
    return { answer, tools_used: ["partidos"], engine: "local" };
  }
  return { answer: "Puedo analizar los partidos de hoy o en directo, buscar una cuota («busca una cuota de 5»), comparar operadores («compara BetPlay con Wplay»), buscar surebets, oportunidades de valor y los últimos 10 partidos de un equipo.", tools_used: [], engine: "local" };
}

// ------------------------------------------------------------------ enrutador
export async function route(path: string, init: { method?: string; json?: any } = {}): Promise<any> {
  const url = new URL(path, "http://x");
  const p = url.pathname;
  const q = url.searchParams;
  const method = (init.method || "GET").toUpperCase();
  const body = init.json;
  touchSession();

  if (p === "/health") return { ok: true };
  if (p === "/status") {
    const [st, c] = await Promise.all([file("status.json"), ctx()]);
    const auth = new Set(c.ops.filter((o) => o.status === "authorized").map((o) => o.key));
    return { ...st, counts: { ...st.counts, colombian_quotes: c.quotes.filter((x: any) => auth.has(x.operator)).length, manual_quotes: c.manual.length } };
  }
  if (p === "/events/days") {
    const c = await ctx();
    const sport = q.get("sport");
    const days: Record<string, { date: string; count: number; finished: number }> = {};
    c.events.events.filter((e: any) => !sport || e.sport === sport).forEach((e: any) => {
      const d = bogotaDate(e.start_time);
      const r = (days[d] ||= { date: d, count: 0, finished: 0 });
      r.count++; if (e.status === "finished") r.finished++;
    });
    return { days: Object.values(days).sort((a, b) => a.date.localeCompare(b.date)) };
  }
  if (p === "/events") {
    const c = await ctx();
    const scope = q.get("scope") || "upcoming", sport = q.get("sport"), day = q.get("date");
    const counts: Record<string, Set<string>> = {};
    const auth = new Set(c.ops.filter((o) => o.status === "authorized").map((o) => o.key));
    c.quotes.forEach((x: any) => { if (auth.has(x.operator)) (counts[x.event_id] ||= new Set()).add(x.operator); });
    let evs = c.events.events.filter((e: any) => (day ? bogotaDate(e.start_time) === day : within(e, scope)) && (!sport || e.sport === sport));
    if (scope === "finished") evs = evs.reverse();
    evs = evs.slice(0, +(q.get("limit") || 300)).map((e: any) => ({ ...e, colombian_operators: counts[e.id]?.size || 0 }));
    return { scope, events: evs };
  }
  let m = p.match(/^\/events\/(\d+)$/);
  if (m) return eventDetail(m[1]);
  m = p.match(/^\/events\/(\d+)\/simulate$/);
  if (m) {
    const d = await file(`events/${m[1]}.json`, 120e3);
    if (!d.simulation) throw new HttpError(409, d.model_note || "Sin modelo");
    return d.simulation;
  }
  m = p.match(/^\/events\/(\d+)\/odds-history$/);
  if (m) {
    const d = await file(`events/${m[1]}.json`, 120e3);
    const key = q.get("selection_key") || "";
    const manual = manualAll().filter((x) => String(x.event_id) === m![1] && selKey({ market: x.market, selection: x.selection, line: x.line, player: null, period: "ft" }) === key)
      .map((x) => ({ operator: x.operator, odds: x.odds, captured_at: x.captured_at, source: "manual", available: true }));
    return [...(d.histories?.[key] || []), ...manual];
  }
  if (p === "/value") {
    const c = await ctx();
    const min = +(q.get("min_edge") || 0.02);
    const vb = c.cands.filter((x) => x.data_sufficient && x.ev >= min).map((x) => ({ ...x, implied_probability: 1 / x.odds, edge_pct: x.ev * 100,
      kelly_quarter: Math.max(0, (x.probability * x.odds - 1) / (x.odds - 1) / 4) })).sort((a, b) => b.ev - a.ev);
    return { value_bets: vb, report: { events_with_quotes: new Set(c.cands.map((x) => x.event_id)).size }, note: "Valor esperado positivo no equivale a alta probabilidad de acierto." };
  }
  if (p === "/agent") return file("agent.json").catch(() => { throw new HttpError(503, "El agente aún no tiene datos: se generan en la próxima ejecución del pipeline."); });
  if (p === "/results") return file("results.json").catch(() => ({ results: [] }));
  if (p === "/alerts-feed") return file("alerts_feed.json").catch(() => ({ alerts: [] }));
  if (p === "/quotes") {
    const c = await ctx();
    return { quotes: c.coQuotes.filter((x: any) => c.evById[x.event_id] && new Date(c.evById[x.event_id].start_time).getTime() > Date.now())
      .map((x: any) => ({ ...x, start_time: c.evById[x.event_id].start_time })) };
  }
  if (p === "/stale-lines") {
    const [c, ref] = await Promise.all([ctx(), file("reference_fair.json").catch(() => ({}))]);
    return { lines: staleLines(c.coQuotes, ref, c.evById, c.names, +(q.get("min_edge") || 0.02), STALE_SEC),
      note: "Cuotas de casas colombianas por encima del precio justo de Pinnacle/consenso internacional." };
  }
  if (p === "/surebets") {
    const c = await ctx();
    return { surebets: surebets(c.coQuotes, +(q.get("stake") || 100000)), quotes: c.coQuotes.length };
  }
  if (p === "/odds/operators-compare") {
    const c = await ctx();
    const a = q.get("a")!, b = q.get("b")!;
    const by: Record<string, Record<string, number>> = {};
    c.quotes.forEach((x: any) => { if (x.operator === a || x.operator === b) (by[`${x.event_id}|${x.selection_key}`] ||= {})[x.operator] = x.odds; });
    const common = Object.values(by).filter((v) => v[a] && v[b]);
    const diffs = common.map((v) => v[a] / v[b] - 1);
    return { operator_a: a, operator_b: b, common_selections: common.length, a_better: common.filter((v) => v[a] > v[b]).length,
      b_better: common.filter((v) => v[b] > v[a]).length, equal: common.filter((v) => v[a] === v[b]).length,
      avg_pct_difference_a_vs_b: diffs.length ? (diffs.reduce((s, x) => s + x, 0) / diffs.length) * 100 : null,
      only_in_a: Object.values(by).filter((v) => v[a] && !v[b]).length, only_in_b: Object.values(by).filter((v) => v[b] && !v[a]).length };
  }
  if (p === "/odds/formats") return oddsFormats(+(q.get("odds") || 2));
  if (p === "/operators") return file("operators.json", 3600e3);
  if (p === "/markets") return file("markets.json", 3600e3);
  if (p === "/models") return file("models.json");
  if (p === "/models/performance") return file("performance.json");
  if (p === "/predictions") return file("predictions.json");
  if (p === "/alerts") return file("alerts.json").catch(() => []);
  if (p === "/responsible-gaming") return file("responsible.json", 3600e3);
  if (p === "/football/xt") return file("xt.json", 3600e3);
  if (p === "/football/ratings") return file(`ratings/${q.get("group") || "ENG"}.json`, 3600e3);
  if (p === "/football/team") return teamLookup(await file("teams.json"), q.get("team") || "");
  if (p === "/calculator") return calculator(body || {});
  if (p === "/parlay/search" && method === "POST") return search(body as Req);
  if (p === "/parlay/inverse" && method === "POST") {
    const odds = (body.target_profit_cop + body.stake_cop) / body.stake_cop;
    const out: any = { calculation: { required_odds: odds, implied_probability: 1 / odds } };
    if (body.search !== false) out.search = await search({ target_odds: odds, min_odds: odds, max_odds: odds * 1.12, min_legs: 1, max_legs: body.max_legs || 6, risk: body.risk || "medium", sports: body.sports, operators: body.operators });
    return out;
  }
  if (p === "/parlays") {
    const ps = load<any[]>("parlays", []);
    return { parlays: ps, stats: {} };
  }
  if (p === "/assistant" && method === "POST") return assistant(body.messages);
  if (p === "/auth/me") return { id: 0, email: "este dispositivo", is_admin: false, limits: limitsDict(), gate: gate(), local: true };
  if (p === "/limits" && method === "PUT") {
    const l = limits();
    const delayed: Record<string, number | null> = {};
    for (const k of LIMIT_KEYS) {
      if (!(k in body)) continue;
      const nv = body[k], cur = l[k];
      if (nv != null && (cur == null || nv < cur)) (l as any)[k] = nv; else delayed[k] = nv;
    }
    if (Object.keys(delayed).length) { l.pending_changes = { ...l.pending_changes, ...delayed }; l.pending_effective_at = new Date(Date.now() + 24 * 3600e3).toISOString(); }
    save("limits", l);
    return limitsDict();
  }
  if (p === "/limits/self-exclude" && method === "POST") {
    const l = limits();
    const until = new Date(Date.now() + body.days * 86400e3).toISOString();
    if (!l.self_excluded_until || l.self_excluded_until < until) l.self_excluded_until = until;
    save("limits", l);
    return limitsDict();
  }
  if (p === "/bets") {
    const bets = load<any[]>("bets", []);
    if (method === "POST") {
      bets.unshift({ id: Date.now(), operator: body.operator, description: body.description, stake_cop: body.stake_cop, odds: body.odds, placed_at: new Date().toISOString(), result: null });
      save("bets", bets);
      return { id: bets[0].id, limits: limitsDict(), gate: gate() };
    }
    return bets;
  }
  if (p === "/odds/manual" && method === "POST") {
    const c = await ctx();
    const auth = new Set(c.ops.filter((o) => o.status === "authorized").map((o) => o.key));
    const list = manualAll();
    const errors: any[] = [];
    let n = 0;
    (body as any[]).forEach((r, i) => {
      const op = String(r.operator || "").trim().toLowerCase();
      if (!auth.has(op)) return errors.push({ row: i + 1, error: `Operador '${op}' no está autorizado por Coljuegos en el registro vigente` });
      const odds = +r.odds;
      if (!(odds > 1)) return errors.push({ row: i + 1, error: "La cuota decimal debe ser > 1.00" });
      let ev = r.event_id ? c.evById[r.event_id] : null;
      if (!ev && r.home && r.away) ev = c.events.events.find((e: any) => sim(e.home, r.home) >= 0.75 && sim(e.away, r.away) >= 0.75);
      if (!ev) return errors.push({ row: i + 1, error: "Partido no encontrado en los datos del modelo (solo se valoran partidos con predicción)" });
      list.push({ id: `${Date.now()}-${i}`, event_id: ev.id, operator: op, market: r.market, selection: r.selection,
        line: r.line === "" || r.line == null ? null : +r.line, odds, captured_at: r.captured_at || new Date().toISOString() });
      n++;
    });
    save("manual_quotes", list);
    return { imported: n, errors };
  }
  if (p === "/odds/manual" && method === "GET") return manualAll();
  if (p === "/odds/manual/delete" && method === "POST") {
    save("manual_quotes", manualAll().filter((x) => !body.ids.includes(x.id)));
    return { ok: true };
  }
  throw new HttpError(404, `Función no disponible en la app: ${p}`);
}

export { band, parseKey };
