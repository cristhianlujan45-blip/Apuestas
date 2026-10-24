"use client";
import { useEffect, useState } from "react";
import { Card, ErrorBox, PageHeader, StatusBadge } from "@/components/ui";
import { api, getToken, setToken } from "@/lib/api";
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

export default function Settings() {
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
