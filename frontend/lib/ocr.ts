/** Extrae cuotas de una captura de pantalla de una casa de apuestas (OCR en el dispositivo). */
export type Proposal = { include: boolean; event_id: number | null; market: string; selection: string; line: number | null; odds: number; source: string };

const norm = (s: string) => s.toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/[^a-z0-9., ]/g, " ");
const STOP = new Set(["fc", "cf", "club", "de", "deportivo", "atletico", "real", "the", "united", "city", "sc", "ac"]);
const toks = (s: string) => norm(s).split(/\s+/).filter((t) => t.length >= 4 && !STOP.has(t));
const ODDS = /(?<![\d.,])(\d{1,2}[.,]\d{2})(?![\d])/g;

export function oddsIn(line: string): number[] {
  return [...line.matchAll(ODDS)].map((m) => +m[1].replace(",", ".")).filter((o) => o >= 1.01 && o <= 60);
}

export function parse(text: string, events: { id: number; home: string; away: string }[]): Proposal[] {
  const lines = text.split(/\n+/).map((l) => l.trim()).filter(Boolean);
  const nl = lines.map(norm);
  const out: Proposal[] = [];
  const used = new Set<number>();
  for (let i = 0; i < lines.length; i++) {
    const win = nl.slice(i, i + 3).join(" ");
    let best: { id: number; score: number } | null = null;
    for (const e of events) {
      const th = toks(e.home), ta = toks(e.away);
      const hh = th.some((t) => win.includes(t)), aa = ta.some((t) => win.includes(t));
      const sc = (hh ? 1 : 0) + (aa ? 1 : 0);
      if (sc === 2 && (!best || sc > best.score)) best = { id: e.id, score: sc };
    }
    if (!best || used.has(best.id)) continue;
    used.add(best.id);
    const block = lines.slice(i, i + 8);
    const all = block.flatMap(oddsIn);
    if (all.length >= 3) {
      out.push({ include: true, event_id: best.id, market: "1x2", selection: "home", line: null, odds: all[0], source: block.join(" / ") });
      out.push({ include: true, event_id: best.id, market: "1x2", selection: "draw", line: null, odds: all[1], source: "" });
      out.push({ include: true, event_id: best.id, market: "1x2", selection: "away", line: null, odds: all[2], source: "" });
    }
    for (const l of block) {
      const n = norm(l);
      const tot = n.match(/(mas|over|menos|under)\s*(de\s*)?(\d[.,]5)/);
      const o = oddsIn(l.replace(/\d[.,]5(?!\d)/, ""));
      if (tot && o.length) {
        const over = tot[1] === "mas" || tot[1] === "over";
        out.push({ include: true, event_id: best.id, market: "total_goals", selection: over ? "over" : "under", line: +tot[3].replace(",", "."), odds: o[0], source: l });
      }
      if (/ambos/.test(n) && o.length >= 1) {
        out.push({ include: true, event_id: best.id, market: "btts", selection: /\bno\b/.test(n) ? "no" : "yes", line: null, odds: o[0], source: l });
      }
    }
  }
  return out;
}

export async function recognize(file: File | Blob, onProgress?: (p: number) => void): Promise<string> {
  const { createWorker } = await import("tesseract.js");
  const worker = await createWorker(["spa", "eng"], 1, {
    logger: (m: any) => { if (m.status === "recognizing text" && onProgress) onProgress(m.progress); },
  });
  try {
    const { data } = await worker.recognize(file);
    return data.text;
  } finally {
    await worker.terminate();
  }
}
