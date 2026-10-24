"use client";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { Card, Empty, PageHeader, ProbBar, StatusBadge } from "@/components/ui";
import { api, isStatic, wsUrl } from "@/lib/api";
import { odds } from "@/lib/format";

export default function Live() {
  const [events, setEvents] = useState<any[]>([]);
  const [mode, setMode] = useState<"ws" | "poll" | "connecting">("connecting");
  const [updated, setUpdated] = useState<string | null>(null);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    let poll: ReturnType<typeof setInterval> | null = null;
    const startPolling = () => {
      setMode("poll");
      const load = () => api("/events?scope=live").then((d) => { setEvents(d.events); setUpdated(new Date().toISOString()); }).catch(() => {});
      load();
      poll = setInterval(load, 20000);
    };
    if (isStatic()) { startPolling(); return () => { if (poll) clearInterval(poll); }; }
    try {
      const ws = new WebSocket(wsUrl());
      wsRef.current = ws;
      const timer = setTimeout(() => { if (ws.readyState !== 1) { ws.close(); startPolling(); } }, 4000);
      ws.onopen = () => { clearTimeout(timer); setMode("ws"); };
      ws.onmessage = (m) => {
        const msg = JSON.parse(m.data);
        setUpdated(new Date().toISOString());
        if (msg.type === "snapshot") setEvents(msg.events);
        else if (msg.type === "update") setEvents((prev) => {
          const map = new Map(prev.map((e) => [e.id, e]));
          for (const e of msg.events) map.set(e.id, e);
          return Array.from(map.values());
        });
      };
      ws.onerror = () => { clearTimeout(timer); if (!poll) startPolling(); };
      const ping = setInterval(() => ws.readyState === 1 && ws.send("ping"), 25000);
      return () => { clearInterval(ping); ws.close(); if (poll) clearInterval(poll); };
    } catch {
      startPolling();
      return () => { if (poll) clearInterval(poll); };
    }
  }, []);

  return (
    <div>
      <PageHeader title="Partidos en directo"
        subtitle="Probabilidades actualizadas con marcador, minuto, expulsiones y rendimiento observado (xG o tiros al arco)."
        right={<StatusBadge status={mode === "ws" ? "good" : "info"}>{mode === "ws" ? "WebSocket conectado" : mode === "poll" ? (isStatic() ? "Datos del último ciclo del pipeline" : "Actualización cada 20 s") : "Conectando…"}</StatusBadge>} />
      {!events.length ? (
        <Empty>No hay partidos en directo en este momento. Los datos en vivo requieren API_FOOTBALL_KEY (estadísticas) y ODDS_API_NET_KEY (cuotas en vivo).</Empty>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {events.map((e) => {
            const lp = e.live_model?.probs || e.live?.probs;
            return (
              <Card key={e.id} title={<span>{e.competition || e.sport}</span>} right={<StatusBadge status="critical">{e.minute ?? "?"}'</StatusBadge>}>
                <Link href={`/partido?id=${e.id}`} className="flex items-center justify-between text-lg font-semibold hover:text-accent">
                  <span>{e.home}</span><span className="num">{e.home_score ?? 0} - {e.away_score ?? 0}</span><span>{e.away}</span>
                </Link>
                {lp ? <div className="mt-3"><div className="mb-1 text-xs text-ink-muted">Probabilidad en vivo</div><ProbBar probs={lp} /></div>
                  : <p className="mt-3 text-xs text-ink-muted">{e.model_note || "Sin modelo en vivo para este evento"}</p>}
                {e.prematch_probs && <div className="mt-3"><div className="mb-1 text-xs text-ink-muted">Pre-partido</div><ProbBar probs={e.prematch_probs} /></div>}
                {e.best_odds?.length > 0 && (
                  <table className="data mt-3"><tbody>
                    {e.best_odds.slice(0, 5).map((o: any, i: number) => (
                      <tr key={i}><td className="text-xs">{o.selection}</td><td className="text-xs text-ink-2">{o.operator}</td><td className="num">{odds(o.odds)}</td></tr>
                    ))}
                  </tbody></table>
                )}
              </Card>
            );
          })}
        </div>
      )}
      {updated && <p className="mt-3 text-xs text-ink-muted">Última actualización: {new Date(updated).toLocaleTimeString("es-CO")}</p>}
    </div>
  );
}
