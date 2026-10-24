"use client";
import Link from "next/link";
import { bogota, num, SPORT_LABEL } from "@/lib/format";
import { Badge, Empty, ProbBar, StatusBadge } from "./ui";

export type EventRow = {
  id: number; sport: string; label: string; home: string; away: string; start_time: string; status: string;
  competition: string | null; home_score: number | null; away_score: number | null; minute: number | null;
  probs?: { home: number; draw?: number; away: number } | null; live?: any; expected_goals?: { home: number; away: number } | null;
  data_sufficient?: boolean; model_note?: string | null; colombian_operators?: number;
};

export default function EventTable({ events, empty }: { events: EventRow[]; empty?: string }) {
  if (!events.length) return <Empty>{empty || "No hay eventos para este filtro."}</Empty>;
  return (
    <div className="overflow-x-auto">
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
                  <Link href={`/partido/${e.id}`} className="font-medium hover:text-accent">{e.label}</Link>
                  {e.home_score != null && <span className="ml-2 num text-ink">{e.home_score}-{e.away_score}</span>}
                  <div className="text-[11px] text-ink-muted">{SPORT_LABEL[e.sport] || e.sport}</div>
                </td>
                <td className="text-ink-2">{e.competition || "—"}</td>
                <td>{p ? <ProbBar probs={p} /> : <span className="text-xs text-ink-muted">{e.model_note || "Sin modelo"}</span>}</td>
                <td className="num text-ink-2">{e.expected_goals ? `${num(e.expected_goals.home, 2)} – ${num(e.expected_goals.away, 2)}` : "—"}</td>
                <td>{e.colombian_operators ? <Badge>{e.colombian_operators}</Badge> : <span className="text-xs text-ink-muted">sin cuotas</span>}</td>
                <td>{e.data_sufficient ? <StatusBadge status="good">OK</StatusBadge> : <StatusBadge status="warning">Limitados</StatusBadge>}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
