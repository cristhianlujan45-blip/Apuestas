"use client";
import Link from "next/link";
import { bogota, num, SPORT_LABEL } from "@/lib/format";
import { Badge, Empty, ProbBar, StatusBadge } from "./ui";

export type EventRow = {
  id: number; sport: string; label: string; home: string; away: string; start_time: string; status: string;
  competition: string | null; home_score: number | null; away_score: number | null; minute: number | null;
  probs?: { home: number; draw?: number; away: number } | null; live?: any; expected_goals?: { home: number; away: number } | null;
  data_sufficient?: boolean; model_note?: string | null; colombian_operators?: number; prematch?: any;
};

function Verdict({ probs, hs, as }: { probs: Record<string, number>; hs: number; as: number }) {
  const pred = Object.keys(probs).reduce((a, b) => ((probs[a] ?? 0) >= (probs[b] ?? 0) ? a : b));
  const act = hs > as ? "home" : hs < as ? "away" : "draw";
  const name: Record<string, string> = { home: "local", draw: "empate", away: "visitante" };
  return (
    <div className="mt-1 text-[11px]">
      <span className="text-ink-muted">Antes del partido dijo {name[pred]} · </span>
      {pred === act ? <span className="text-good">acertó</span> : <span className="text-critical">falló</span>}
    </div>
  );
}

function short(name: string) {
  return name.length > 16 ? name.split(" ").slice(0, 2).join(" ") : name;
}

/** Tarjeta de partido para el celular: todo a la vista sin desplazarse de lado. */
function EventCard({ e }: { e: EventRow }) {
  const p = e.live?.probs || e.probs;
  return (
    <Link href={`/partido?id=${e.id}`} className="block rounded-xl border border-line bg-surface-2/40 p-3 active:bg-surface-2">
      <div className="flex items-center justify-between gap-2 text-[11px] text-ink-muted">
        <span className="min-w-0 truncate">{e.competition || SPORT_LABEL[e.sport] || e.sport}</span>
        <span className="shrink-0 num">
          {e.status === "live" ? <StatusBadge status="critical">EN VIVO {e.minute ?? ""}'</StatusBadge> : e.status === "finished" ? "Terminado" : bogota(e.start_time)}
        </span>
      </div>
      <div className="mt-1 flex items-center justify-between gap-2">
        <div className="min-w-0 text-[15px] font-medium leading-snug">{e.home}<span className="text-ink-muted"> vs </span>{e.away}</div>
        {e.home_score != null && <div className="shrink-0 text-lg font-semibold num">{e.home_score}-{e.away_score}</div>}
      </div>
      <div className="mt-2">
        {p ? <ProbBar probs={p} labels={[short(e.home), "Empate", short(e.away)]} />
          : <span className="text-xs text-ink-muted">{e.status === "finished" ? "Sin predicción previa registrada" : e.model_note || "Sin modelo"}</span>}
        {e.status === "finished" && p && e.home_score != null && <Verdict probs={p} hs={e.home_score} as={e.away_score!} />}
      </div>
      <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-ink-2">
        {e.expected_goals && <span className="num">Goles esperados {num(e.expected_goals.home, 1)} – {num(e.expected_goals.away, 1)}</span>}
        <span>{e.colombian_operators ? `${e.colombian_operators} casas CO con cuota` : "Sin cuotas colombianas"}</span>
        {e.status !== "finished" && e.data_sufficient === false && <span className="text-warning">Datos limitados</span>}
      </div>
    </Link>
  );
}

export default function EventTable({ events, empty }: { events: EventRow[]; empty?: string }) {
  if (!events.length) return <Empty>{empty || "No hay eventos para este filtro."}</Empty>;
  return (
    <>
    <div className="space-y-2 md:hidden">{events.map((e) => <EventCard key={e.id} e={e} />)}</div>
    <div className="hidden overflow-x-auto md:block">
      <table className="data min-w-[760px]">
        <thead>
          <tr>
            <th>Hora (COL)</th><th>Evento</th><th>Competición</th><th className="w-64">Probabilidad del modelo</th>
            <th>xG / Esperado</th><th>Casas CO</th><th>Datos</th>
          </tr>
        </thead>
        <tbody>
          {events.map((e) => {
            const p = e.live?.probs || e.probs;
            return (
              <tr key={e.id}>
                <td className="whitespace-nowrap num text-ink-2">
                  {e.status === "live" ? <StatusBadge status="critical">EN VIVO {e.minute ?? ""}'</StatusBadge> : bogota(e.start_time)}
                </td>
                <td>
                  <Link href={`/partido?id=${e.id}`} className="font-medium hover:text-accent">{e.label}</Link>
                  {e.home_score != null && <span className="ml-2 num text-ink">{e.home_score}-{e.away_score}</span>}
                  <div className="text-[11px] text-ink-muted">{SPORT_LABEL[e.sport] || e.sport}</div>
                </td>
                <td className="text-ink-2">{e.competition || "—"}</td>
                <td>{p ? <ProbBar probs={p} /> : <span className="text-xs text-ink-muted">{e.status === "finished" ? "Sin predicción previa registrada" : e.model_note || "Sin modelo"}</span>}
                  {e.status === "finished" && p && e.home_score != null && <Verdict probs={p} hs={e.home_score} as={e.away_score!} />}</td>
                <td className="num text-ink-2">{e.expected_goals ? `${num(e.expected_goals.home, 2)} – ${num(e.expected_goals.away, 2)}` : "—"}</td>
                <td>{e.colombian_operators ? <Badge>{e.colombian_operators}</Badge> : <span className="text-xs text-ink-muted">sin cuotas</span>}</td>
                <td>{e.data_sufficient ? <StatusBadge status="good">OK</StatusBadge> : <StatusBadge status="warning">Limitados</StatusBadge>}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
    </>
  );
}
