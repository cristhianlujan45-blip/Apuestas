"use client";
import { useState } from "react";
import EventTable from "./EventTable";
import { Card, ErrorBox, Loading, PageHeader } from "./ui";
import { SPORT_LABEL } from "@/lib/format";
import { useApi } from "@/lib/useApi";

export default function EventsPage({ scope, title, subtitle }: { scope: "today" | "upcoming" | "finished"; title: string; subtitle: string }) {
  const [sport, setSport] = useState("");
  const { data, error, loading } = useApi(`/events?scope=${scope}&limit=300${sport ? `&sport=${sport}` : ""}`, [sport], 120000);
  return (
    <div>
      <PageHeader title={title} subtitle={subtitle} right={
        <div className="flex flex-wrap gap-1">
          {["", "football", "basketball", "tennis", "baseball", "volleyball"].map((s) => (
            <button key={s} onClick={() => setSport(s)} className={`tab ${sport === s ? "tab-active" : ""}`}>{s ? SPORT_LABEL[s] : "Todos"}</button>
          ))}
        </div>} />
      <Card>{loading && !data ? <Loading /> : error ? <ErrorBox error={error} /> : <EventTable events={data?.events || []} />}</Card>
    </div>
  );
}
