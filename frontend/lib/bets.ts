/**
 * Mis apuestas: registro local de lo que el usuario apostó por su cuenta, con
 * liquidación automática y CLV (closing line value) frente a la cuota de cierre
 * justa de Pinnacle. El CLV es el mejor indicador temprano de ventaja real.
 */
import { gradeCell, parseKey } from "./engine";

export type BetLeg = { event_id: number; event: string; selection_key: string; selection: string; odds: number; start_time?: string };
export type Bet = {
  id: string; placed_at: string; operator: string; stake_cop: number; odds: number; legs: BetLeg[]; description: string;
  manual_result?: "won" | "lost" | "void" | null;
};

const KEY = "bets";
export function loadBets(): Bet[] {
  try {
    return (JSON.parse(localStorage.getItem(KEY) || "[]") as any[]).map((b) => ({ legs: [], description: "", ...b, id: String(b.id) }));
  } catch {
    return [];
  }
}
function saveAll(b: Bet[]) {
  try { localStorage.setItem(KEY, JSON.stringify(b)); } catch { /* lleno */ }
}
export function addBet(b: Omit<Bet, "id" | "placed_at"> & { placed_at?: string }) {
  const all = loadBets();
  const bet: Bet = { ...b, id: `${Date.now()}`, placed_at: b.placed_at || new Date().toISOString() };
  all.unshift(bet);
  saveAll(all);
  return bet;
}
export function deleteBet(id: string) { saveAll(loadBets().filter((b) => b.id !== id)); }
export function setManualResult(id: string, r: Bet["manual_result"]) {
  saveAll(loadBets().map((b) => (b.id === id ? { ...b, manual_result: r } : b)));
}

export type Result = { event_id: number; home_score: number | null; away_score: number | null; closing: any };

function closingFair(leg: BetLeg, r: Result | undefined): number | null {
  const c = r?.closing;
  if (!c) return null;
  const s = parseKey(leg.selection_key);
  if (s.market === "1x2" && c.fair_1x2) return c.fair_1x2[s.selection] ?? null;
  if (s.market === "total_goals" && s.line === 2.5 && c.fair_total_2_5) return c.fair_total_2_5[s.selection] ?? null;
  if (s.market === "double_chance" && c.fair_1x2) {
    const f = c.fair_1x2;
    return s.selection === "1X" ? f.home + f.draw : s.selection === "X2" ? f.draw + f.away : f.home + f.away;
  }
  return null;
}

export function evaluate(bet: Bet, results: Record<number, Result>) {
  let mult = 1, pending = false, unknown = false, lost = false;
  let clvProd = 1, clvOk = bet.legs.length > 0;
  const legs = bet.legs.map((l) => {
    const r = results[l.event_id];
    const pf = closingFair(l, r);
    if (pf == null) clvOk = false; else clvProd *= l.odds * pf;
    if (!r || r.home_score == null) { pending = true; return { ...l, status: "pendiente", clv: pf != null ? l.odds * pf - 1 : null }; }
    const g = gradeCell(parseKey(l.selection_key), r.home_score, r.away_score!);
    if (!g) { unknown = true; return { ...l, status: "liquidar a mano", clv: pf != null ? l.odds * pf - 1 : null, score: `${r.home_score}-${r.away_score}` }; }
    const m = g[0] * l.odds + g[1];
    mult *= m;
    if (m === 0) lost = true;
    const status = g[0] === 1 ? "ganada" : m === 0 ? "perdida" : g[1] === 1 ? "nula" : g[0] > 0 ? "media ganada" : "media perdida";
    return { ...l, status, clv: pf != null ? l.odds * pf - 1 : null, score: `${r.home_score}-${r.away_score}` };
  });
  let status: string, payout: number | null;
  if (bet.manual_result) {
    status = { won: "ganada", lost: "perdida", void: "nula" }[bet.manual_result];
    payout = bet.manual_result === "won" ? bet.stake_cop * bet.odds : bet.manual_result === "void" ? bet.stake_cop : 0;
  } else if (lost) { status = "perdida"; payout = 0; }
  else if (pending) { status = "pendiente"; payout = null; }
  else if (unknown || !bet.legs.length) { status = "liquidar a mano"; payout = null; }
  else if (legs.every((l) => l.status === "ganada")) { status = "ganada"; payout = bet.stake_cop * bet.odds; }
  else { status = mult === 1 ? "nula" : "parcial"; payout = bet.stake_cop * mult; }
  return { ...bet, legs, status, payout, profit: payout == null ? null : payout - bet.stake_cop, clv: clvOk ? clvProd - 1 : null };
}

export function summary(evals: ReturnType<typeof evaluate>[]) {
  const settled = evals.filter((e) => e.payout != null);
  const staked = settled.reduce((s, e) => s + e.stake_cop, 0);
  const profit = settled.reduce((s, e) => s + (e.profit || 0), 0);
  const clvs = evals.map((e) => e.clv).filter((x): x is number => x != null);
  return {
    total: evals.length, settled: settled.length, staked, profit, roi: staked ? profit / staked : null,
    avg_clv: clvs.length ? clvs.reduce((s, x) => s + x, 0) / clvs.length : null,
    beat_close: clvs.length ? clvs.filter((x) => x > 0).length / clvs.length : null, clv_n: clvs.length,
  };
}
