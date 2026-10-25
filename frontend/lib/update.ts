/**
 * Aviso de nueva versión de la app Android: compara la hora de compilación con la fecha de la
 * APK publicada en GitHub Releases (consulta como máximo cada 6 horas).
 */
export const APK_URL = "https://github.com/cristhianlujan45-blip/Apuestas/releases/download/app-latest/apuestas-intel-co.apk";
const RELEASE_API = "https://api.github.com/repos/cristhianlujan45-blip/Apuestas/releases/tags/app-latest";
// La APK se sube unos minutos después de compilarse: margen para no avisar de la propia versión.
const MARGIN_MS = 30 * 60e3;

export async function checkUpdate(): Promise<{ available: boolean; published_at?: string }> {
  const built = process.env.NEXT_PUBLIC_BUILD_TIME;
  if (!built) return { available: false };
  let published: string | null = null;
  try {
    const c = JSON.parse(localStorage.getItem("update_check") || "null");
    if (c && Date.now() - c.t < 6 * 3600e3) published = c.published;
  } catch { /* */ }
  if (!published) {
    const r = await fetch(RELEASE_API, { headers: { Accept: "application/vnd.github+json" } });
    if (!r.ok) return { available: false };
    const rel = await r.json();
    published = (rel.assets || []).find((a: any) => a.name === "apuestas-intel-co.apk")?.updated_at || null;
    try { localStorage.setItem("update_check", JSON.stringify({ t: Date.now(), published })); } catch { /* */ }
  }
  if (!published) return { available: false };
  return { available: new Date(published).getTime() - new Date(built).getTime() > MARGIN_MS, published_at: published };
}
