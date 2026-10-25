"use client";
import { useEffect, useState } from "react";
import { Card, ErrorBox, PageHeader, StatusBadge } from "@/components/ui";
import { api, getToken, isStatic, serverUrl, setServerUrl, setToken } from "@/lib/api";
import { COUNT_MARKETS, MARKET_LABEL, MATRIX_MARKETS } from "@/lib/engine";
import { loadBankroll, saveBankroll } from "@/lib/bankroll";
import { BACKUP_KEYS, setSyncConfig, syncConfig, syncNow } from "@/lib/sync";
import { bogota, cop } from "@/lib/format";
import { useApi } from "@/lib/useApi";

function Account({ me, reload }: { me: any; reload: () => void }) {
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [pw, setPw] = useState("");
  const [birth, setBirth] = useState("");
  const [terms, setTerms] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  if (me) return (
    <Card title="Cuenta">
      <p className="text-sm">{me.email} {me.is_admin && <StatusBadge status="info">administrador</StatusBadge>}</p>
      <button className="btn-ghost mt-3" onClick={() => { setToken(null); reload(); }}>Cerrar sesión</button>
    </Card>
  );
  const submit = async () => {
    try {
      const r = mode === "login" ? await api("/auth/login", { method: "POST", json: { email, password: pw } })
        : await api("/auth/register", { method: "POST", json: { email, password: pw, birthdate: birth, accept_terms: terms } });
      setToken(r.token); setErr(null); reload();
    } catch (e) { setErr(e); }
  };
  return (
    <Card title="Cuenta" right={<div className="flex gap-1"><button className={`tab ${mode === "login" ? "tab-active" : ""}`} onClick={() => setMode("login")}>Ingresar</button><button className={`tab ${mode === "register" ? "tab-active" : ""}`} onClick={() => setMode("register")}>Registrarse</button></div>}>
      <label className="label">Correo</label><input className="input" value={email} onChange={(e) => setEmail(e.target.value)} />
      <label className="label mt-2">Contraseña</label><input type="password" className="input" value={pw} onChange={(e) => setPw(e.target.value)} />
      {mode === "register" && (<>
        <label className="label mt-2">Fecha de nacimiento (debe ser mayor de 18 años)</label><input type="date" className="input" value={birth} onChange={(e) => setBirth(e.target.value)} />
        <label className="mt-2 flex items-center gap-2 text-xs text-ink-2"><input type="checkbox" checked={terms} onChange={(e) => setTerms(e.target.checked)} /> Acepto que es una herramienta de análisis sin garantía de ganancias y el aviso de juego responsable.</label>
      </>)}
      <button className="btn-primary mt-3" onClick={submit}>{mode === "login" ? "Ingresar" : "Crear cuenta"}</button>
      <p className="mt-2 text-[11px] text-ink-muted">El primer usuario registrado es administrador. Nunca se piden ni guardan credenciales de casas de apuestas.</p>
      <ErrorBox error={err} />
    </Card>
  );
}

function Limits({ me, reload }: { me: any; reload: () => void }) {
  const l = me.limits;
  const [f, setF] = useState({ daily_stake_cop: l.daily_stake_cop ?? "", weekly_stake_cop: l.weekly_stake_cop ?? "", monthly_stake_cop: l.monthly_stake_cop ?? "", session_minutes: l.session_minutes ?? "" });
  const [days, setDays] = useState(30);
  const [bet, setBet] = useState({ operator: "betplay", description: "", stake_cop: 10000, odds: 2 });
  const [err, setErr] = useState<unknown>(null);
  const save = async () => {
    const body: any = {};
    for (const [k, v] of Object.entries(f)) body[k] = v === "" ? null : Number(v);
    try { await api("/limits", { method: "PUT", json: body }); reload(); } catch (e) { setErr(e); }
  };
  return (
    <Card title="Límites personales y autoexclusión">
      {me.gate && <div className="mb-3"><StatusBadge status="warning">{me.gate.message}</StatusBadge></div>}
      <div className="grid grid-cols-2 gap-3">
        {([["daily_stake_cop", "Límite diario (COP)"], ["weekly_stake_cop", "Límite semanal (COP)"], ["monthly_stake_cop", "Límite mensual (COP)"], ["session_minutes", "Tiempo de sesión (min)"]] as const).map(([k, label]) => (
          <div key={k}><label className="label">{label}</label><input type="number" className="input" value={(f as any)[k]} onChange={(e) => setF({ ...f, [k]: e.target.value })} /></div>
        ))}
      </div>
      <button className="btn-primary mt-3" onClick={save}>Guardar límites</button>
      {Object.keys(l.pending_changes || {}).length > 0 && <p className="mt-2 text-xs text-warning">Cambios pendientes (aumentos) efectivos el {bogota(l.pending_effective_at)}: {JSON.stringify(l.pending_changes)}</p>}
      <p className="mt-2 text-xs text-ink-muted num">Gasto registrado: hoy {cop(l.usage_cop.day)} · 7 días {cop(l.usage_cop.week)} · 30 días {cop(l.usage_cop.month)}</p>
      <div className="mt-4 border-t border-line pt-3">
        <label className="label">Registrar una apuesta que usted colocó (para controlar sus límites)</label>
        <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
          <input className="input" placeholder="Operador" value={bet.operator} onChange={(e) => setBet({ ...bet, operator: e.target.value })} />
          <input className="input" placeholder="Descripción" value={bet.description} onChange={(e) => setBet({ ...bet, description: e.target.value })} />
          <input type="number" className="input" placeholder="COP" value={bet.stake_cop} onChange={(e) => setBet({ ...bet, stake_cop: +e.target.value })} />
          <input type="number" step="0.01" className="input" placeholder="Cuota" value={bet.odds} onChange={(e) => setBet({ ...bet, odds: +e.target.value })} />
        </div>
        <button className="btn-ghost mt-2" onClick={async () => { try { await api("/bets", { method: "POST", json: bet }); reload(); } catch (e) { setErr(e); } }}>Registrar</button>
      </div>
      <div className="mt-4 border-t border-line pt-3">
        <label className="label">Autoexclusión (no se puede acortar)</label>
        <div className="flex gap-2"><input type="number" className="input w-28" value={days} onChange={(e) => setDays(+e.target.value)} /><span className="self-center text-sm text-ink-2">días</span>
          <button className="btn-ghost border-critical/50 text-critical" onClick={async () => { if (confirm(`¿Autoexcluirse ${days} días? No podrá revertirlo.`)) { await api("/limits/self-exclude", { method: "POST", json: { days } }); reload(); } }}>Autoexcluirme</button></div>
        {l.self_excluded_until && <p className="mt-2 text-xs text-warning">Autoexcluido hasta {bogota(l.self_excluded_until)}</p>}
      </div>
      <ErrorBox error={err} />
    </Card>
  );
}

function ManualOdds() {
  const [row, setRow] = useState({ sport: "football", competition: "", start_time: "", home: "", away: "", operator: "betplay", market: "1x2", selection: "home", line: "", odds: "" });
  const [res, setRes] = useState<any>(null);
  const [err, setErr] = useState<unknown>(null);
  const submit = async () => {
    try { setRes(await api("/odds/manual", { method: "POST", json: [{ ...row, line: row.line === "" ? null : +row.line, odds: +row.odds }] })); setErr(null); } catch (e) { setErr(e); }
  };
  const upload = async (file: File) => {
    const fd = new FormData(); fd.append("file", file);
    try {
      const r = await fetch("/api/odds/import", { method: "POST", body: fd, headers: getToken() ? { Authorization: `Bearer ${getToken()}` } : {} });
      setRes(await r.json());
    } catch (e) { setErr(e); }
  };
  return (
    <Card title="Cargar cuotas manualmente (cuando no hay integración autorizada)">
      <div className="grid grid-cols-2 gap-2 md:grid-cols-5">
        {Object.entries(row).map(([k, v]) => (
          <div key={k}><label className="label">{k}</label><input className="input" value={v} placeholder={k === "start_time" ? "2026-10-25T15:00 (hora COL)" : ""} onChange={(e) => setRow({ ...row, [k]: e.target.value })} /></div>
        ))}
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-3">
        <button className="btn-primary" onClick={submit}>Guardar cuota</button>
        <label className="btn-ghost cursor-pointer">Importar CSV<input type="file" accept=".csv" className="hidden" onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} /></label>
        <a className="text-xs text-accent" href="data:text/csv;charset=utf-8,sport,competition,start_time,home,away,operator,market,selection,line,player,odds,captured_at%0A" download="plantilla_cuotas.csv">Descargar plantilla</a>
      </div>
      <p className="mt-2 text-xs text-ink-muted">Las cuotas cargadas quedan marcadas como «manual» con su hora de consulta. Solo se aceptan operadores autorizados. Requiere sesión iniciada.</p>
      {res && <pre className="mt-2 overflow-x-auto rounded bg-page p-2 text-xs">{JSON.stringify(res, null, 1)}</pre>}
      <ErrorBox error={err} />
    </Card>
  );
}

function Admin() {
  const [msg, setMsg] = useState<string | null>(null);
  const run = async (path: string) => { try { const r = await api(path, { method: "POST" }); setMsg(JSON.stringify(r)); } catch (e: any) { setMsg(e.message); } };
  return (
    <Card title="Administración (requiere administrador)">
      <div className="flex flex-wrap gap-2">
        <button className="btn-ghost" onClick={() => run("/ingest/fixtures")}>Ingerir próximos partidos</button>
        <button className="btn-ghost" onClick={() => run("/ingest/odds")}>Ingerir cuotas colombianas</button>
        <button className="btn-ghost" onClick={() => run("/ingest/api_football")}>Ingerir API-Football</button>
        <button className="btn-ghost" onClick={() => run("/ingest/results")}>Actualizar resultados</button>
        <button className="btn-ghost" onClick={() => run("/predictions/run")}>Registrar predicciones</button>
        <button className="btn-ghost" onClick={() => run("/settle")}>Liquidar combinadas</button>
        <button className="btn-ghost" onClick={() => run("/operators/verify")}>Verificar Coljuegos</button>
        <button className="btn-ghost" onClick={() => run("/models/train?kind=football")}>Reentrenar fútbol</button>
        <button className="btn-ghost" onClick={() => run("/models/train?kind=other")}>Entrenar otros deportes</button>
      </div>
      {msg && <pre className="mt-2 overflow-x-auto rounded bg-page p-2 text-xs">{msg}</pre>}
    </Card>
  );
}

const SELECTIONS: Record<string, string[]> = {
  "1x2": ["home", "draw", "away"], double_chance: ["1X", "X2", "12"], dnb: ["home", "away"], total_goals: ["over", "under"],
  btts: ["yes", "no"], correct_score: ["1-0", "2-0", "2-1", "0-0", "1-1", "2-2", "0-1", "0-2", "1-2"], asian_handicap: ["home", "away"],
  european_handicap: ["home", "draw", "away"], team_total_home: ["over", "under"], team_total_away: ["over", "under"],
  corners_total: ["over", "under"], corners_home: ["over", "under"], corners_away: ["over", "under"], cards_total: ["over", "under"],
  shots_on_target_total: ["over", "under"],
};
const SEL_ES: Record<string, string> = { home: "Local", away: "Visitante", draw: "Empate", over: "Más de", under: "Menos de", yes: "Sí", no: "No" };
const NEEDS_LINE = ["total_goals", "asian_handicap", "european_handicap", "team_total_home", "team_total_away", "corners_total",
  "corners_home", "corners_away", "cards_total", "shots_on_target_total"];

function parseCsv(text: string): Record<string, string>[] {
  const lines = text.replace(/\r/g, "").split("\n").filter((l) => l.trim());
  const head = lines[0].split(",").map((h) => h.trim());
  return lines.slice(1).map((l) => Object.fromEntries(l.split(",").map((v, i) => [head[i], v.trim()])));
}

function DeviceOdds() {
  const events = useApi("/events?scope=upcoming&limit=400");
  const ops = useApi("/operators");
  const saved = useApi("/odds/manual");
  const [f, setF] = useState({ event_id: "", operator: "betplay", market: "1x2", selection: "home", line: "", odds: "" });
  const [msg, setMsg] = useState<any>(null);
  const evs = (events.data?.events || []).filter((e: any) => e.has_matrix);
  const submit = async (rows: any[]) => { const r = await api("/odds/manual", { method: "POST", json: rows }); setMsg(r); saved.reload(); };
  const del = async (id: string) => { await api("/odds/manual/delete", { method: "POST", json: { ids: [id] } }); saved.reload(); };
  const evLabel = (id: number) => evs.find((e: any) => e.id === id)?.label || (events.data?.events || []).find((e: any) => e.id === id)?.label || id;
  return (
    <Card title="Mis cuotas (copie aquí las cuotas que ve en su casa de apuestas)">
      <p className="mb-3 text-xs text-ink-muted">La app valora cada cuota con el modelo del partido: probabilidad, cuota justa, valor esperado, surebets y combinadas. Se guardan solo en este teléfono.</p>
      <div className="grid grid-cols-2 gap-2 md:grid-cols-6">
        <div className="col-span-2"><label className="label">Partido</label>
          <select className="input" value={f.event_id} onChange={(e) => setF({ ...f, event_id: e.target.value })}>
            <option value="">Seleccione…</option>{evs.map((e: any) => <option key={e.id} value={e.id}>{bogota(e.start_time)} · {e.label}</option>)}
          </select></div>
        <div><label className="label">Casa</label><select className="input" value={f.operator} onChange={(e) => setF({ ...f, operator: e.target.value })}>
          {(ops.data?.operators || []).filter((o: any) => o.status === "authorized").map((o: any) => <option key={o.key} value={o.key}>{o.name}</option>)}</select></div>
        <div><label className="label">Mercado</label><select className="input" value={f.market} onChange={(e) => setF({ ...f, market: e.target.value, selection: SELECTIONS[e.target.value][0] })}>
          {[...MATRIX_MARKETS, ...Object.keys(COUNT_MARKETS).filter((m) => m !== "shots_total")].map((m) => <option key={m} value={m}>{MARKET_LABEL[m]}</option>)}</select></div>
        <div><label className="label">Selección</label><select className="input" value={f.selection} onChange={(e) => setF({ ...f, selection: e.target.value })}>
          {SELECTIONS[f.market].map((x) => <option key={x} value={x}>{SEL_ES[x] || x}</option>)}</select></div>
        {NEEDS_LINE.includes(f.market) && <div><label className="label">Línea</label><input className="input" inputMode="decimal" placeholder="2.5" value={f.line} onChange={(e) => setF({ ...f, line: e.target.value })} /></div>}
        <div><label className="label">Cuota</label><input className="input" inputMode="decimal" placeholder="1.85" value={f.odds} onChange={(e) => setF({ ...f, odds: e.target.value })} /></div>
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-3">
        <button className="btn-primary" disabled={!f.event_id || !f.odds} onClick={() => submit([{ ...f, event_id: +f.event_id, odds: +f.odds.replace(",", "."), line: f.line === "" ? null : +f.line.replace(",", ".") }])}>Guardar cuota</button>
        <label className="btn-ghost cursor-pointer">Importar CSV<input type="file" accept=".csv" className="hidden" onChange={async (e) => { const fl = e.target.files?.[0]; if (fl) submit(parseCsv(await fl.text())); }} /></label>
        <span className="text-[11px] text-ink-muted">CSV: home,away,operator,market,selection,line,odds</span>
      </div>
      {msg && <p className="mt-2 text-xs text-ink-2">Guardadas: {msg.imported}{msg.errors?.length ? ` · errores: ${msg.errors.map((x: any) => `fila ${x.row}: ${x.error}`).join("; ")}` : ""}</p>}
      {saved.data?.length > 0 && (
        <table className="data mt-3"><thead><tr><th>Partido</th><th>Casa</th><th>Mercado</th><th>Selección</th><th>Cuota</th><th>Hora</th><th /></tr></thead>
          <tbody>{saved.data.slice().reverse().map((m: any) => (
            <tr key={m.id}><td>{evLabel(m.event_id)}</td><td>{m.operator}</td><td>{MARKET_LABEL[m.market] || m.market}</td><td>{SEL_ES[m.selection] || m.selection}{m.line != null ? ` ${m.line}` : ""}</td>
              <td className="num">{m.odds}</td><td className="num text-ink-muted">{bogota(m.captured_at, false)}</td><td><button className="text-xs text-critical" onClick={() => del(m.id)}>Borrar</button></td></tr>
          ))}</tbody></table>
      )}
      <p className="mt-2 text-[11px] text-ink-muted">Las cuotas con más de 15 minutos se marcan como desactualizadas y no entran en combinadas ni surebets. Vuelva a copiarlas antes de decidir.</p>
    </Card>
  );
}



function Backup() {
  const [txt, setTxt] = useState("");
  const [msg, setMsg] = useState("");
  const exportNow = () => {
    const data: Record<string, unknown> = { app: "apuestas-intel-co", version: 1, exported_at: new Date().toISOString() };
    for (const k of BACKUP_KEYS) { try { const v = localStorage.getItem(k); if (v != null) data[k] = v; } catch { /* */ } }
    const json = JSON.stringify(data);
    setTxt(json);
    try {
      const a = document.createElement("a");
      a.href = URL.createObjectURL(new Blob([json], { type: "application/json" }));
      a.download = `apuestas-intel-respaldo-${new Date().toISOString().slice(0, 10)}.json`;
      a.click();
    } catch { /* en la app se usa copiar/pegar */ }
    navigator.clipboard?.writeText(json).then(() => setMsg("Copia creada y copiada al portapapeles."), () => setMsg("Copia creada: copie el texto de abajo."));
  };
  const importNow = (raw: string) => {
    try {
      const d = JSON.parse(raw);
      if (d.app !== "apuestas-intel-co") throw new Error("Archivo no reconocido");
      for (const k of BACKUP_KEYS) if (typeof d[k] === "string") localStorage.setItem(k, d[k]);
      setMsg("Datos restaurados. Recargando…");
      setTimeout(() => location.reload(), 800);
    } catch (e: any) { setMsg(`No se pudo restaurar: ${e.message}`); }
  };
  return (
    <Card title="Copia de seguridad y paso a otro dispositivo">
      <p className="text-xs text-ink-muted">Sus cuotas, apuestas, combinadas y límites se guardan en este dispositivo. Exporte una copia y restáurela en el celular o computador donde quiera continuar.</p>
      <div className="mt-3 flex flex-wrap gap-2">
        <button className="btn-primary" onClick={exportNow}>Exportar copia</button>
        <label className="btn-ghost cursor-pointer">Restaurar desde archivo<input type="file" accept="application/json,.json" className="hidden" onChange={async (e) => { const f = e.target.files?.[0]; if (f) importNow(await f.text()); }} /></label>
        <button className="btn-ghost" disabled={!txt} onClick={() => importNow(txt)}>Restaurar desde el texto</button>
      </div>
      <textarea className="input mt-3 h-24 font-mono text-[11px]" placeholder="…o pegue aquí el texto de una copia para restaurarla" value={txt} onChange={(e) => setTxt(e.target.value)} />
      {msg && <p className="mt-2 text-xs text-ink-2">{msg}</p>}
    </Card>
  );
}

function Sync() {
  const [cfg, setCfg] = useState({ token: "", gist_id: null as string | null, last_sync: null as string | null });
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => { const c = syncConfig(); setCfg({ token: c.token, gist_id: c.gist_id, last_sync: c.last_sync }); }, []);
  const run = async () => {
    setBusy(true); setMsg("");
    try { setSyncConfig({ token: cfg.token.trim() }); setMsg(await syncNow()); const c = syncConfig(); setCfg({ token: c.token, gist_id: c.gist_id, last_sync: c.last_sync }); }
    catch (e: any) { setMsg(e.message); } finally { setBusy(false); }
  };
  return (
    <Card title="Sincronizar entre dispositivos">
      <p className="text-xs text-ink-muted">Use un Gist secreto de su propia cuenta de GitHub para tener las mismas apuestas, cuotas y ajustes en el celular y en la web. Cree un token en GitHub → Settings → Developer settings → Personal access tokens (solo permiso «gist») y péguelo aquí en cada dispositivo. El token se guarda únicamente en este dispositivo.</p>
      <div className="mt-3 flex flex-wrap gap-2">
        <input className="input max-w-md" type="password" placeholder="Token de GitHub (permiso gist)" value={cfg.token} onChange={(e) => setCfg({ ...cfg, token: e.target.value })} />
        <button className="btn-primary" disabled={busy || !cfg.token.trim()} onClick={run}>{busy ? "Sincronizando…" : "Sincronizar ahora"}</button>
        {cfg.token && <button className="btn-ghost" onClick={() => { setSyncConfig({ token: "", gist_id: null, last_hash: null, last_sync: null }); setCfg({ token: "", gist_id: null, last_sync: null }); setMsg("Sincronización desactivada en este dispositivo."); }}>Desactivar</button>}
      </div>
      {cfg.gist_id && <p className="mt-2 text-xs text-ink-2">Gist: {cfg.gist_id}{cfg.last_sync ? ` · última sincronización ${bogota(cfg.last_sync)}` : ""}. Se sincroniza solo al abrir la app y cada 10 minutos.</p>}
      {msg && <p className="mt-2 text-xs text-ink-2">{msg}</p>}
    </Card>
  );
}

function BankrollCard() {
  const [b, setB] = useState(loadBankroll());
  const [ok, setOk] = useState(false);
  return (
    <Card title="Banca y tamaño de apuesta">
      <p className="text-xs text-ink-muted">Con su banca, la app sugiere cuánto apostar en cada oportunidad: una fracción de Kelly según la ventaja estimada, nunca más del tope por apuesta. La banca actual se calcula con sus apuestas liquidadas en «Mis apuestas».</p>
      <div className="mt-3 grid gap-3 sm:grid-cols-3">
        <div><label className="label">Banca inicial (COP)</label><input type="number" className="input" value={b.initial_cop || ""} onChange={(e) => setB({ ...b, initial_cop: +e.target.value })} /></div>
        <div><label className="label">Fracción de Kelly</label>
          <select className="input" value={b.kelly_fraction} onChange={(e) => setB({ ...b, kelly_fraction: +e.target.value })}>
            <option value={0.1}>1/10 (muy prudente)</option><option value={0.25}>1/4 (recomendado)</option><option value={0.5}>1/2 (agresivo)</option></select></div>
        <div><label className="label">Tope por apuesta</label>
          <select className="input" value={b.max_pct} onChange={(e) => setB({ ...b, max_pct: +e.target.value })}>
            <option value={0.01}>1 % de la banca</option><option value={0.02}>2 % de la banca</option><option value={0.05}>5 % de la banca</option></select></div>
      </div>
      <button className="btn-primary mt-3" onClick={() => { saveBankroll(b); setOk(true); setTimeout(() => setOk(false), 2000); }}>{ok ? "Guardado" : "Guardar"}</button>
    </Card>
  );
}

function Alerts() {
  const [st, setSt] = useState({ enabled: false, min_ev: 0.03 });
  const [msg, setMsg] = useState("");
  useEffect(() => { import("@/lib/notify").then((m) => setSt(m.alertSettings())); }, []);
  const save = async (enabled: boolean, min_ev: number) => {
    const m = await import("@/lib/notify");
    if (enabled && !(await m.requestPermission())) { setMsg("El sistema no concedió permiso para notificaciones."); return; }
    m.setAlertSettings(enabled, min_ev);
    setSt({ enabled, min_ev });
    setMsg(enabled ? "Alertas activadas." : "Alertas desactivadas.");
  };
  return (
    <Card title="Alertas de oportunidades">
      <p className="text-xs text-ink-muted">Avisa cuando aparece un surebet o una apuesta con valor esperado por encima del umbral, mientras la app está abierta y al volver a ella.</p>
      <div className="mt-3 flex flex-wrap items-end gap-3">
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={st.enabled} onChange={(e) => save(e.target.checked, st.min_ev)} /> Activar alertas</label>
        <div><label className="label">EV mínimo</label><input type="number" step="0.01" className="input w-28" value={st.min_ev} onChange={(e) => save(st.enabled, +e.target.value)} /></div>
        <button className="btn-ghost" onClick={async () => { const m = await import("@/lib/notify"); const n = await m.checkAndNotify(); setMsg(n ? `${n} alertas nuevas enviadas.` : "No hay oportunidades nuevas ahora."); }}>Comprobar ahora</button>
      </div>
      <p className="mt-3 text-xs text-ink-muted">Para recibir avisos con la app cerrada: instale la app gratuita <b>ntfy</b>, suscríbase a un tema privado (un nombre difícil de adivinar) y guárdelo como secreto <code>NTFY_TOPIC</code> del repositorio. El pipeline enviará las oportunidades detectadas con el feed de cuotas.</p>
      {msg && <p className="mt-2 text-xs text-ink-2">{msg}</p>}
    </Card>
  );
}

function LiveServer() {
  const [url, setUrl] = useState("");
  const [msg, setMsg] = useState("");
  useEffect(() => { setUrl(serverUrl() || ""); }, []);
  if (process.env.NEXT_PUBLIC_MODE !== "static") return null;
  const test = async () => {
    try {
      const r = await fetch(`${url.replace(/\/+$/, "")}/api/health`);
      if (!r.ok) throw new Error(String(r.status));
      setServerUrl(url); setMsg("Conectado. Recargando…"); setTimeout(() => location.reload(), 600);
    } catch (e: any) { setMsg(`No responde (${e.message}). Revise la URL y que el servidor esté encendido.`); }
  };
  return (
    <Card title="Servidor en vivo (opcional)">
      <p className="text-xs text-ink-muted">Si despliega el backend (por ejemplo con el botón de Render del README), la app usará datos en tiempo real, WebSocket de partidos en directo y cuentas sincronizadas. Sin servidor funciona con los datos del pipeline cada 30 minutos.</p>
      <div className="mt-3 flex flex-wrap gap-2">
        <input className="input max-w-md" placeholder="https://su-servidor.onrender.com" value={url} onChange={(e) => setUrl(e.target.value)} />
        <button className="btn-primary" onClick={test}>Conectar</button>
        {serverUrl() && <button className="btn-ghost" onClick={() => { setServerUrl(null); location.reload(); }}>Desconectar</button>}
      </div>
      {msg && <p className="mt-2 text-xs text-ink-2">{msg}</p>}
    </Card>
  );
}

function StaticSettings() {
  const status = useApi("/status");
  const [me, setMe] = useState<any>(null);
  const [url, setUrl] = useState("");
  const loadMe = () => { api("/auth/me").then(setMe).catch(() => {}); };
  useEffect(() => { loadMe(); import("@/lib/staticApi").then((m) => setUrl(m.dataUrl())); }, []);
  return (
    <div className="space-y-4">
      <PageHeader title="Configuración" subtitle="Fuente de datos, sus cuotas, límites de juego responsable y estado de los proveedores." />
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Fuente de datos">
          <p className="text-sm text-ink-2">Datos generados por el pipeline automático: <b>{status.data?.generated_at ? bogota(status.data.generated_at) : "—"}</b></p>
          <label className="label mt-3">URL de datos</label><input className="input" value={url} onChange={(e) => setUrl(e.target.value)} />
          <div className="mt-3 flex gap-2">
            <button className="btn-primary" onClick={async () => { const m = await import("@/lib/staticApi"); m.setDataUrl(url); m.clearCache(); status.reload(); }}>Guardar y actualizar</button>
            <button className="btn-ghost" onClick={async () => { const m = await import("@/lib/staticApi"); m.clearCache(); location.reload(); }}>Actualizar datos</button>
          </div>
        </Card>
        <Card title="Proveedores del pipeline">
          {status.data && (
            <table className="data"><tbody>{Object.entries(status.data.providers).map(([k, p]: any) => (
              <tr key={k}><td>{k}</td><td className="text-xs text-ink-2">{p.role}</td><td>{p.configured ? <StatusBadge status="good">activo</StatusBadge> : <StatusBadge status="warning">sin clave</StatusBadge>}</td></tr>
            ))}</tbody></table>
          )}
          <p className="mt-2 text-xs text-ink-muted">Las claves se configuran como secretos del repositorio en GitHub (Settings → Secrets → Actions): ODDSPAPI_KEY (gratis), ODDS_API_NET_KEY, API_FOOTBALL_KEY, NTFY_TOPIC. Nunca se guardan en el teléfono.</p>
        </Card>
      </div>
      <DeviceOdds />
      <Alerts />
      {me && <Limits me={me} reload={loadMe} />}
      <LiveServer />
      <BankrollCard />
      <Sync />
      <Backup />
    </div>
  );
}

export default function Settings() {
  if (isStatic()) return <StaticSettings />;
  return <ServerSettings />;
}

function ServerSettings() {
  const status = useApi("/status");
  const [me, setMe] = useState<any>(null);
  const loadMe = () => { if (!getToken()) { setMe(null); return; } api("/auth/me").then(setMe).catch(() => { setToken(null); setMe(null); }); };
  useEffect(loadMe, []);
  return (
    <div className="space-y-4">
      <PageHeader title="Configuración" subtitle="Cuenta, límites de juego responsable, proveedores de datos y acciones de mantenimiento." />
      <div className="grid gap-4 lg:grid-cols-2">
        <Account me={me} reload={loadMe} />
        <Card title="Proveedores de datos">
          {status.data && (
            <table className="data"><tbody>{Object.entries(status.data.providers).map(([k, p]: any) => (
              <tr key={k}><td>{k}</td><td className="text-xs text-ink-2">{p.role}</td><td>{p.configured ? <StatusBadge status="good">activo</StatusBadge> : <StatusBadge status="warning">sin clave</StatusBadge>}</td></tr>
            ))}</tbody></table>
          )}
          <p className="mt-2 text-xs text-ink-muted">Las claves se configuran en el archivo <code>.env</code> del servidor (ver <code>.env.example</code>). Nunca se exponen al navegador.</p>
        </Card>
      </div>
      {me && <Limits me={me} reload={loadMe} />}
      <ManualOdds />
      <Alerts />
      <LiveServer />
      <BankrollCard />
      <Sync />
      <Backup />
      {me?.is_admin && <Admin />}
      {status.data?.ingestion?.length > 0 && (
        <Card title="Últimas ingestas">
          <table className="data"><tbody>{status.data.ingestion.map((l: any, i: number) => (
            <tr key={i}><td className="num">{bogota(l.started_at)}</td><td>{l.provider}</td><td>{l.kind}</td><td>{l.status === "ok" ? <StatusBadge status="good">ok</StatusBadge> : <StatusBadge status="critical">{l.status}</StatusBadge>}</td><td className="num">{l.count}</td><td className="text-xs text-ink-muted">{l.detail?.error || ""}</td></tr>
          ))}</tbody></table>
        </Card>
      )}
    </div>
  );
}
