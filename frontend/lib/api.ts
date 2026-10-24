export class ApiError extends Error {
  status: number;
  detail: unknown;
  constructor(status: number, detail: unknown) {
    super(typeof detail === "string" ? detail : (detail as { message?: string })?.message || `Error ${status}`);
    this.status = status;
    this.detail = detail;
  }
}

export function getToken(): string | null {
  try {
    return localStorage.getItem("token");
  } catch {
    return null;
  }
}

export function setToken(t: string | null) {
  try {
    if (t) localStorage.setItem("token", t);
    else localStorage.removeItem("token");
  } catch {
    /* sin almacenamiento */
  }
}

/** URL de un servidor en vivo opcional (backend FastAPI desplegado, p. ej. en Render). */
export function serverUrl(): string | null {
  if (process.env.NEXT_PUBLIC_MODE !== "static") return null;
  try {
    return localStorage.getItem("server_url") || null;
  } catch {
    return null;
  }
}
export function setServerUrl(u: string | null) {
  try {
    if (u) localStorage.setItem("server_url", u.replace(/\/+$/, ""));
    else localStorage.removeItem("server_url");
  } catch {
    /* sin almacenamiento */
  }
}

/** Modo app: sin servidor, datos estáticos del pipeline + cálculo en el dispositivo. */
export const isStatic = () => process.env.NEXT_PUBLIC_MODE === "static" && !serverUrl();

export async function api<T = any>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  if (isStatic()) {
    const { route } = await import("./staticApi");
    try {
      return (await route(path, { method: init.method, json: init.json })) as T;
    } catch (e: any) {
      throw new ApiError(e.status || 500, e.detail ?? e.message);
    }
  }
  const headers: Record<string, string> = { ...(init.headers as Record<string, string>) };
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  let body = init.body;
  if (init.json !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(init.json);
  }
  const res = await fetch(`${serverUrl() || ""}/api${path}`, { ...init, headers, body, cache: "no-store" });
  const text = await res.text();
  const data = text ? JSON.parse(text) : null;
  if (!res.ok) throw new ApiError(res.status, data?.detail ?? data);
  return data as T;
}

export function wsUrl(): string {
  const env = process.env.NEXT_PUBLIC_WS_URL;
  if (env) return env;
  const srv = serverUrl();
  if (srv) return srv.replace(/^http/, "ws") + "/ws/live";
  const { protocol, hostname } = window.location;
  return `${protocol === "https:" ? "wss" : "ws"}://${hostname}:8000/ws/live`;
}
