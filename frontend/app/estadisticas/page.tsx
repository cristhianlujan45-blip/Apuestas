"use client";
import { useState } from "react";
import { Card, Empty, ErrorBox, Loading, PageHeader } from "@/components/ui";
import { api } from "@/lib/api";

export default function Stats() {
  const [team, setTeam] = useState("Arsenal");
  const [n, setN] = useState(10);
  const [res, setRes] = useState<any>(null);
  const [err, setErr] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const go = () => { setBusy(true); api(`/football/team?team=${encodeURIComponent(team)}&n=${n}`).then((r) => { setRes(r); setErr(null); }).catch(setErr).finally(() => setBusy(false)); };
  return (
    <div className="space-y-4">
      <PageHeader title="Estadísticas" subtitle="Últimos partidos reales de un equipo (football-data.co.uk): resultado, tiros, tiros al arco y córners." />
      <Card>
        <div className="flex flex-wrap items-end gap-3">
          <div><label className="label">Equipo</label><input className="input" value={team} onChange={(e) => setTeam(e.target.value)} /></div>
          <div><label className="label">Partidos</label><input type="number" className="input w-24" value={n} onChange={(e) => setN(+e.target.value)} /></div>
          <button className="btn-primary" onClick={go} disabled={busy}>Analizar</button>
        </div>
      </Card>
      {busy && <Loading />}<ErrorBox error={err} />
      {res && (res.error ? <Empty>{res.error}</Empty> : (
        <Card title={`${res.team} · ${res.summary.wins}G ${res.summary.draws}E ${res.summary.losses}P`}>
          <table className="data"><thead><tr><th>Fecha</th><th>Rival</th><th>Condición</th><th>Marcador</th><th>Res.</th><th>Tiros</th><th>Al arco</th><th>Córners</th></tr></thead>
            <tbody>{res.matches.slice().reverse().map((m: any, i: number) => (
              <tr key={i}><td className="num">{m.date}</td><td>{m.opponent}</td><td>{m.venue}</td><td className="num">{m.score}</td>
                <td className={m.result === "G" ? "text-good" : m.result === "P" ? "text-critical" : "text-ink-2"}>{m.result}</td>
                <td className="num">{m.shots ?? "—"}</td><td className="num">{m.shots_on_target ?? "—"}</td><td className="num">{m.corners ?? "—"}</td></tr>
            ))}</tbody></table>
          <p className="mt-2 text-xs text-ink-muted">Fuente: {res.source}</p>
        </Card>
      ))}
    </div>
  );
}
