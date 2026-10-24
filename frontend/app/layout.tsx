import type { Metadata, Viewport } from "next";
import Shell from "@/components/Shell";
import "./globals.css";

export const metadata: Metadata = {
  title: "Apuestas Intel CO",
  description: "Inteligencia deportiva, predicciones y PARLAY AI para el mercado colombiano",
};

export const viewport: Viewport = { width: "device-width", initialScale: 1, viewportFit: "cover", themeColor: "#0d0d0d" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="es-CO">
      <body>
        <Shell>{children}</Shell>
      </body>
    </html>
  );
}
