/**
 * «Mi boleto»: selecciones que el usuario elige a mano, de uno o varios partidos.
 * Se guardan en el dispositivo. La probabilidad conjunta se calcula sobre la matriz de marcadores
 * de cada partido, así que las selecciones del mismo partido no se tratan como independientes.
 */
import { api } from "./api";
import { COUNT_MARKETS, jointSameEvent, parseKey, priceCounts, priceMatrix, type CountParams } from "./engine";

export type SlipLeg = {
  event_id: number; event: string; start_time: string; home: string; away: string;
  selection_key: string; label: string; odds: number | null; operator: string | null;
  source: "casa" | "referencia" | "manual"; p: number | null;
};

const KEY = "slip";
export function loadSlip(): SlipLeg[] {
  try { return JSON.parse(localStorage.getItem(KEY) || "[]"); } catch { return []; }
}
function save(legs: SlipLeg[]) {
  try { localStorage.setItem(KEY, JSON.stringify(legs)); } catch { /* lleno */ }
  window.dispatchEvent(new Event("slip"));
}
export const inSlip = (eventId: number, key: string) => loadSlip().some((l) => l.event_id === eventId && l.selection_key === key);
export function toggleLeg(leg: SlipLeg) {
  const all = loadSlip();
  const i = all.findIndex((l) => l.event_id === leg.event_id && l.selection_key === leg.selection_key);
  if (i >= 0) all.splice(i, 1); else all.push(leg);
  save(all);
}
export function addLegs(legs: SlipLeg[]) {
  const all = loadSlip().filter((l) => !legs.some((n) => n.event_id === l.event_id && n.selection_key === l.selection_key));
  save([...all, ...legs]);
}
export function removeLeg(eventId: number, key: string) { save(loadSlip().filter((l) => !(l.event_id === eventId && l.selection_key === key))); }
export function setLegOdds(eventId: number, key: string, odds: number | null) {
  save(loadSlip().map((l) => (l.event_id === eventId && l.selection_key === key ? { ...l, odds, operator: null, source: "manual" } : l)));
}
export function clearSlip() { save([]); }

type Detail = { matrix?: number[][] | null; model?: { counts?: CountParams }; markets?: any[] };
const cache: Record<number, Promise<Detail>> = {};
export const eventDetail = (id: number) => (cache[id] ||= api<Detail>(`/events/${id}`).catch(() => ({})));

export type SlipEval = {
  n: number; total_odds: number | null; p_win: number | null; p_no_loss: number | null; expected_return: number | null;
  ev: number | null; warnings: string[]; same_event: boolean;
  houses: { operator: string; name: string; total_odds: number }[];
};

/** Valora el boleto: probabilidad de acertar todas, ganancia esperada y comparación entre casas. */
export async function evaluateSlip(legs: SlipLeg[], names: Record<string, string> = {}): Promise<SlipEval> {
  const warnings: string[] = [];
  const byEvent: Record<number, SlipLeg[]> = {};
  legs.forEach((l) => (byEvent[l.event_id] ||= []).push(l));
  let pWin = 1, pNoLoss = 1, er = 1, known = true, erKnown = true;
  const details: Record<number, Detail> = {};
  for (const [eid, ls] of Object.entries(byEvent)) {
    const d = await eventDetail(+eid);
    details[+eid] = d;
    const matrixLegs = ls.filter((l) => !COUNT_MARKETS[parseKey(l.selection_key).market]);
    const countLegs = ls.filter((l) => COUNT_MARKETS[parseKey(l.selection_key).market]);
    if (matrixLegs.length) {
      if (!d.matrix) { known = false; erKnown = false; }
      else {
        const j = jointSameEvent(d.matrix, matrixLegs.map((l) => ({ sel: parseKey(l.selection_key), odds: l.odds || 1 })));
        if (!j) { known = false; erKnown = false; }
        else {
          if (matrixLegs.length > 1 && j.p_all_win < 1e-6) warnings.push(`${ls[0].event}: estas selecciones no pueden ganar a la vez.`);
          pWin *= j.p_all_win; pNoLoss *= j.p_no_loss;
          if (matrixLegs.some((l) => !l.odds)) erKnown = false; else er *= j.expected_return;
        }
      }
    }
    for (const l of countLegs) {
      const pr = priceCounts(d.model?.counts, parseKey(l.selection_key));
      if (!pr) { known = false; erKnown = false; continue; }
      pWin *= pr.p_win; pNoLoss *= 1 - pr.p_lose;
      if (!l.odds) erKnown = false; else er *= pr.p_win * l.odds + pr.p_half_win * (l.odds + 1) / 2 + pr.p_push + pr.p_half_lose * 0.5;
    }
    if (ls.length > 1) {
      if (countLegs.length && matrixLegs.length) warnings.push(`${ls[0].event}: córners/tarjetas se combinan con los goles como si fueran independientes (aproximación).`);
      warnings.push(`${ls[0].event}: varias selecciones del mismo partido. Solo algunas casas lo permiten (creador de apuestas) y pueden pagar menos que el producto de las cuotas.`);
    }
  }
  const missing = legs.filter((l) => !l.odds);
  if (missing.length) warnings.push(`Falta la cuota de ${missing.length} selección(es): escríbala tal como la ve en su casa.`);
  if (legs.some((l) => l.source === "referencia")) warnings.push("Algunas cuotas son de referencia internacional: confírmelas en su casa.");
  const total = missing.length ? null : legs.reduce((t, l) => t * (l.odds || 1), 1);
  // Casas que ofrecen todas las selecciones
  const ops = new Set<string>();
  Object.values(details).forEach((d) => (d.markets || []).forEach((r: any) => r.offers?.forEach((o: any) => ops.add(o.operator))));
  const houses: SlipEval["houses"] = [];
  for (const op of ops) {
    let t = 1, ok = true;
    for (const l of legs) {
      const row = (details[l.event_id].markets || []).find((r: any) => r.selection_key === l.selection_key);
      const o = row?.offers?.find((x: any) => x.operator === op && !x.stale);
      if (!o) { ok = false; break; }
      t *= o.odds;
    }
    if (ok) houses.push({ operator: op, name: names[op] || op, total_odds: t });
  }
  houses.sort((a, b) => b.total_odds - a.total_odds);
  return {
    n: legs.length, total_odds: total, p_win: known && legs.length ? pWin : null, p_no_loss: known && legs.length ? pNoLoss : null,
    expected_return: erKnown && total ? er : null, ev: erKnown && total ? er - 1 : null, warnings, houses,
    same_event: Object.values(byEvent).some((ls) => ls.length > 1),
  };
}

/** Probabilidad de una selección sobre la matriz o los conteos del partido. */
export function legProbability(d: Detail, key: string): number | null {
  const sel = parseKey(key);
  const pr = (d.matrix ? priceMatrix(d.matrix, sel) : null) || priceCounts(d.model?.counts, sel);
  return pr ? pr.p_win + 0.5 * pr.p_half_win : null;
}
