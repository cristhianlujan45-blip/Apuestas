/**
 * Motor de cálculo en el dispositivo (modo app/estático).
 *
 * Port fiel de backend/app/engine/markets.py y services/parlay/optimizer.py:
 * - valoración exacta de mercados de goles sobre la matriz de marcadores del modelo,
 * - optimizador PARLAY AI (mochila por grupos exacta en log-cuotas),
 * - validación, comparación entre operadores, arbitraje y calculadora COP.
 * Las probabilidades SIEMPRE provienen del modelo exportado por el servidor.
 */

export type Sel = { market: string; selection: string; line: number | null; player: string | null; period: string };
export type Pricing = { p_win: number; p_half_win: number; p_push: number; p_half_lose: number; p_lose: number };

export const MARKET_LABEL: Record<string, string> = {
  "1x2": "Ganador del partido (1X2)", double_chance: "Doble oportunidad", dnb: "Empate no apuesta",
  total_goals: "Total de goles (más/menos)", btts: "Ambos equipos marcan", correct_score: "Resultado exacto",
  asian_handicap: "Hándicap asiático", european_handicap: "Hándicap europeo", team_total_home: "Goles del local",
  team_total_away: "Goles del visitante", moneyline: "Ganador", spread: "Hándicap", total_points: "Total de puntos",
};
export const MATRIX_MARKETS = ["1x2", "double_chance", "dnb", "total_goals", "btts", "correct_score", "asian_handicap",
  "european_handicap", "team_total_home", "team_total_away"];
const SEL_LABEL: Record<string, string> = { home: "Local", away: "Visitante", draw: "Empate", over: "Más de", under: "Menos de", yes: "Sí", no: "No" };

export const selKey = (s: Sel) => `${s.market}|${s.selection}|${s.line == null ? "" : fmtLine(s.line)}|${s.player || ""}|${s.period || "ft"}`;
export const fmtLine = (l: number) => String(+l.toFixed(4));
export function parseKey(k: string): Sel {
  const [market, selection, line, player, period] = k.split("|");
  return { market, selection, line: line ? +line : null, player: player || null, period: period || "ft" };
}
export function describe(s: Sel, home = "Local", away = "Visitante"): string {
  const sel = s.selection === "home" ? home : s.selection === "away" ? away : SEL_LABEL[s.selection] || s.selection;
  let line = "";
  if (s.line != null) line = ["asian_handicap", "spread", "european_handicap"].includes(s.market) ? ` (${s.line > 0 ? "+" : ""}${s.line})` : ` ${s.line}`;
  return `${MARKET_LABEL[s.market] || s.market} — ${s.player ? s.player + " " : ""}${sel}${line}`;
}

// ---------------------------------------------------------------- liquidación
type Grade = [number, number]; // multiplicador = a·o + b
const isQuarter = (l: number) => Math.abs(((l * 4) % 2 + 2) % 2 - 1) < 1e-9;
const lineGrade = (score: number): Grade => [score > 1e-9 ? 1 : 0, Math.abs(score) <= 1e-9 ? 1 : 0];
function split(fn: (l: number) => Grade, line: number): Grade {
  if (isQuarter(line)) {
    const [a1, b1] = fn(line - 0.25), [a2, b2] = fn(line + 0.25);
    return [(a1 + a2) / 2, (b1 + b2) / 2];
  }
  return fn(line);
}

export function gradeCell(s: Sel, h: number, a: number): Grade | null {
  const d = h - a, m = s.market, x = s.selection, L = s.line;
  switch (m) {
    case "1x2": return [x === "home" ? +(d > 0) : x === "away" ? +(d < 0) : +(d === 0), 0];
    case "moneyline": return x === "home" ? [+(d > 0), +(d === 0)] : [+(d < 0), +(d === 0)];
    case "double_chance": return [x === "1X" ? +(d >= 0) : x === "X2" ? +(d <= 0) : +(d !== 0), 0];
    case "dnb": return lineGrade(x === "home" ? d : -d);
    case "total_goals": if (L == null) return null; return split((l) => lineGrade((x === "over" ? 1 : -1) * (h + a - l)), L);
    case "team_total_home": if (L == null) return null; return split((l) => lineGrade((x === "over" ? 1 : -1) * (h - l)), L);
    case "team_total_away": if (L == null) return null; return split((l) => lineGrade((x === "over" ? 1 : -1) * (a - l)), L);
    case "btts": { const both = h > 0 && a > 0; return [x === "yes" ? +both : +!both, 0]; }
    case "correct_score": { const [hs, as] = x.split("-").map(Number); return [+(h === hs && a === as), 0]; }
    case "asian_handicap": case "spread": if (L == null) return null; return split((l) => lineGrade((x === "home" ? d : -d) + l), L);
    case "european_handicap": { if (L == null) return null; const adj = d + L; return [x === "home" ? +(adj > 0) : x === "away" ? +(adj < 0) : +(adj === 0), 0]; }
  }
  return null;
}

export function priceMatrix(matrix: number[][], s: Sel): Pricing | null {
  if (s.period !== "ft" || !MATRIX_MARKETS.includes(s.market)) return null;
  let win = 0, hw = 0, push = 0, hl = 0, tot = 0;
  for (let h = 0; h < matrix.length; h++) for (let a = 0; a < matrix[h].length; a++) {
    const w = matrix[h][a];
    tot += w;
    const g = gradeCell(s, h, a);
    if (!g) return null;
    const [ga, gb] = g;
    if (ga === 1) win += w; else if (ga === 0.5 && gb === 0.5) hw += w; else if (ga === 0 && gb === 1) push += w; else if (ga === 0 && gb === 0.5) hl += w;
  }
  win /= tot; hw /= tot; push /= tot; hl /= tot;
  return { p_win: win, p_half_win: hw, p_push: push, p_half_lose: hl, p_lose: Math.max(0, 1 - win - hw - push - hl) };
}

export const pEff = (p: Pricing) => p.p_win + 0.5 * p.p_half_win;
export const expReturn = (p: Pricing, o: number) => p.p_win * o + p.p_half_win * (o + 1) / 2 + p.p_push + p.p_half_lose * 0.5;
export const evOf = (p: Pricing, o: number) => expReturn(p, o) - 1;
export function fairOdds(p: Pricing) {
  const ea = p.p_win + 0.5 * p.p_half_win, eb = p.p_push + 0.5 * p.p_half_win + 0.5 * p.p_half_lose;
  return ea > 0 ? (1 - eb) / ea : Infinity;
}

/** Probabilidad conjunta de selecciones del MISMO partido (sin asumir independencia). */
export function jointSameEvent(matrix: number[][], legs: { sel: Sel; odds: number }[]) {
  let er = 0, noLoss = 0, all = 0, tot = 0;
  for (let h = 0; h < matrix.length; h++) for (let a = 0; a < matrix[h].length; a++) {
    const w = matrix[h][a];
    tot += w;
    let mult = 1, nl = true, aw = true;
    for (const l of legs) {
      const g = gradeCell(l.sel, h, a);
      if (!g) return null;
      mult *= g[0] * l.odds + g[1];
      nl = nl && g[0] + g[1] > 0;
      aw = aw && g[0] === 1;
    }
    er += w * mult; if (nl) noLoss += w; if (aw) all += w;
  }
  return { expected_return: er / tot, p_no_loss: noLoss / tot, p_all_win: all / tot };
}

// ---------------------------------------------------------------- PARLAY AI
export type Cand = {
  event_id: number; event: string; sport: string; competition: string | null; start_time: string; selection_key: string;
  selection: string; operator: string; odds: number; captured_at: string; probability: number;
  probability_low: number | null; probability_high: number | null; fair_odds: number; ev: number; pricing: Pricing;
  data_sufficient: boolean; is_live: boolean; source: string; components?: Cand[]; same_event_note?: string;
};
export type Mode = "conservative" | "balanced" | "value" | "min_legs";
export type Req = {
  target_odds: number; min_odds?: number | null; max_odds?: number | null; min_legs: number; max_legs: number;
  sports?: string[] | null; operators?: string[] | null; markets?: string[] | null; risk: "low" | "medium" | "high";
  allow_same_event?: boolean; same_day_only?: boolean; max_hours_ahead?: number | null; include_live?: boolean;
};
export const RISK = {
  low: { min_leg_prob: 0.55, min_edge: 0.02, max_negative_ev: 0.12 },
  medium: { min_leg_prob: 0.4, min_edge: 0.02, max_negative_ev: 0.18 },
  high: { min_leg_prob: 0.2, min_edge: 0.01, max_negative_ev: 0.3 },
};
const STEP = 0.005;
const er = (c: Cand) => expReturn(c.pricing, c.odds);

export function band(r: Req): [number, number] {
  const lo = r.min_odds || Math.max(1.01, r.target_odds * 0.9);
  const hi = r.max_odds || r.target_odds * 1.15;
  if (hi < lo) throw new Error("La cuota máxima debe ser mayor que la mínima");
  return [lo, hi];
}

function legValue(c: Cand, mode: Mode) {
  const p = Math.max(c.probability, 1e-9);
  if (mode === "conservative") return Math.log(Math.max(c.probability_low || p, 1e-9));
  if (mode === "balanced") return Math.log(p) + 0.5 * Math.log(Math.max(er(c), 1e-9));
  if (mode === "value") return Math.log(Math.max(er(c), 1e-9));
  return Math.log(p);
}

/** Mochila por grupos exacta (una selección por evento) sobre log-cuotas discretizadas. */
function dp(groups: Cand[][], values: number[][], lo: number, hi: number, kmin: number, kmax: number, mode: Mode, top = 3): Cand[][] {
  const W = Math.floor(Math.log(hi) / STEP) + 1, wlo = Math.ceil(Math.log(lo) / STEP), K = kmax, NEG = -1e18;
  const cols = W + 1;
  const weights = groups.map((g) => g.map((c) => Math.round(Math.log(c.odds) / STEP)));
  let prev = new Float64Array((K + 1) * cols).fill(NEG);
  prev[0] = 0;
  const choices: Int16Array[] = [];
  for (let gi = 0; gi < groups.length; gi++) {
    const next = Float64Array.from(prev);
    const ch = new Int16Array((K + 1) * cols).fill(-1);
    weights[gi].forEach((w, ii) => {
      if (w <= 0 || w > W) return;
      const v = values[gi][ii];
      for (let k = 1; k <= K; k++) for (let x = w; x <= W; x++) {
        const from = prev[(k - 1) * cols + x - w];
        if (from <= NEG / 2) continue;
        const cand = from + v, idx = k * cols + x;
        if (cand > next[idx] + 1e-12) { next[idx] = cand; ch[idx] = ii; }
      }
    });
    choices.push(ch);
    prev = next;
  }
  let finals: [number, number, number][] = [];
  for (let k = kmin; k <= K; k++) for (let x = wlo; x <= W; x++) if (prev[k * cols + x] > NEG / 2) finals.push([k, x, prev[k * cols + x]]);
  if (!finals.length) return [];
  if (mode === "min_legs") { const kb = Math.min(...finals.map((f) => f[0])); finals = finals.filter((f) => f[0] === kb); }
  finals.sort((a, b) => b[2] - a[2]);
  const out: Cand[][] = [], seen = new Set<string>();
  for (const [k, x] of finals) {
    const legs: Cand[] = []; let kk = k, ww = x;
    for (let gi = groups.length - 1; gi >= 0; gi--) {
      const ii = choices[gi][kk * cols + ww];
      if (ii >= 0) { legs.push(groups[gi][ii]); ww -= weights[gi][ii]; kk--; }
    }
    if (kk !== 0 || ww !== 0) continue;
    const key = legs.map((l) => `${l.event_id}${l.selection_key}`).sort().join(";");
    if (seen.has(key)) continue;
    seen.add(key); out.push(legs.reverse());
    if (out.length >= top) break;
  }
  return out;
}

export type Sol = {
  operator: string; mode: Mode; legs: Cand[]; total_odds: number; joint_probability: number; joint_probability_all_win: number;
  independent_probability: number; expected_return: number; ev: number; joint_probability_low: number; joint_probability_high: number;
  fair_total_odds: number | null; n_legs: number;
};

function evaluate(op: string, mode: Mode, legs: Cand[], matrices: Record<string, number[][]>): Sol {
  let total = 1, pnl = 1, pall = 1, indep = 1, ret = 1, plo = 1, phi = 1;
  for (const c of legs) {
    total *= c.odds;
    const m = matrices[String(c.event_id)];
    if (c.components && m) {
      const j = jointSameEvent(m, c.components.map((x) => ({ sel: parseKey(x.selection_key), odds: x.odds })))!;
      pnl *= j.p_no_loss; pall *= j.p_all_win; ret *= j.expected_return;
      c.components.forEach((x) => { indep *= x.probability; });
    } else {
      pnl *= 1 - c.pricing.p_lose; pall *= c.pricing.p_win; ret *= er(c); indep *= c.probability;
    }
    plo *= c.probability_low || c.probability; phi *= c.probability_high || c.probability;
  }
  return { operator: op, mode, legs, total_odds: total, joint_probability: pnl, joint_probability_all_win: pall,
    independent_probability: indep, expected_return: ret, ev: ret - 1, joint_probability_low: plo, joint_probability_high: phi,
    fair_total_odds: pnl > 0 ? 1 / pnl : null, n_legs: legs.reduce((s, c) => s + Math.max(1, c.components?.length || 0), 0) };
}

function composites(items: Cand[], m: number[][]): Cand[] {
  const out: Cand[] = [];
  const pool = [...items].sort((a, b) => b.probability - a.probability).slice(0, 8);
  for (let i = 0; i < pool.length; i++) for (let j = i + 1; j < pool.length; j++) {
    const a = pool[i], b = pool[j], sa = parseKey(a.selection_key), sb = parseKey(b.selection_key);
    if (sa.market === sb.market) continue;
    const jj = jointSameEvent(m, [{ sel: sa, odds: a.odds }, { sel: sb, odds: b.odds }]);
    if (!jj || jj.p_all_win < 1e-4) continue;
    const pricing: Pricing = { p_win: jj.p_all_win, p_half_win: 0, p_push: Math.max(0, jj.p_no_loss - jj.p_all_win), p_half_lose: 0, p_lose: 1 - jj.p_no_loss };
    out.push({ ...a, selection_key: `same_event|${a.selection_key}+${b.selection_key}||||`, selection: `${a.selection} + ${b.selection}`,
      odds: a.odds * b.odds, probability: pEff(pricing), probability_low: null, probability_high: null, pricing,
      fair_odds: fairOdds(pricing), ev: evOf(pricing, a.odds * b.odds), captured_at: a.captured_at < b.captured_at ? a.captured_at : b.captured_at,
      data_sufficient: a.data_sufficient && b.data_sufficient, components: [a, b],
      same_event_note: "Probabilidad conjunta calculada sobre la matriz de marcadores del partido. La cuota mostrada es el producto; el operador puede ajustarla en su creador de apuestas." });
    if (out.length >= 15) return out;
  }
  return out;
}

export type OpInfo = { key: string; name: string; status: string; capabilities: any };

export function optimize(all: Cand[], req: Req, ops: OpInfo[], matrices: Record<string, number[][]>, staleSec = 900, liveStaleSec = 60, now = Date.now()) {
  const [lo, hi] = band(req);
  const prof = RISK[req.risk];
  const authorized = new Set(ops.filter((o) => o.status === "authorized").map((o) => o.key));
  const reasons: Record<string, number> = {};
  const drop = (r: string) => { reasons[r] = (reasons[r] || 0) + 1; };
  const today = new Date(now).toLocaleDateString("es-CO", { timeZone: "America/Bogota" });
  const pool = all.filter((c) => {
    const st = new Date(c.start_time).getTime();
    if (!authorized.has(c.operator)) return drop("operador no autorizado por Coljuegos"), false;
    if (req.operators?.length && !req.operators.includes(c.operator)) return drop("operador excluido por el usuario"), false;
    if (req.sports?.length && !req.sports.includes(c.sport)) return drop("deporte excluido"), false;
    if (req.markets?.length && !req.markets.includes(parseKey(c.selection_key).market)) return drop("mercado excluido"), false;
    if (c.is_live && !req.include_live) return drop("en directo excluido"), false;
    if (!c.is_live && st <= now) return drop("evento ya iniciado"), false;
    if (req.max_hours_ahead && st - now > req.max_hours_ahead * 3600e3) return drop("fuera de la ventana temporal"), false;
    if (req.same_day_only && new Date(st).toLocaleDateString("es-CO", { timeZone: "America/Bogota" }) !== today) return drop("no es del mismo día"), false;
    const age = (now - new Date(c.captured_at).getTime()) / 1000;
    if (age > (c.is_live ? liveStaleSec : staleSec)) return drop("cuota desactualizada"), false;
    if (!c.data_sufficient) return drop("datos insuficientes para el modelo"), false;
    if (c.probability < prof.min_leg_prob) return drop("probabilidad por debajo del perfil de riesgo"), false;
    if (c.odds < 1.03) return drop("cuota demasiado baja"), false;
    return true;
  });
  const byOp: Record<string, Record<string, Cand[]>> = {};
  pool.forEach((c) => { ((byOp[c.operator] ||= {})[c.event_id] ||= []).push(c); });
  const perOp: Record<string, Sol[]> = {};
  const modes: Mode[] = ["conservative", "balanced", "value", "min_legs"];
  for (const [op, events] of Object.entries(byOp)) {
    const info = ops.find((o) => o.key === op);
    const cap = info?.capabilities?.max_parlay_legs;
    const kmax = cap ? Math.min(req.max_legs, cap) : req.max_legs;
    if (Object.keys(events).length < req.min_legs) continue;
    const sols: Sol[] = [];
    for (const mode of modes) {
      const groups: Cand[][] = [], values: number[][] = [];
      for (const [eid, items] of Object.entries(events)) {
        let its = [...items];
        if (req.allow_same_event && info?.capabilities?.same_event_parlays && matrices[eid]) its = its.concat(composites(items, matrices[eid]));
        if (mode === "value") its = its.filter((c) => c.ev >= prof.min_edge);
        if (!its.length) continue;
        its.sort((a, b) => legValue(b, mode) - legValue(a, mode));
        its = its.slice(0, 6);
        groups.push(its); values.push(its.map((c) => legValue(c, mode)));
      }
      if (groups.length < req.min_legs) continue;
      dp(groups, values, lo, hi, req.min_legs, kmax, mode).forEach((legs) => sols.push(evaluate(op, mode, legs, matrices)));
    }
    if (sols.length) perOp[op] = sols;
  }
  const flat = Object.values(perOp).flat();
  const pick = (mode: Mode): Sol | null => {
    let o = flat.filter((s) => s.mode === mode);
    if (mode === "value") o = o.filter((s) => s.ev > 0);
    if (!o.length) return null;
    const score = (s: Sol) => mode === "conservative" ? s.joint_probability_low : mode === "balanced"
      ? Math.log(Math.max(s.joint_probability, 1e-12)) + 0.5 * Math.log(Math.max(s.expected_return, 1e-12)) : mode === "value" ? s.ev : s.joint_probability;
    if (mode === "min_legs") { const km = Math.min(...o.map((s) => s.legs.length)); o = o.filter((s) => s.legs.length === km); }
    return o.reduce((a, b) => (score(b) > score(a) ? b : a));
  };
  const alt: Record<string, Sol | null> = { A: pick("conservative"), B: pick("balanced"), C: pick("value"), D: pick("min_legs") };
  const messages: string[] = [];
  for (const [k, s] of Object.entries(alt)) if (s && s.ev < -prof.max_negative_ev) {
    messages.push(`Parlay ${k}: descartado. Su valor esperado estimado (${(s.ev * 100).toFixed(1)} %) es peor que el límite del perfil de riesgo (${(-prof.max_negative_ev * 100).toFixed(0)} %).`);
    alt[k] = null;
  }
  if (!alt.C) messages.push("No se encontró ninguna combinada con valor esperado positivo y respaldo estadístico dentro de la banda de cuotas solicitada.");
  if (Object.values(alt).every((v) => !v)) messages.push("No existe una combinación suficientemente sólida para la cuota solicitada con los datos disponibles. No se fuerza un resultado.");
  return { alternatives: alt, perOp, considered: { candidates_in: all.length, candidates_used: pool.length, operators: Object.keys(byOp), discarded: reasons, band: [lo, hi] }, messages };
}

export function validate(sol: Sol, events: Record<string, any>, op: OpInfo | undefined, matrices: Record<string, number[][]>, staleSec = 900, now = Date.now()) {
  const checks: { check: string; ok: boolean; detail: string; level: string }[] = [];
  const add = (check: string, ok: boolean, detail: string, level = "error") => checks.push({ check, ok, detail, level: ok ? "ok" : level });
  const legs = sol.legs.flatMap((c) => c.components || [c]);
  const bad = legs.filter((c) => !events[c.event_id] || (!c.is_live && events[c.event_id].status !== "scheduled")).map((c) => c.event);
  add("encuentros_confirmados", !bad.length, bad.length ? `Problemas: ${bad.join(", ")}` : "Todos los encuentros existen y no han comenzado");
  const stale = legs.filter((c) => (now - new Date(c.captured_at).getTime()) / 1000 > staleSec).map((c) => c.selection);
  const ts = legs.map((c) => new Date(c.captured_at).getTime());
  const hm = (t: number) => new Date(t).toLocaleTimeString("es-CO", { timeZone: "America/Bogota", hour: "2-digit", minute: "2-digit" });
  add("cuotas_vigentes", !stale.length, stale.length ? `Cuotas desactualizadas: ${stale.join("; ")}` : `Consultadas entre ${hm(Math.min(...ts))} y ${hm(Math.max(...ts))}`);
  add("mercados_verificados", legs.every((c) => !!c.pricing), "Cada mercado fue valorado por el modelo");
  const keys = legs.map((c) => `${c.event_id}${c.selection_key}`);
  add("sin_duplicados", new Set(keys).size === keys.length, new Set(keys).size === keys.length ? "Sin selecciones duplicadas" : "Hay selecciones duplicadas");
  const byEv: Record<string, Cand[]> = {};
  legs.forEach((c) => (byEv[c.event_id] ||= []).push(c));
  const same = Object.entries(byEv).filter(([, cs]) => cs.length > 1);
  const notes: string[] = [];
  let compatible = true;
  for (const [eid, cs] of same) {
    const m = matrices[eid];
    if (m) {
      const j = jointSameEvent(m, cs.map((c) => ({ sel: parseKey(c.selection_key), odds: c.odds })));
      if (j) {
        if (j.p_all_win < 1e-6) compatible = false;
        notes.push(`${cs[0].event}: prob. conjunta ${(j.p_all_win * 100).toFixed(1)} % vs ${(cs.reduce((p, c) => p * c.probability, 1) * 100).toFixed(1)} % si fueran independientes`);
      }
    }
  }
  add("selecciones_compatibles", compatible, compatible ? "Sin selecciones contradictorias" : "Hay selecciones incompatibles en el mismo partido");
  add("correlaciones", true, notes.length ? notes.join("; ") : "Selecciones de eventos distintos: se tratan como independientes condicionalmente al modelo", "info");
  const caps = op?.capabilities || {};
  const probs: string[] = [];
  if (caps.parlays === false) probs.push("el operador no ofrece combinadas");
  if (same.length && !caps.same_event_parlays) probs.push("combina mercados del mismo encuentro y no está verificado que el operador lo permita");
  if (caps.max_parlay_legs && legs.length > caps.max_parlay_legs) probs.push(`supera el máximo de ${caps.max_parlay_legs} selecciones`);
  if (op?.status !== "authorized") probs.push("operador no autorizado en el registro vigente de Coljuegos");
  add("reglas_operador", !probs.length, probs.length ? probs.join("; ") : "Compatible con las reglas conocidas del operador");
  const prod = sol.legs.reduce((p, c) => p * c.odds, 1);
  add("cuota_calculada", Math.abs(prod - sol.total_odds) < 1e-6, `Cuota total = ${prod.toFixed(2)} (producto de las cuotas)`);
  const ins = legs.filter((c) => !c.data_sufficient).map((c) => c.selection);
  add("datos_suficientes", !ins.length, ins.length ? `Datos insuficientes: ${ins.join(", ")}` : "Modelos con historial suficiente para todos los equipos", "warning");
  return { valid: checks.every((c) => c.ok || c.level === "info" || c.level === "warning"), checks, validated_at: new Date(now).toISOString() };
}

export function comparison(sol: Sol, all: Cand[], names: Record<string, string>) {
  const idx: Record<string, Record<string, Cand>> = {};
  all.forEach((c) => { (idx[`${c.event_id}|${c.selection_key}`] ||= {})[c.operator] = c; });
  const legs = sol.legs.flatMap((c) => c.components || [c]);
  const opsSet = new Set<string>();
  legs.forEach((c) => Object.keys(idx[`${c.event_id}|${c.selection_key}`] || {}).forEach((o) => opsSet.add(o)));
  const operators = [...opsSet].sort();
  const rows = legs.map((c) => {
    const offers = idx[`${c.event_id}|${c.selection_key}`] || {};
    const best = Object.keys(offers).reduce<string | null>((b, o) => (!b || offers[o].odds > offers[b].odds ? o : b), null);
    return { event: c.event, selection: c.selection, selection_key: c.selection_key, probability: c.probability,
      offers: Object.fromEntries(Object.entries(offers).map(([o, x]) => [o, { odds: x.odds, captured_at: x.captured_at, available: true }])),
      best_operator: best, best_odds: best ? offers[best].odds : null, unavailable_at: operators.filter((o) => !offers[o]) };
  });
  const totals: Record<string, any> = {};
  for (const o of operators) {
    const all = legs.every((c) => idx[`${c.event_id}|${c.selection_key}`]?.[o]);
    totals[o] = all ? { total_odds: legs.reduce((p, c) => p * idx[`${c.event_id}|${c.selection_key}`][o].odds, 1), complete: true, name: names[o] || o }
      : { total_odds: null, complete: false, missing: legs.filter((c) => !idx[`${c.event_id}|${c.selection_key}`]?.[o]).map((c) => c.selection), name: names[o] || o };
  }
  const complete = Object.entries(totals).filter(([, v]) => v.complete);
  const bestSingle = complete.length ? complete.reduce((a, b) => (b[1].total_odds > a[1].total_odds ? b : a))[0] : null;
  return { rows, per_operator_totals: totals, best_single_operator: bestSingle,
    note: "Cada total corresponde a la combinada completa en UNA sola casa. No se suman cuotas de operadores distintos: una combinada solo puede colocarse en un operador." };
}

// ---------------------------------------------------------------- arbitraje
const THREE = ["home", "draw", "away"];
const TWO: Record<string, string[]> = { total_goals: ["over", "under"], team_total_home: ["over", "under"], team_total_away: ["over", "under"],
  btts: ["yes", "no"], moneyline: ["home", "away"], dnb: ["home", "away"], total_points: ["over", "under"], total_games: ["over", "under"],
  total_runs: ["over", "under"], corners_total: ["over", "under"], cards_total: ["over", "under"] };
const OPP = ["asian_handicap", "spread", "games_handicap", "set_handicap"];

export function surebets(quotes: any[], stake = 100000, staleSec = 900, now = Date.now()) {
  const books: Record<string, Record<string, any>> = {};
  for (const q of quotes) {
    if ((now - new Date(q.captured_at).getTime()) / 1000 > (q.is_live || q.live ? 60 : staleSec)) continue;
    let key: string | null = null;
    if (q.market === "1x2") key = `${q.event_id}|1x2`;
    else if (TWO[q.market]) key = `${q.event_id}|${q.market}|${q.line ?? ""}|${q.player ?? ""}`;
    else if (OPP.includes(q.market) && q.line != null) key = `${q.event_id}|${q.market}|${q.selection === "home" ? q.line : -q.line}`;
    if (!key) continue;
    const b = (books[key] ||= {});
    if (!b[q.selection] || q.odds > b[q.selection].odds) b[q.selection] = q;
  }
  const out: any[] = [];
  for (const [key, sels] of Object.entries(books)) {
    const market = key.split("|")[1];
    const need = market === "1x2" ? THREE : TWO[market] || ["home", "away"];
    if (!need.every((s) => sels[s])) continue;
    const legs = need.map((s) => sels[s]);
    const inv = legs.reduce((s, l) => s + 1 / l.odds, 0);
    if (inv >= 1) continue;
    out.push({ event_id: legs[0].event_id, event: legs[0].event, market, line: legs[0].line, profit_pct: (1 / inv - 1) * 100, sum_inverse: inv,
      legs: legs.map((l) => { const st = stake * (1 / l.odds) / inv; return { selection: l.selection, selection_label: l.selection_label || l.selection, operator: l.operator, odds: l.odds, stake_cop: Math.round(st), return_cop: Math.round(st * l.odds), captured_at: l.captured_at }; }),
      total_stake_cop: stake, guaranteed_return_cop: Math.round(stake / inv),
      warning: "Verifique cada cuota en la casa antes de apostar: las cuotas cambian, las casas pueden anular cuotas erróneas y limitar cuentas que hacen arbitraje." });
  }
  return out.sort((a, b) => b.profit_pct - a.profit_pct);
}

// ---------------------------------------------------------------- calculadora
export const copFmt = (v: number) => `${v < 0 ? "-" : ""}$${Math.round(Math.abs(v)).toLocaleString("es-CO")}`;
export function calculator(b: { stake_cop?: number | null; odds?: number | null; target_profit_cop?: number | null; capital_cop?: number | null; probability?: number | null }) {
  const out: any = {};
  const { stake_cop: s, odds: o, target_profit_cop: t, capital_cop: cap, probability: p } = b;
  if (s && o) {
    if (s <= 0 || o <= 1) throw new Error("Inversión > 0 y cuota > 1.00");
    out.returns = { stake: s, odds: o, potential_return: s * o, potential_profit: s * o - s };
    if (p != null) out.expected = { expected_profit: s * (p * o - 1), probability_of_loss: 1 - p };
  }
  if (s && t) out.required_odds = { required_odds: (t + s) / s, implied_probability: s / (t + s) };
  if (o && t && o > 1) out.required_stake = { required_stake: t / (o - 1) };
  if (cap && s) {
    const pct = s / cap;
    out.bankroll = { stake_pct_of_capital: pct, warning: pct > 0.05 ? "La inversión supera el 5 % del capital disponible. Una racha de pérdidas es muy probable incluso con estimaciones correctas." : null } as any;
    if (p != null && o && o > 1) {
      const k = Math.max(0, (p * (o - 1) - (1 - p)) / (o - 1));
      out.bankroll.kelly_full_pct = k; out.bankroll.kelly_quarter_stake = (cap * k) / 4;
      if (k === 0) out.bankroll.kelly_note = "Valor esperado ≤ 0 según el modelo: Kelly recomienda no apostar.";
    }
  }
  if (!Object.keys(out).length) throw new Error("Indique inversión y cuota, o inversión y ganancia deseada");
  return out;
}

export function oddsFormats(o: number) {
  const frac = (() => { const x = o - 1; let best = [1, 1], err = 1e9; for (let d = 1; d <= 100; d++) { const n = Math.round(x * d); const e = Math.abs(n / d - x); if (e < err - 1e-12) { err = e; best = [n, d]; } } return `${best[0]}/${best[1]}`; })();
  return { decimal: +o.toFixed(3), americana: o >= 2 ? `+${Math.round((o - 1) * 100)}` : `${Math.round(-100 / (o - 1))}`, fraccional: frac,
    hong_kong: +(o - 1).toFixed(3), indonesia: +(o >= 2 ? o - 1 : -1 / (o - 1)).toFixed(3), malaya: +(o <= 2 ? o - 1 : -1 / (o - 1)).toFixed(3), probabilidad_implicita: +(1 / o).toFixed(4) };
}
