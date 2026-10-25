"use client";
import { useEffect, useState } from "react";
import DayPicker, { dayLabel, todayBogota } from "./DayPicker";
import EventTable from "./EventTable";
import { Card, ErrorBox, Loading, PageHeader } from "./ui";
import SportPicker from "./SportPicker";
import { useApi } from "@/lib/useApi";

export default function EventsPage({ scope, title, subtitle }: { scope: "today" | "upcoming" | "finished" | "day"; title: string; subtitle: string }) {
  const [sport, setSport] = useState("");
  const [day, setDay] = useState<string[]>([]);
  useEffect(() => {
    if (scope !== "day") return;
    const q = new URLSearchParams(window.location.search).get("dia");
    setDay([q || todayBogota()]);
  }, [scope]);
  const path = scope === "day"
    ? (day[0] ? `/events?date=${day[0]}&limit=400${sport ? `&sport=${sport}` : ""}` : null)
    : `/events?scope=${scope}&limit=300${sport ? `&sport=${sport}` : ""}`;
  const { data, error, loading } = useApi(path, [path], 120000);
  const evs = data?.events || [];
  const finished = evs.filter((e: any) => e.status === "finished");
  const checked = finished.filter((e: any) => e.prematch?.probs && e.home_score != null);
  const hits = checked.filter((e: any) => {
    const p = e.prematch.probs, pred = Object.keys(p).reduce((a, b) => (p[a] >= p[b] ? a : b));
    const act = e.home_score > e.away_score ? "home" : e.home_score < e.away_score ? "away" : "draw";
    return pred === act;
  }).length;
  return (
    <div className="space-y-4">
      <PageHeader title={scope === "day" && day[0] ? `${title} · ${dayLabel(day[0])}` : title} subtitle={subtitle} />
      <SportPicker value={sport ? [sport] : []} onChange={(v) => setSport(v[0] || "")} multiple={false} allLabel="Todos" />
      {scope === "day" && (
        <Card title="Elija el día">
          <DayPicker value={day} onChange={setDay} sport={sport || undefined} />
          {checked.length > 0 && <p className="mt-2 text-sm text-ink-2 num">Ese día el modelo acertó el ganador en <b className="text-ink">{hits} de {checked.length}</b> partidos ({Math.round((hits / checked.length) * 100)} %), según lo que predijo antes de cada partido.</p>}
        </Card>
      )}
      <Card>{loading && !data ? <Loading /> : error ? <ErrorBox error={error} /> : <EventTable events={evs} empty="No hay partidos ese día en los datos disponibles." />}</Card>
    </div>
  );
}
