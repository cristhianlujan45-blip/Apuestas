"use client";
import { useState } from "react";
import { Card, Empty, ErrorBox, Loading, PageHeader, StatusBadge } from "@/components/ui";
import { num } from "@/lib/format";
import { useApi } from "@/lib/useApi";

const GROUP_LABEL: Record<string, string> = { ENG: "Inglaterra", ESP: "España", ITA: "Italia", GER: "Alemania", FRA: "Francia", NED: "Países Bajos", POR: "Portugal", BEL: "Bélgica", TUR: "Turquía", SCO: "Escocia", ARG: "Argentina", BRA: "Brasil", MEX: "México", USA: "EE. UU.", COL: "Colombia" };

const SPORT_MODELS = [
  { sport: "Fútbol", models: "Poisson, Poisson bivariado, Dixon-Coles (MAP + Laplace), Elo, Glicko-2, xG (proveedor o proxy por tiros), xT/xA (StatsBomb), ML (LogReg, RF, LightGBM, XGBoost, CatBoost, MLP), modelo en directo bayesiano, córners/tarjetas/tiros con binomial negativa." },
  { sport: "Baloncesto", models: "ORtg/DRtg ajustados por rival por 100 posesiones, ritmo (pace), Four Factors, puntos simulados con normal bivariante y prórrogas, props de jugador (puntos, rebotes, asistencias, triples) con binomial negativa." },
  { sport: "Tenis", models: "Elo por superficie, puntos ganados al saque/resto (Barnett-Clarke), cadena de Markov analítica (juego, tie-break, set, partido), simulación de juegos y sets." },
  { sport: "Béisbol", models: "Ataque/defensa log-lineal de carreras, binomial negativa, entradas extra con corredor fantasma." },
  { sport: "Voleibol", models: "Probabilidad de rally ajustada por rival, simulación rally a rally de sets a 25/15." },
];

export default function Sports() {
  const [group, setGroup] = useState("ENG");
  const r = useApi(`/football/ratings?group=${group}`, [group]);
  const xt = useApi("/football/xt");
  return (
    <div className="space-y-4">
      <PageHeader title="Análisis por deporte" subtitle="Modelos especializados por deporte y mercado. Las fuerzas se estiman con datos históricos reales y ponderación temporal." />
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-5">{SPORT_MODELS.map((s) => <Card key={s.sport} title={s.sport}><p className="text-xs text-ink-2">{s.models}</p></Card>)}</div>
      <Card title="Fútbol · fuerzas Dixon-Coles" right={r.data && <select className="input w-auto" value={group} onChange={(e) => setGroup(e.target.value)}>{r.data.groups.map((g: string) => <option key={g} value={g}>{GROUP_LABEL[g] || g}</option>)}</select>}>
        {r.loading ? <Loading /> : r.error ? <ErrorBox error={r.error} /> : (
          <>
            <p className="mb-2 text-xs text-ink-muted num">Ventaja local (log): {num(r.data.home_advantage, 3)} · ρ Dixon-Coles: {num(r.data.rho, 3)} · {r.data.n_matches} partidos · {r.data.version}</p>
            <div className="max-h-[480px] overflow-y-auto"><table className="data">
              <thead><tr><th>#</th><th>Equipo</th><th>Ataque</th><th>Defensa</th><th>Goles a favor esperados*</th><th>Goles en contra esperados*</th></tr></thead>
              <tbody>{r.data.ratings.map((t: any, i: number) => (
                <tr key={t.team}><td className="num text-ink-muted">{i + 1}</td><td>{t.team}</td><td className="num">{num(t.attack, 3)}</td><td className="num">{num(t.defense, 3)}</td>
                  <td className="num">{num(t.exp_goals_for_vs_avg, 2)}</td><td className="num">{num(t.exp_goals_against_vs_avg, 2)}</td></tr>
              ))}</tbody></table></div>
            <p className="mt-1 text-[11px] text-ink-muted">*Frente a un rival promedio en campo neutral. Defensa negativa = concede menos.</p>
          </>
        )}
      </Card>
      <Card title="Expected Threat (xT) y Expected Assists (xA) · StatsBomb Open Data">
        {xt.loading ? <Loading label="Descargando eventos de StatsBomb y calculando xT (primera vez puede tardar)…" /> : xt.error ? <ErrorBox error={xt.error} /> : (
          <>
            <p className="mb-2 text-xs text-ink-muted">{xt.data.matches} partidos · {xt.data.events.toLocaleString("es-CO")} eventos · competición {xt.data.competition_id}/{xt.data.season_id} · {xt.data.source}</p>
            <XtGrid grid={xt.data.grid} />
            <table className="data mt-3"><thead><tr><th>Jugador</th><th>Equipo</th><th>xT añadido</th><th>xA</th><th>xG</th><th>Pases clave</th></tr></thead>
              <tbody>{xt.data.players.slice(0, 15).map((p: any) => (
                <tr key={p.player}><td>{p.player}</td><td className="text-ink-2">{p.team}</td><td className="num">{num(p.xt_added, 2)}</td><td className="num">{num(p.xa, 2)}</td><td className="num">{num(p.xg, 2)}</td><td className="num">{p.key_passes}</td></tr>
              ))}</tbody></table>
          </>
        )}
      </Card>
      <Card title="Otros deportes"><Empty>Baloncesto, tenis, béisbol y voleibol se activan al importar histórico real (CSV en data/import o API-Sports). Ver docs/DATOS.md. <StatusBadge status="info">Sin datos inventados</StatusBadge></Empty></Card>
    </div>
  );
}

function XtGrid({ grid }: { grid: number[][] }) {
  // grid[x][y]; dibujar con y en filas (campo horizontal, ataque hacia la derecha). Rampa secuencial azul.
  const max = Math.max(...grid.flat());
  const ramp = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"];
  const ny = grid[0].length;
  return (
    <div className="overflow-x-auto">
      <div className="inline-grid gap-[2px] rounded border border-line p-1" style={{ gridTemplateColumns: `repeat(${grid.length}, 28px)` }}>
        {Array.from({ length: ny }).map((_, y) => grid.map((col, x) => {
          const v = col[y] / max;
          const c = ramp[Math.min(ramp.length - 1, Math.floor(v * ramp.length))];
          return <div key={`${x}-${y}`} title={`xT ${col[y].toFixed(3)}`} style={{ background: c, height: 18 }} className="rounded-sm" />;
        }))}
      </div>
      <p className="mt-1 text-[11px] text-ink-muted">Más oscuro = mayor probabilidad de que la posesión termine en gol. Ataque hacia la derecha.</p>
    </div>
  );
}
