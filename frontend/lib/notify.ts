/**
 * Alertas locales: avisa de surebets y apuestas con valor nuevas.
 * - App Android: notificaciones locales (Capacitor).
 * - Navegador: Notification API (mientras la web está abierta).
 * Para avisos con la app cerrada, el pipeline puede enviar push vía ntfy (NTFY_TOPIC).
 */
import { api } from "./api";

type AlertItem = { id: string; title: string; body: string; event_id: number; kind: string };

export function alertSettings() {
  try {
    return { enabled: localStorage.getItem("alerts_enabled") === "1", min_ev: +(localStorage.getItem("alerts_min_ev") || "0.03") };
  } catch {
    return { enabled: false, min_ev: 0.03 };
  }
}
export function setAlertSettings(enabled: boolean, min_ev: number) {
  try { localStorage.setItem("alerts_enabled", enabled ? "1" : "0"); localStorage.setItem("alerts_min_ev", String(min_ev)); } catch { /* */ }
}

async function native() {
  const { Capacitor } = await import("@capacitor/core");
  return Capacitor.isNativePlatform();
}

export async function requestPermission(): Promise<boolean> {
  if (await native()) {
    const { LocalNotifications } = await import("@capacitor/local-notifications");
    const r = await LocalNotifications.requestPermissions();
    return r.display === "granted";
  }
  if (typeof Notification === "undefined") return false;
  return (await Notification.requestPermission()) === "granted";
}

const hash = (s: string) => { let h = 0; for (const c of s) h = (h * 31 + c.charCodeAt(0)) | 0; return Math.abs(h); };

export async function collectAlerts(minEv: number): Promise<AlertItem[]> {
  const out: AlertItem[] = [];
  try {
    const sb = await api("/surebets");
    for (const s of sb.surebets || []) {
      out.push({ id: `sb|${s.event_id}|${s.market}|${s.line}|${s.legs.map((l: any) => l.operator + l.odds).join(",")}`, kind: "surebet", event_id: s.event_id,
        title: `Surebet ${s.profit_pct.toFixed(2)} % · ${s.event}`, body: s.legs.map((l: any) => `${l.selection_label} ${l.odds} (${l.operator})`).join(" · ") });
    }
  } catch { /* sin datos */ }
  try {
    const sl = await api(`/stale-lines?min_edge=${minEv}`);
    for (const x of (sl.lines || []).slice(0, 10)) {
      out.push({ id: `sl|${x.event_id}|${x.selection_key}|${x.operator}|${x.odds}`, kind: "stale_line", event_id: x.event_id,
        title: `Cuota ${x.status === "retrasada" ? "retrasada" : "sobre el mercado"} ${(x.edge * 100).toFixed(1)} % · ${x.event}`, body: `${x.selection} @ ${x.odds} en ${x.operator_name}: ${x.explanation}` });
    }
  } catch { /* sin datos */ }
  try {
    const v = await api(`/value?min_edge=${minEv}`);
    for (const x of (v.value_bets || []).slice(0, 10)) {
      out.push({ id: `ev|${x.event_id}|${x.selection_key}|${x.operator}|${x.odds}`, kind: "value", event_id: x.event_id,
        title: `Valor ${(x.ev * 100).toFixed(1)} % · ${x.event}`, body: `${x.selection} @ ${x.odds} en ${x.operator}` });
    }
  } catch { /* sin datos */ }
  return out;
}

export async function checkAndNotify(): Promise<number> {
  const st = alertSettings();
  if (!st.enabled) return 0;
  let seen: string[] = [];
  try { seen = JSON.parse(localStorage.getItem("alerts_seen") || "[]"); } catch { /* */ }
  const fresh = (await collectAlerts(st.min_ev)).filter((a) => !seen.includes(a.id)).slice(0, 5);
  if (!fresh.length) return 0;
  if (await native()) {
    const { LocalNotifications } = await import("@capacitor/local-notifications");
    await LocalNotifications.schedule({ notifications: fresh.map((a) => ({ id: hash(a.id) % 2147483647, title: a.title, body: a.body, extra: { event_id: a.event_id } })) });
  } else if (typeof Notification !== "undefined" && Notification.permission === "granted") {
    fresh.forEach((a) => new Notification(a.title, { body: a.body, tag: a.id }));
  }
  try { localStorage.setItem("alerts_seen", JSON.stringify([...fresh.map((a) => a.id), ...seen].slice(0, 500))); } catch { /* */ }
  return fresh.length;
}

/** Inicia la vigilancia periódica mientras la app está abierta y al volver a primer plano. */
export async function startAlertWatcher(onOpenEvent: (id: number) => void): Promise<() => void> {
  const timers: (() => void)[] = [];
  checkAndNotify().catch(() => {});
  const id = setInterval(() => checkAndNotify().catch(() => {}), 10 * 60e3);
  timers.push(() => clearInterval(id));
  if (await native()) {
    const { App } = await import("@capacitor/app");
    const { LocalNotifications } = await import("@capacitor/local-notifications");
    const h1 = await App.addListener("resume", () => { checkAndNotify().catch(() => {}); });
    const h2 = await LocalNotifications.addListener("localNotificationActionPerformed", (a) => {
      const ev = a.notification.extra?.event_id;
      if (ev) onOpenEvent(ev);
    });
    timers.push(() => h1.remove(), () => h2.remove());
  }
  return () => timers.forEach((t) => t());
}
