/**
 * Sincronización entre dispositivos con un Gist secreto de GitHub del propio usuario.
 * El usuario crea un token personal con permiso «gist»; se guarda solo en este dispositivo y
 * se envía únicamente a api.github.com. Nunca se guardan contraseñas de casas de apuestas.
 */
export const BACKUP_KEYS = ["manual_quotes", "bets", "parlays", "limits", "alerts_enabled", "alerts_min_ev", "data_url", "server_url", "bankroll"];
const FILE = "apuestas-intel-co.json";
const API = "https://api.github.com/gists";

type SyncCfg = { token: string; gist_id: string | null; last_hash: string | null; last_sync: string | null };
export function syncConfig(): SyncCfg {
  try { return { token: "", gist_id: null, last_hash: null, last_sync: null, ...JSON.parse(localStorage.getItem("sync_cfg") || "{}") }; }
  catch { return { token: "", gist_id: null, last_hash: null, last_sync: null }; }
}
export function setSyncConfig(c: Partial<SyncCfg>) {
  try { localStorage.setItem("sync_cfg", JSON.stringify({ ...syncConfig(), ...c })); } catch { /* */ }
}

export function snapshot(): Record<string, string> {
  const out: Record<string, string> = {};
  for (const k of BACKUP_KEYS) { try { const v = localStorage.getItem(k); if (v != null) out[k] = v; } catch { /* */ } }
  return out;
}
const hash = (s: string) => { let h = 5381; for (let i = 0; i < s.length; i++) h = ((h << 5) + h + s.charCodeAt(i)) | 0; return String(h >>> 0); };

/** Une dos copias: los registros con id (apuestas, cuotas, combinadas) se suman; el resto, gana la más reciente. */
export function merge(local: Record<string, string>, remote: Record<string, string>, remoteNewer: boolean) {
  const out: Record<string, string> = { ...(remoteNewer ? { ...local, ...remote } : { ...remote, ...local }) };
  for (const k of ["bets", "manual_quotes", "parlays"]) {
    try {
      const a: any[] = JSON.parse(local[k] || "[]"), b: any[] = JSON.parse(remote[k] || "[]");
      const by = new Map<string, any>();
      for (const x of [...(remoteNewer ? a : b), ...(remoteNewer ? b : a)]) by.set(String(x.id), x);
      out[k] = JSON.stringify([...by.values()].sort((x, y) => String(y.placed_at || y.created_at || y.captured_at || "").localeCompare(String(x.placed_at || x.created_at || x.captured_at || ""))));
    } catch { /* deja el valor ya elegido */ }
  }
  return out;
}

async function gh(path: string, token: string, init: RequestInit = {}) {
  const r = await fetch(`${API}${path}`, { ...init, headers: { Accept: "application/vnd.github+json", Authorization: `Bearer ${token}`, ...(init.headers || {}) } });
  if (!r.ok) throw new Error(r.status === 401 ? "Token inválido o sin permiso «gist»" : `GitHub respondió ${r.status}`);
  return r.json();
}

/** Descarga, une y sube. Devuelve un mensaje para el usuario. */
export async function syncNow(): Promise<string> {
  const cfg = syncConfig();
  if (!cfg.token) throw new Error("Configure su token de GitHub");
  const local = snapshot();
  let remote: Record<string, string> = {}, remoteAt = "";
  if (cfg.gist_id) {
    const g = await gh(`/${cfg.gist_id}`, cfg.token);
    const f = g.files?.[FILE];
    if (f) {
      const content = f.truncated ? await (await fetch(f.raw_url)).text() : f.content;
      const d = JSON.parse(content || "{}");
      remote = d.data || {}; remoteAt = d.saved_at || "";
    }
  }
  const merged = merge(local, remote, remoteAt > (cfg.last_sync || ""));
  for (const [k, v] of Object.entries(merged)) { try { localStorage.setItem(k, v); } catch { /* */ } }
  const savedAt = new Date().toISOString();
  const body = JSON.stringify({ files: { [FILE]: { content: JSON.stringify({ app: "apuestas-intel-co", saved_at: savedAt, data: merged }) } } });
  const h = hash(JSON.stringify(merged));
  if (cfg.gist_id && h === cfg.last_hash && JSON.stringify(remote) === JSON.stringify(merged)) {
    setSyncConfig({ last_sync: savedAt });
    return "Todo al día.";
  }
  const g = cfg.gist_id
    ? await gh(`/${cfg.gist_id}`, cfg.token, { method: "PATCH", body })
    : await gh("", cfg.token, { method: "POST", body: JSON.stringify({ description: "Apuestas Intel CO · sincronización", public: false, ...JSON.parse(body) }) });
  setSyncConfig({ gist_id: g.id, last_hash: h, last_sync: savedAt });
  const changed = JSON.stringify(local) !== JSON.stringify(merged);
  return changed ? "Sincronizado: se trajeron cambios de otro dispositivo." : "Sincronizado.";
}

/** Sincroniza al abrir la app, cada 10 minutos y al pasar a segundo plano. */
export function startAutoSync(onChange?: () => void): () => void {
  if (!syncConfig().token) return () => {};
  const run = () => { const before = JSON.stringify(snapshot()); syncNow().then(() => { if (JSON.stringify(snapshot()) !== before) onChange?.(); }).catch(() => {}); };
  run();
  const id = setInterval(run, 10 * 60e3);
  const vis = () => { if (document.visibilityState === "hidden") run(); };
  document.addEventListener("visibilitychange", vis);
  return () => { clearInterval(id); document.removeEventListener("visibilitychange", vis); };
}
