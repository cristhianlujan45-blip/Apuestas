"use client";
import { useEffect, useRef, useState } from "react";
import { Badge, Card, Disclaimer, PageHeader } from "@/components/ui";
import { api } from "@/lib/api";

const SUGGESTIONS = ["Analiza los partidos de hoy", "Busca una cuota de 5", "Construye un parlay mixto", "Compara BetPlay con Wplay",
  "Busca las mejores cuotas para Arsenal vs Everton", "Analiza los últimos diez partidos de Barcelona", "Encuentra oportunidades estadísticas",
  "¿Qué combinada tiene mayor probabilidad estimada?", "Construye una combinada con máximo tres selecciones", "Analiza los partidos en directo"];

function Markdownish({ text }: { text: string }) {
  return <div className="whitespace-pre-wrap text-sm leading-relaxed">{text.split(/(\*\*[^*]+\*\*)/g).map((p, i) => p.startsWith("**") ? <b key={i}>{p.slice(2, -2)}</b> : <span key={i}>{p}</span>)}</div>;
}

export default function Assistant() {
  const [msgs, setMsgs] = useState<{ role: "user" | "assistant"; content: string; meta?: any }[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => { end.current?.scrollIntoView({ behavior: "smooth" }); }, [msgs]);
  const send = async (text: string) => {
    if (!text.trim()) return;
    const next = [...msgs, { role: "user" as const, content: text }];
    setMsgs(next); setInput(""); setBusy(true);
    try {
      const r = await api("/assistant", { method: "POST", json: { messages: next.map(({ role, content }) => ({ role, content })) } });
      setMsgs([...next, { role: "assistant", content: r.answer, meta: { tools: r.tools_used, engine: r.engine } }]);
    } catch (e: any) {
      setMsgs([...next, { role: "assistant", content: `⚠️ ${e.message}` }]);
    } finally { setBusy(false); }
  };
  return (
    <div className="space-y-4">
      <PageHeader title="Asistente de IA deportiva" subtitle="Consulta los datos y modelos reales de la plataforma. Las probabilidades y cuotas que muestra provienen de las herramientas, nunca del modelo de lenguaje." />
      <Card>
        <div className="mb-3 flex flex-wrap gap-1">{SUGGESTIONS.map((s) => <button key={s} className="tab whitespace-normal border-line text-left text-xs" onClick={() => send(s)}>{s}</button>)}</div>
        <div className="max-h-[60vh] min-h-[300px] space-y-3 overflow-y-auto rounded-lg bg-page p-3">
          {msgs.map((m, i) => (
            <div key={i} className={`max-w-[90%] rounded-lg p-3 ${m.role === "user" ? "ml-auto bg-accent/20" : "bg-surface-2"}`}>
              <Markdownish text={m.content} />
              {m.meta && <div className="mt-2 flex gap-1">{m.meta.tools?.map((t: string) => <Badge key={t}>{t}</Badge>)}<Badge>{m.meta.engine === "claude" ? "Claude" : "enrutador local"}</Badge></div>}
            </div>
          ))}
          {busy && <div className="text-sm text-ink-muted">Consultando datos y modelos…</div>}
          <div ref={end} />
        </div>
        <form className="mt-3 flex gap-2" onSubmit={(e) => { e.preventDefault(); send(input); }}>
          <input className="input" value={input} onChange={(e) => setInput(e.target.value)} placeholder="Ej.: Busca una cuota de 8 con máximo 4 selecciones" />
          <button className="btn-primary" disabled={busy}>Enviar</button>
        </form>
      </Card>
      <Disclaimer />
    </div>
  );
}
