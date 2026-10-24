import type { MetadataRoute } from "next";

// Permite instalar la versión web como app desde el navegador (PWA).
export const dynamic = "force-static";

export default function manifest(): MetadataRoute.Manifest {
  const base = process.env.NEXT_PUBLIC_BASE_PATH || "";
  return {
    name: "Apuestas Intel CO",
    short_name: "Apuestas Intel",
    description: "Inteligencia deportiva, predicciones y PARLAY AI para Colombia",
    start_url: `${base}/`,
    scope: `${base}/`,
    display: "standalone",
    background_color: "#0d0d0d",
    theme_color: "#0d0d0d",
    lang: "es-CO",
    icons: [{ src: `${base}/icon.png`, sizes: "1024x1024", type: "image/png", purpose: "any" }],
  };
}
