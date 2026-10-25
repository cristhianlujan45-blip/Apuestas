"use client";
import { Ticket } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { loadSlip } from "@/lib/slip";

/** Botón flotante con el número de selecciones del boleto. */
export default function SlipButton() {
  const [n, setN] = useState(0);
  const path = usePathname();
  useEffect(() => {
    const f = () => setN(loadSlip().length);
    f();
    window.addEventListener("slip", f);
    window.addEventListener("storage", f);
    return () => { window.removeEventListener("slip", f); window.removeEventListener("storage", f); };
  }, []);
  if (!n || path.startsWith("/boleto")) return null;
  return (
    <Link href="/boleto" style={{ bottom: "calc(4.5rem + env(safe-area-inset-bottom))" }}
      className="fixed right-4 z-40 flex items-center gap-2 rounded-full bg-accent px-4 py-3 text-sm font-semibold text-white shadow-lg lg:bottom-6">
      <Ticket size={18} /> Mi boleto · {n}
    </Link>
  );
}
