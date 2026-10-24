import type { Metadata } from "next";
import Shell from "@/components/Shell";
import "./globals.css";

export const metadata: Metadata = {
  title: "Apuestas Intel CO",
  description: "Inteligencia deportiva, predicciones y PARLAY AI para el mercado colombiano",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="es-CO">
      <body>
        <Shell>{children}</Shell>
      </body>
    </html>
  );
}
