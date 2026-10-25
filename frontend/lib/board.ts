/**
 * Tablero de cuotas de un partido: todos los mercados con la probabilidad del modelo, la cuota
 * justa y la mejor cuota disponible (casa colombiana o, si no hay, referencia internacional).
 */
import { fairOdds, jointSameEvent, parseKey, pEff, priceAny, selKey, type CountParams, type Sel } from "./engine";

export type BoardRow = {
  key: string; group: string; label: string; p: number | null; fair: number | null;
  best: { odds: number; operator: string; operator_name: string; captured_at: string } | null;
  ref: { odds: number; operator: string } | null;
};

const S = (market: string, selection: string, line: number | null = null): Sel => ({ market, selection, line, player: null, period: "ft" });
const STANDARD: Sel[] = [
  S("1x2", "home"), S("1x2", "draw"), S("1x2", "away"),
  S("double_chance", "1X"), S("double_chance", "X2"), S("double_chance", "12"),
  S("dnb", "home"), S("dnb", "away"),
  ...[0.5, 1.5, 2.5, 3.5, 4.5].flatMap((l) => [S("total_goals", "over", l), S("total_goals", "under", l)]),
  S("btts", "yes"), S("btts", "no"),
  ...[0.5, 1.5, 2.5].flatMap((l) => [S("team_total_home", "over", l), S("team_total_away", "over", l)]),
  ...[8.5, 9.5, 10.5].flatMap((l) => [S("corners_total", "over", l), S("corners_total", "under", l)]),
  ...[3.5, 4.5].flatMap((l) => [S("cards_total", "over", l), S("cards_total", "under", l)]),
];

export const GROUPS = ["Resultado", "Goles", "Ambos marcan", "Hándicap", "Córners y tarjetas"];
const GROUP: Record<string, string> = {
  "1x2": "Resultado", double_chance: "Resultado", dnb: "Resultado", total_goals: "Goles", team_total_home: "Goles",
  team_total_away: "Goles", btts: "Ambos marcan", asian_handicap: "Hándicap", european_handicap: "Hándicap",
  corners_total: "Córners y tarjetas", corners_home: "Córners y tarjetas", corners_away: "Córners y tarjetas", cards_total: "Córners y tarjetas",
};

/** Nombre corto y claro de la selección («Más de 2.5 goles», «Real o empate»…). */
export function shortLabel(s: Sel, home: string, away: string): string {
  const team = s.selection === "home" ? home : s.selection === "away" ? away : "";
  const L = s.line;
  switch (s.market) {
    case "1x2": return s.selection === "draw" ? "Empate" : `Gana ${team}`;
    case "double_chance": return s.selection === "1X" ? `${home} o empate` : s.selection === "X2" ? `Empate o ${away}` : `${home} o ${away}`;
    case "dnb": return `${team} (si empatan, devuelven)`;
    case "total_goals": return `${s.selection === "over" ? "Más" : "Menos"} de ${L} goles`;
    case "team_total_home": return `${home}: ${s.selection === "over" ? "más" : "menos"} de ${L} goles`;
    case "team_total_away": return `${away}: ${s.selection === "over" ? "más" : "menos"} de ${L} goles`;
    case "btts": return s.selection === "yes" ? "Ambos marcan: sí" : "Ambos marcan: no";
    case "asian_handicap": return `${team} (${L! > 0 ? "+" : ""}${L})`;
    case "european_handicap": return `${s.selection === "draw" ? "Empate" : team} con hándicap ${L! > 0 ? "+" : ""}${L}`;
    case "corners_total": return `${s.selection === "over" ? "Más" : "Menos"} de ${L} córners`;
    case "corners_home": return `${home}: ${s.selection === "over" ? "más" : "menos"} de ${L} córners`;
    case "corners_away": return `${away}: ${s.selection === "over" ? "más" : "menos"} de ${L} córners`;
    case "cards_total": return `${s.selection === "over" ? "Más" : "Menos"} de ${L} tarjetas`;
    case "correct_score": return `Resultado exacto ${s.selection}`;
  }
  return s.selection;
}

export function buildBoard(detail: any, names: Record<string, string> = {}): BoardRow[] {
  const ev = detail.event;
  const matrix: number[][] | undefined = detail.matrix || undefined;
  const counts: CountParams | undefined = detail.model?.counts;
  const rows = new Map<string, BoardRow>();
  const add = (sel: Sel) => {
    const key = selKey(sel);
    if (rows.has(key) || !GROUP[sel.market]) return rows.get(key);
    const pr = priceAny(matrix, counts, sel);
    const row: BoardRow = { key, group: GROUP[sel.market], label: shortLabel(sel, ev.home, ev.away), p: pr ? pEff(pr) : null,
      fair: pr ? fairOdds(pr) : null, best: null, ref: null };
    rows.set(key, row);
    return row;
  };
  if (matrix || counts) STANDARD.forEach(add);
  for (const m of detail.markets || []) {
    const row = add(parseKey(m.selection_key));
    if (!row) continue;
    if (row.p == null && m.model?.p != null) { row.p = m.model.p; row.fair = m.model.fair_odds; }
    const fresh = (m.offers || []).filter((o: any) => !o.stale).sort((a: any, b: any) => b.odds - a.odds)[0];
    if (fresh) row.best = { odds: fresh.odds, operator: fresh.operator, operator_name: fresh.operator_name || names[fresh.operator] || fresh.operator, captured_at: fresh.captured_at };
    const ref = (m.reference || [])[0];
    if (ref) row.ref = { odds: ref.odds, operator: ref.operator };
  }
  return [...rows.values()].filter((r) => r.p == null || (r.p > 0.005 && r.p < 0.995));
}

/** Cuota usable de una fila: la mejor colombiana o, si no hay, la de referencia. */
export const rowOdds = (r: BoardRow) => r.best ? { odds: r.best.odds, operator: r.best.operator, source: "casa" as const }
  : r.ref ? { odds: r.ref.odds, operator: r.ref.operator, source: "referencia" as const } : null;

// Una selección por familia: el resultado (1X2, doble oportunidad, sin empate, hándicaps) y los
// goles (totales del partido y de cada equipo) se contienen o se solapan entre sí.
const family = (key: string) => {
  const m = parseKey(key).market;
  if (["1x2", "dnb", "double_chance", "asian_handicap", "european_handicap"].includes(m)) return "resultado";
  if (["total_goals", "team_total_home", "team_total_away"].includes(m)) return "goles";
  return m;
};

/** Combinadas del mismo partido cerca de la cuota pedida, ordenadas por probabilidad conjunta real. */
export function sameGameCombos(rows: BoardRow[], matrix: number[][] | undefined, target: number, maxLegs = 3) {
  if (!matrix) return [];
  const pool = rows.filter((r) => rowOdds(r) && r.p != null && r.p >= 0.2 && !r.key.startsWith("corners") && !r.key.startsWith("cards"))
    .sort((a, b) => (b.p || 0) - (a.p || 0)).slice(0, 18);
  const lo = target * 0.85, hi = target * 1.25;
  const out: { legs: BoardRow[]; odds: number; p: number; fair: number }[] = [];
  const consider = (legs: BoardRow[]) => {
    const fams = new Set(legs.map((l) => family(l.key)));
    if (fams.size !== legs.length) return;
    const odds = legs.reduce((t, l) => t * rowOdds(l)!.odds, 1);
    if (odds < lo || odds > hi) return;
    const j = jointSameEvent(matrix, legs.map((l) => ({ sel: parseKey(l.key), odds: rowOdds(l)!.odds })));
    if (!j || j.p_all_win < 0.02) return;
    out.push({ legs, odds, p: j.p_all_win, fair: 1 / j.p_all_win });
  };
  for (let i = 0; i < pool.length; i++) for (let k = i + 1; k < pool.length; k++) {
    consider([pool[i], pool[k]]);
    if (maxLegs >= 3) for (let m = k + 1; m < pool.length; m++) consider([pool[i], pool[k], pool[m]]);
  }
  return out.sort((a, b) => b.p - a.p).slice(0, 4);
}
