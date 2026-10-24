export const cop = (v: number | null | undefined) =>
  v == null || Number.isNaN(v) ? "—" : `$${Math.round(v).toLocaleString("es-CO")}`;

export const pct = (v: number | null | undefined, d = 1) =>
  v == null || Number.isNaN(v) ? "—" : `${(v * 100).toFixed(d)} %`;

export const signedPct = (v: number | null | undefined, d = 1) =>
  v == null || Number.isNaN(v) ? "—" : `${v >= 0 ? "+" : ""}${(v * 100).toFixed(d)} %`;

export const odds = (v: number | null | undefined) => (v == null ? "—" : v.toFixed(2));

export const num = (v: number | null | undefined, d = 3) => (v == null ? "—" : v.toFixed(d));

export const bogota = (iso: string | null | undefined, withDate = true) => {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString("es-CO", {
    timeZone: "America/Bogota",
    ...(withDate ? { day: "2-digit", month: "short" } : {}),
    hour: "2-digit",
    minute: "2-digit",
  });
};

export const ago = (iso: string | null | undefined) => {
  if (!iso) return "—";
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 60) return `hace ${Math.round(s)} s`;
  if (s < 3600) return `hace ${Math.round(s / 60)} min`;
  if (s < 86400) return `hace ${Math.round(s / 3600)} h`;
  return `hace ${Math.round(s / 86400)} d`;
};

export const SPORT_LABEL: Record<string, string> = {
  football: "Fútbol", basketball: "Baloncesto", tennis: "Tenis", baseball: "Béisbol", volleyball: "Voleibol",
};

// Paleta categórica validada (modo oscuro), en orden fijo — nunca cíclica.
export const SERIES = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"];
