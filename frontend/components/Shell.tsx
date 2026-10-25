"use client";
import {
  Activity, BarChart3, Bot, BrainCircuit, Building2, Calculator, CalendarDays, Gauge, History, Layers,
  LineChart, Menu, Radio, Scale, Search, Settings, ShieldCheck, Sparkles, Trophy, X, Zap, Wallet, Camera, Hourglass, Gift,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { api } from "@/lib/api";

const NAV: { href: string; label: string; icon: ReactNode; group: string }[] = [
  { href: "/", label: "Dashboard", icon: <Gauge size={16} />, group: "Centro" },
  { href: "/partidos", label: "Partidos por día", icon: <CalendarDays size={16} />, group: "Centro" },
  { href: "/directo", label: "En directo", icon: <Radio size={16} />, group: "Centro" },
  { href: "/proximos", label: "Próximos", icon: <Layers size={16} />, group: "Centro" },
  { href: "/ia-apuestas", label: "IA de apuestas (simulada)", icon: <Bot size={16} />, group: "Centro" },
  { href: "/ventaja", label: "Ventaja · Surebets", icon: <Zap size={16} />, group: "Análisis" },
  { href: "/retrasadas", label: "Cuotas retrasadas", icon: <Hourglass size={16} />, group: "Análisis" },
  { href: "/predicciones", label: "Predicciones", icon: <LineChart size={16} />, group: "Análisis" },
  { href: "/comparador", label: "Comparador de cuotas", icon: <Scale size={16} />, group: "Análisis" },
  { href: "/valor", label: "Detector de valor", icon: <Sparkles size={16} />, group: "Análisis" },
  { href: "/deportes", label: "Análisis por deporte", icon: <Trophy size={16} />, group: "Análisis" },
  { href: "/parlay", label: "PARLAY AI · Buscar mi cuota", icon: <Search size={16} />, group: "Combinadas" },
  { href: "/bonos", label: "Bonos y apuestas gratis", icon: <Gift size={16} />, group: "Combinadas" },
  { href: "/calculadora", label: "Calculadora COP", icon: <Calculator size={16} />, group: "Combinadas" },
  { href: "/apuestas", label: "Mis apuestas · CLV", icon: <Wallet size={16} />, group: "Combinadas" },
  { href: "/captura", label: "Cuotas desde foto", icon: <Camera size={16} />, group: "Combinadas" },
  { href: "/asistente", label: "Asistente IA", icon: <Bot size={16} />, group: "Combinadas" },
  { href: "/ia", label: "Inteligencia artificial", icon: <BrainCircuit size={16} />, group: "Modelos" },
  { href: "/rendimiento", label: "Rendimiento de modelos", icon: <Activity size={16} />, group: "Modelos" },
  { href: "/historial", label: "Historial", icon: <History size={16} />, group: "Modelos" },
  { href: "/estadisticas", label: "Estadísticas", icon: <BarChart3 size={16} />, group: "Modelos" },
  { href: "/operadores", label: "Operadores (Coljuegos)", icon: <Building2 size={16} />, group: "Plataforma" },
  { href: "/juego-responsable", label: "Juego responsable", icon: <ShieldCheck size={16} />, group: "Plataforma" },
  { href: "/configuracion", label: "Configuración", icon: <Settings size={16} />, group: "Plataforma" },
  { href: "/privacidad", label: "Privacidad", icon: <ShieldCheck size={16} />, group: "Plataforma" },
];

function AgeGate() {
  const [ok, setOk] = useState(true);
  useEffect(() => {
    try {
      setOk(localStorage.getItem("age_ok") === "1");
    } catch {
      setOk(false);
    }
  }, []);
  if (ok) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-4">
      <div className="card max-w-md">
        <h2 className="text-lg font-semibold">Solo para mayores de 18 años</h2>
        <p className="mt-2 text-sm text-ink-2">
          Esta plataforma ofrece análisis estadístico de mercados deportivos en Colombia. No es una casa de apuestas,
          no garantiza ganancias y no coloca apuestas. Debes ser mayor de edad para continuar.
        </p>
        <div className="mt-4 flex gap-2">
          <button className="btn-primary" onClick={() => { try { localStorage.setItem("age_ok", "1"); } catch { /* */ } setOk(true); }}>
            Soy mayor de 18 años
          </button>
          <a className="btn-ghost" href="https://www.coljuegos.gov.co/">Salir</a>
        </div>
      </div>
    </div>
  );
}

function StatusStrip() {
  const [st, setSt] = useState<any>(null);
  useEffect(() => {
    api("/status").then(setSt).catch(() => setSt(null));
    const id = setInterval(() => api("/status").then(setSt).catch(() => {}), 60000);
    return () => clearInterval(id);
  }, []);
  if (!st) return <span className="text-xs text-ink-muted">Backend sin conexión</span>;
  const p = st.providers;
  const chip = (ok: boolean, label: string) => (
    <span key={label} className="inline-flex items-center gap-1 text-xs text-ink-2">
      <span className={`h-1.5 w-1.5 rounded-full ${ok ? "bg-good" : "bg-ink-muted"}`} />
      {label}{ok ? "" : " (sin clave)"}
    </span>
  );
  return (
    <div className="hidden flex-wrap items-center gap-3 md:flex">
      {chip(p.odds_api_net.configured || !!p.oddspapi?.configured, "Cuotas CO")}
      {chip(p.api_football.configured, "Directo")}
      {chip(!!st.champion_models?.football_ensemble, "Modelo fútbol")}
      <span className="text-xs text-ink-muted num">{st.counts.colombian_quotes} cuotas CO · {st.counts.upcoming} próximos · {st.counts.live} en vivo</span>
    </div>
  );
}

function useAndroidBack() {
  useEffect(() => {
    let remove: (() => void) | undefined;
    (async () => {
      const { Capacitor } = await import("@capacitor/core");
      if (!Capacitor.isNativePlatform()) return;
      const { App } = await import("@capacitor/app");
      const h = await App.addListener("backButton", ({ canGoBack }) => {
        if (canGoBack && window.location.pathname !== "/") window.history.back();
        else App.exitApp();
      });
      remove = () => h.remove();
    })();
    return () => remove?.();
  }, []);
}

function useAlerts() {
  const router = useRouter();
  useEffect(() => {
    let stop: (() => void) | undefined;
    import("@/lib/notify").then(async (m) => { stop = await m.startAlertWatcher((id) => router.push(`/partido?id=${id}`)); });
    return () => stop?.();
  }, [router]);
}

function useAutoSync() {
  useEffect(() => {
    let stop: (() => void) | undefined;
    import("@/lib/sync").then((m) => { stop = m.startAutoSync(); });
    return () => stop?.();
  }, []);
}

function UpdateBanner() {
  const [info, setInfo] = useState<{ available: boolean; url?: string } | null>(null);
  useEffect(() => {
    (async () => {
      const { Capacitor } = await import("@capacitor/core");
      if (!Capacitor.isNativePlatform()) return;
      const m = await import("@/lib/update");
      const r = await m.checkUpdate().catch(() => ({ available: false }));
      setInfo({ ...r, url: m.APK_URL });
    })();
  }, []);
  if (!info?.available) return null;
  return (
    <div className="border-b border-line bg-accent/10 px-4 py-2 text-sm">
      Hay una versión nueva de la app.{" "}
      <a className="font-semibold text-accent underline" href={info.url}>Descargar e instalar</a>
      <span className="text-xs text-ink-muted"> · se instala encima sin perder sus datos</span>
    </div>
  );
}

export default function Shell({ children }: { children: ReactNode }) {
  const path = usePathname();
  const [open, setOpen] = useState(false);
  useAndroidBack();
  useAlerts();
  useAutoSync();
  const groups = Array.from(new Set(NAV.map((n) => n.group)));
  const nav = (
    <nav className="space-y-5 p-3">
      {groups.map((g) => (
        <div key={g}>
          <div className="px-2 pb-1 text-[10px] font-semibold uppercase tracking-widest text-ink-muted">{g}</div>
          {NAV.filter((n) => n.group === g).map((n) => {
            const active = n.href === "/" ? path === "/" : path.startsWith(n.href);
            return (
              <Link key={n.href} href={n.href} onClick={() => setOpen(false)}
                className={`flex items-center gap-2 rounded-lg px-2 py-1.5 text-sm ${active ? "bg-surface-3 text-ink" : "text-ink-2 hover:bg-surface-2"}`}>
                {n.icon} {n.label}
              </Link>
            );
          })}
        </div>
      ))}
    </nav>
  );
  return (
    <div className="flex min-h-screen">
      <AgeGate />
      <aside className="sticky top-0 hidden h-screen w-64 shrink-0 overflow-y-auto border-r border-line bg-surface-1 lg:block">
        <div className="border-b border-line px-4 py-4">
          <div className="text-sm font-semibold">Apuestas Intel <span className="text-accent">CO</span></div>
          <div className="text-[11px] text-ink-muted">Centro de inteligencia deportiva</div>
        </div>
        {nav}
      </aside>
      {open && (
        <div className="fixed inset-0 z-40 bg-black/70 lg:hidden" onClick={() => setOpen(false)}>
          <aside className="h-full w-72 overflow-y-auto bg-surface-1" onClick={(e) => e.stopPropagation()}>
            <div className="flex justify-end p-2"><button className="btn-ghost" onClick={() => setOpen(false)}><X size={16} /></button></div>
            {nav}
          </aside>
        </div>
      )}
      <div className="min-w-0 flex-1">
        <header style={{ paddingTop: "max(0.5rem, env(safe-area-inset-top))" }} className="sticky top-0 z-30 flex items-center justify-between gap-3 border-b border-line bg-page/90 px-4 py-2 backdrop-blur">
          <button className="btn-ghost lg:hidden" onClick={() => setOpen(true)} aria-label="Menú"><Menu size={16} /></button>
          <StatusStrip />
          <span className="text-xs text-ink-muted">+18 · Juego responsable</span>
        </header>
        <UpdateBanner />
        <main className="mx-auto max-w-[1400px] px-4 py-6">{children}</main>
      </div>
    </div>
  );
}
