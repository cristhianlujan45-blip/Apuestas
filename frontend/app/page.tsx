"use client";
import { Bot, CalendarDays, Camera, Gift, Hourglass, Search, Ticket, Zap } from "lucide-react";
import Link from "next/link";
import { useState, type ReactNode } from "react";
import EventTable from "@/components/EventTable";
import { Card, Disclaimer, Empty, ErrorBox, Loading, StatusBadge } from "@/components/ui";
import { odds, signedPct } from "@/lib/format";
import { useApi } from "@/lib/useApi";

const PRESETS = [2, 3, 5, 10, 20, 50];

const ACTIONS: { href: string; title: string; text: string; icon: ReactNode }[] = [
  { href: "/parlay", title: "Buscar mi cuota", text: "Combinadas para la cuota que quiere", icon: <Search size={22} /> },
  { href: "/partidos", title: "Partidos por día", text: "Probabilidades de cada partido", icon: <CalendarDays size={22} /> },
  { href: "/ia-apuestas", title: "IA de apuestas", text: "Qué recomienda y cómo le va", icon: <Bot size={22} /> },
  { href: "/retrasadas", title: "Cuotas retrasadas", text: "Casas que pagan de más", icon: <Hourglass size={22} /> },
  { href: "/ventaja", title: "Surebets", text: "Ganancia segura entre casas", icon: <Zap size={22} /> },
  { href: "/bonos", title: "Bonos", text: "Convierta apuestas gratis en saldo", icon: <Gift size={22} /> },
  { href: "/captura", title: "Cuotas desde foto", text: "Lea las cuotas de su casa", icon: <Camera size={22} /> },
  { href: "/boleto", title: "Mi boleto", text: "Elija usted las cuotas de uno o varios partidos", icon: <Ticket size={22} /> },
];

function DataStatus() {
  const { data } = useApi("/status", [], 60000);
  if (!data) return null;
  const co = data.counts?.colombian_quotes || 0;
  const p = data.providers || {};
  const feed = p.odds_api_net?.configured || p.oddspapi?.configured;
  return (
    <Card title="Estado de los datos">
      <ul className="space-y-2 text-sm">
        <li className="flex items-start gap-2"><StatusBadge status="good">Activo</StatusBadge>
          <span className="text-ink-2"><b className="text-ink num">{data.counts?.upcoming ?? 0}</b> partidos con predicción del modelo · se actualiza cada 30 minutos</span></li>
        <li className="flex items-start gap-2">
          {co ? <StatusBadge status="good">Activo</StatusBadge> : <StatusBadge status="warning">Falta</StatusBadge>}
          <span className="text-ink-2">{co ? <><b className="text-ink num">{co}</b> cuotas de casas colombianas</> : feed
            ? "Cuotas colombianas: conectadas, esperando la próxima consulta"
            : <>Cuotas colombianas sin conectar. Mientras tanto use <Link className="text-accent underline" href="/captura">cuotas desde foto</Link>; PARLAY usa cuotas de referencia.</>}</span></li>
        <li className="flex items-start gap-2">
          {data.counts?.live ? <StatusBadge status="critical">En vivo</StatusBadge> : <StatusBadge status="info">—</StatusBadge>}
          <span className="text-ink-2">{data.counts?.live ? `${data.counts.live} partidos en directo` : "Ningún partido en directo ahora"}</span></li>
      </ul>
    </Card>
  );
}

function Opportunities() {
  const agent = useApi("/agent", [], 120000);
  const stale = useApi("/stale-lines?min_edge=0.02", [], 120000);
  const rows = [
    ...(agent.data?.open || []).map((b: any) => ({ kind: "IA", event: b.event, event_id: b.event_id, sel: b.selection, op: b.operator, odds: b.odds, edge: b.edge })),
    ...(stale.data?.lines || []).map((l: any) => ({ kind: l.status === "retrasada" ? "Retrasada" : "Sobre mercado", event: l.event, event_id: l.event_id, sel: l.selection, op: l.operator_name, odds: l.odds, edge: l.edge })),
  ].sort((a, b) => b.edge - a.edge).slice(0, 6);
  return (
    <Card title="Oportunidades ahora" right={<Link href="/retrasadas" className="text-xs text-accent">Ver todas</Link>}>
      {agent.loading && stale.loading ? <Loading /> : !rows.length ? (
        <Empty>Sin oportunidades en este momento. Aparecen cuando una casa colombiana paga más que el precio justo del mercado.</Empty>
      ) : (
        <ul className="divide-y divide-line">
          {rows.map((r, i) => (
            <li key={i} className="flex items-center justify-between gap-3 py-2">
              <Link href={`/partido?id=${r.event_id}`} className="min-w-0">
                <div className="truncate text-sm font-medium">{r.sel}</div>
                <div className="truncate text-[11px] text-ink-muted">{r.event} · {r.op} · {r.kind}</div>
              </Link>
              <div className="shrink-0 text-right"><div className="num">{odds(r.odds)}</div><div className="num text-[11px] text-good">{signedPct(r.edge)}</div></div>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

export default function Home() {
  const today = useApi("/events?scope=today&limit=8", [], 120000);
  const [target, setTarget] = useState(5);
  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">¿Qué quiere hacer hoy?</h1>
        <p className="mt-1 text-sm text-ink-2">Análisis de partidos y cuotas de casas autorizadas en Colombia. La app no coloca apuestas ni garantiza ganancias.</p>
      </div>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        {ACTIONS.map((a) => (
          <Link key={a.href} href={a.href} className="card flex flex-col gap-1 p-3 transition hover:border-line-strong hover:bg-surface-2 active:bg-surface-2">
            <span className="text-accent">{a.icon}</span>
            <span className="text-sm font-semibold leading-tight">{a.title}</span>
            <span className="text-[11px] leading-tight text-ink-muted">{a.text}</span>
          </Link>
        ))}
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <Card title="Buscar mi cuota">
          <div className="flex items-baseline gap-2"><span className="text-4xl font-semibold num">{target.toFixed(2)}</span><span className="text-xs text-ink-muted">cuota total</span></div>
          <div className="mt-3 grid grid-cols-6 gap-1">
            {PRESETS.map((p) => <button key={p} className={`tab px-0 num ${target === p ? "tab-active" : ""}`} onClick={() => setTarget(p)}>{p}</button>)}
          </div>
          <Link href={`/parlay?target=${target}`} className="btn-primary mt-3 w-full justify-center">Buscar combinadas</Link>
          <p className="mt-2 text-[11px] text-ink-muted">Le muestra 4 opciones (A, B, C, D) por casa: mayor probabilidad, equilibrio, mejor valor y menos selecciones.</p>
        </Card>
        <Opportunities />
        <DataStatus />
      </div>

      <Card title="Próximos partidos de hoy" right={<Link href="/partidos" className="text-xs text-accent">Elegir otro día</Link>}>
        {today.loading && !today.data ? <Loading /> : today.error ? <ErrorBox error={today.error} /> :
          <EventTable events={today.data?.events || []} empty="No hay más partidos hoy. Vea los de mañana en «Partidos por día»." />}
      </Card>
      <p className="text-center text-[11px] text-ink-muted">Probabilidades de un modelo validado con miles de partidos reales · <Link className="underline" href="/ia">cómo funciona</Link> · <Link className="underline" href="/rendimiento">rendimiento real</Link></p>
      <Disclaimer />
    </div>
  );
}
