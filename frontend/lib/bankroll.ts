/**
 * Control de banca: cuánto apostar según la ventaja estimada (Kelly fraccional) sin pasar de un
 * tope por apuesta. La banca vive en este dispositivo; la plataforma no mueve dinero.
 */
export type Bankroll = { initial_cop: number; kelly_fraction: number; max_pct: number };
const KEY = "bankroll";
const DEFAULT: Bankroll = { initial_cop: 0, kelly_fraction: 0.25, max_pct: 0.02 };

export function loadBankroll(): Bankroll {
  try { return { ...DEFAULT, ...JSON.parse(localStorage.getItem(KEY) || "{}") }; } catch { return DEFAULT; }
}
export function saveBankroll(b: Bankroll) {
  try { localStorage.setItem(KEY, JSON.stringify(b)); } catch { /* lleno */ }
}

/** Banca actual = inicial + ganancia neta de las apuestas liquidadas en «Mis apuestas». */
export const currentBankroll = (b: Bankroll, settledProfit: number) => b.initial_cop + settledProfit;

/** Fracción de Kelly para cuota decimal ``odds`` y probabilidad ``p``. */
export const kelly = (p: number, odds: number) => Math.max(0, (p * odds - 1) / (odds - 1));

/** Importe sugerido (COP, redondeado a 1.000) o null si no hay banca o no hay ventaja. */
export function suggestedStake(p: number, odds: number, bankrollCop: number, b: Bankroll = loadBankroll()): number | null {
  if (!(bankrollCop > 0) || !(odds > 1)) return null;
  const f = Math.min(kelly(p, odds) * b.kelly_fraction, b.max_pct);
  if (f <= 0) return null;
  return Math.max(1000, Math.round((bankrollCop * f) / 1000) * 1000);
}

/** Banca actual guardada por «Mis apuestas» (o la inicial si aún no se ha calculado). */
export function bankrollNow(): number {
  const b = loadBankroll();
  if (!b.initial_cop) return 0;
  try {
    const c = JSON.parse(localStorage.getItem("bankroll_current") || "null");
    if (c && typeof c.value === "number") return c.value;
  } catch { /* */ }
  return b.initial_cop;
}
export function storeBankrollNow(settledProfit: number) {
  const b = loadBankroll();
  if (!b.initial_cop) return;
  try { localStorage.setItem("bankroll_current", JSON.stringify({ value: currentBankroll(b, settledProfit), at: new Date().toISOString() })); } catch { /* */ }
}
