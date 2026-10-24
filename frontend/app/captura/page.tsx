"use client";
import { useState } from "react";
import { Card, Empty, ErrorBox, PageHeader, StatusBadge } from "@/components/ui";
import { api } from "@/lib/api";
import { MARKET_LABEL } from "@/lib/engine";
import { bogota } from "@/lib/format";
import { parse, recognize, type Proposal } from "@/lib/ocr";
import { useApi } from "@/lib/useApi";

const SEL: Record<string, string[]> = { "1x2": ["home", "draw", "away"], total_goals: ["over", "under"], btts: ["yes", "no"], double_chance: ["1X", "X2", "12"], dnb: ["home", "away"] };
const ES: Record<string, string> = { home: "Local", away: "Visitante", draw: "Empate", over: "Más de", under: "Menos de", yes: "Sí", no: "No" };

export default function Capture() {
  const events = useApi("/events?scope=upcoming&limit=400");
  const ops = useApi("/operators");
  const [operator, setOperator] = useState("betplay");
  const [progress, setProgress] = useState<number | null>(null);
  const [text, setText] = useState("");
  const [props, setProps] = useState<Proposal[]>([]);
  const [msg, setMsg] = useState<any>(null);
  const [err, setErr] = useState<unknown>(null);
  const evs = (events.data?.events || []).filter((e: any) => e.has_matrix !== false);
  const run = async (f: File) => {
    setErr(null); setMsg(null); setProgress(0);
    try {
      const t = await recognize(f, setProgress);
      setText(t);
      setProps(parse(t, evs));
    } catch (e) { setErr(e); } finally { setProgress(null); }
  };
  const upd = (i: number, k: keyof Proposal, v: any) => setProps(props.map((p, j) => (j === i ? { ...p, [k]: v } : p)));
  const save = async () => {
    const rows = props.filter((p) => p.include && p.event_id && p.odds > 1).map((p) => {
      const e = evs.find((x: any) => x.id === p.event_id);
      return { event_id: p.event_id, sport: "football", start_time: e?.start_time, home: e?.home, away: e?.away, operator, market: p.market, selection: p.selection, line: p.line, odds: p.odds };
    });
    try { setMsg(await api("/odds/manual", { method: "POST", json: rows })); } catch (e) { setErr(e); }
  };
  return (
    <div className="space-y-4">
      <PageHeader title="Cuotas desde una foto"
        subtitle="Tome una captura de pantalla de su casa de apuestas (o una foto) y la app leerá las cuotas en el propio dispositivo. Revise y corrija antes de guardar: el reconocimiento de texto puede equivocarse." />
      <Card title="1 · Imagen">
        <div className="flex flex-wrap items-end gap-3">
          <div><label className="label">Casa de la captura</label>
            <select className="input" value={operator} onChange={(e) => setOperator(e.target.value)}>
              {(ops.data?.operators || []).filter((o: any) => o.status === "authorized").map((o: any) => <option key={o.key} value={o.key}>{o.name}</option>)}
            </select></div>
          <label className="btn-primary cursor-pointer">Elegir captura o tomar foto
            <input type="file" accept="image/*" className="hidden" onChange={(e) => e.target.files?.[0] && run(e.target.files[0])} /></label>
        </div>
        {progress != null && <p className="mt-3 text-sm text-ink-2">Leyendo la imagen… {Math.round(progress * 100)} % (la primera vez descarga el idioma, unos segundos)</p>}
        <ErrorBox error={err} />
      </Card>
      {text && (
        <Card title="2 · Revise las cuotas detectadas">
          {!props.length ? <Empty>No se reconocieron partidos conocidos con cuotas. Asegúrese de que la captura muestre los nombres de los equipos y las cuotas, o cárguelas en Configuración → Mis cuotas.</Empty> : (
            <div className="overflow-x-auto"><table className="data min-w-[760px]">
              <thead><tr><th /><th>Partido</th><th>Mercado</th><th>Selección</th><th>Línea</th><th>Cuota</th></tr></thead>
              <tbody>{props.map((p, i) => (
                <tr key={i}>
                  <td><input type="checkbox" checked={p.include} onChange={(e) => upd(i, "include", e.target.checked)} /></td>
                  <td><select className="input" value={p.event_id ?? ""} onChange={(e) => upd(i, "event_id", +e.target.value)}>
                    {evs.map((e: any) => <option key={e.id} value={e.id}>{bogota(e.start_time)} · {e.label}</option>)}</select></td>
                  <td><select className="input" value={p.market} onChange={(e) => { upd(i, "market", e.target.value); }}>
                    {Object.keys(SEL).map((m) => <option key={m} value={m}>{MARKET_LABEL[m]}</option>)}</select></td>
                  <td><select className="input" value={p.selection} onChange={(e) => upd(i, "selection", e.target.value)}>
                    {SEL[p.market].map((x) => <option key={x} value={x}>{ES[x] || x}</option>)}</select></td>
                  <td><input className="input w-20" value={p.line ?? ""} onChange={(e) => upd(i, "line", e.target.value === "" ? null : +e.target.value)} /></td>
                  <td><input className="input w-24" value={p.odds} onChange={(e) => upd(i, "odds", +e.target.value.replace(",", "."))} /></td>
                </tr>
              ))}</tbody></table></div>
          )}
          <div className="mt-3 flex flex-wrap gap-2">
            <button className="btn-primary" disabled={!props.some((p) => p.include)} onClick={save}>Guardar cuotas seleccionadas</button>
            <button className="btn-ghost" onClick={() => setProps([...props, { include: true, event_id: evs[0]?.id ?? null, market: "1x2", selection: "home", line: null, odds: 2, source: "" }])}>Añadir fila</button>
          </div>
          {msg && <p className="mt-2 text-sm"><StatusBadge status={msg.errors?.length ? "warning" : "good"}>Guardadas: {msg.imported}</StatusBadge> {msg.errors?.map((x: any) => `fila ${x.row}: ${x.error}`).join("; ")}</p>}
          <details className="mt-3"><summary className="cursor-pointer text-xs text-ink-2">Texto reconocido</summary><pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap rounded bg-page p-2 text-xs">{text}</pre></details>
        </Card>
      )}
    </div>
  );
}
