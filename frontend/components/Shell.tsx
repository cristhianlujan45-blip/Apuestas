"use client";
import {
  Activity, BarChart3, Bot, BrainCircuit, Building2, Calculator, CalendarDays, Gauge, History, Layers,
  LineChart, Menu, Radio, Scale, Search, Settings, ShieldCheck, Sparkles, Trophy, X, Zap, Wallet, Camera, Hourglass, Gift,
  Home, Lock, MessageCircle,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { api } from "@/lib/api";

type NavItem = { href: string; label: string; icon: ReactNode; group: string; desc?: string };
const NAV: NavItem[] = [
  { href: "/", label: "Inicio", icon: <Home size={18} />, group: "Empezar", desc: "Resumen y accesos rápidos" },
  { href: "/partidos", label: "Partidos por día", icon: <CalendarDays size={18} />, group: "Empezar", desc: "Elija el día y vea probabilidades" },
  { href: "/directo", label: "En directo", icon: <Radio size={18} />, group: "Empezar", desc: "Partidos que se están jugando" },
  { href: "/parlay", label: "Buscar mi cuota (PARLAY)", icon: <Search size={18} />, group: "Apostar mejor", desc: "Combinadas para la cuota que quiere" },
  { href: "/ia-apuestas", label: "IA de apuestas", icon: <Bot size={18} />, group: "Apostar mejor", desc: "Recomendaciones que se evalúan solas" },
  { href: "/retrasadas", label: "Cuotas retrasadas", icon: <Hourglass size={18} />, group: "Apostar mejor", desc: "Casas que pagan más de lo justo" },
  { href: "/valor", label: "Detector de valor", icon: <Sparkles size={18} />, group: "Apostar mejor", desc: "Cuotas por encima del modelo" },
  { href: "/ventaja", label: "Surebets", icon: <Zap size={18} />, group: "Apostar mejor", desc: "Ganancia segura entre casas" },
  { href: "/bonos", label: "Bonos y apuestas gratis", icon: <Gift size={18} />, group: "Apostar mejor", desc: "Convierta promociones en saldo" },
  { href: "/comparador", label: "Comparador de cuotas", icon: <Scale size={18} />, group: "Apostar mejor", desc: "Qué casa paga más" },
  { href: "/apuestas", label: "Mis apuestas", icon: <Wallet size={18} />, group: "Mis herramientas", desc: "Registro, ganancias y CLV" },
  { href: "/captura", label: "Cuotas desde foto", icon: <Camera size={18} />, group: "Mis herramientas", desc: "Lea las cuotas de una captura" },
  { href: "/calculadora", label: "Calculadora COP", icon: <Calculator size={18} />, group: "Mis herramientas", desc: "Retorno y cuota necesaria" },
  { href: "/asistente", label: "Asistente", icon: <MessageCircle size={18} />, group: "Mis herramientas", desc: "Pregunte en español" },
  { href: "/predicciones", label: "Predicciones", icon: <LineChart size={18} />, group: "Datos y modelos", desc: "Registro sellado antes del partido" },
  { href: "/estadisticas", label: "Estadísticas de equipos", icon: <BarChart3 size={18} />, group: "Datos y modelos", desc: "Últimos partidos de un equipo" },
  { href: "/deportes", label: "Análisis por deporte", icon: <Trophy size={18} />, group: "Datos y modelos", desc: "Modelos de cada deporte" },
  { href: "/rendimiento", label: "Rendimiento real", icon: <Activity size={18} />, group: "Datos y modelos", desc: "Aciertos con partidos jugados" },
  { href: "/ia", label: "Cómo funciona el modelo", icon: <BrainCircuit size={18} />, group: "Datos y modelos", desc: "Validación y comparación" },
  { href: "/historial", label: "Historial de combinadas", icon: <History size={18} />, group: "Datos y modelos", desc: "Combinadas generadas" },
  { href: "/configuracion", label: "Configuración", icon: <Settings size={18} />, group: "Cuenta y ayuda", desc: "Banca, alertas, sincronización" },
  { href: "/operadores", label: "Casas autorizadas", icon: <Building2 size={18} />, group: "Cuenta y ayuda", desc: "Registro de Coljuegos" },
  { href: "/juego-responsable", label: "Juego responsable", icon: <ShieldCheck size={18} />, group: "Cuenta y ayuda", desc: "Límites y ayuda" },
  { href: "/privacidad", label: "Privacidad", icon: <Lock size={18} />, group: "Cuenta y ayuda" },
];
// Barra inferior del celular: lo que más se usa, a un toque
const TABS: { href: string; label: string; icon: ReactNode }[] = [
  { href: "/", label: "Inicio", icon: <Home size={20} /> },
  { href: "/partidos", label: "Partidos", icon: <CalendarDays size={20} /> },
  { href: "/parlay", label: "Mi cuota", icon: <Search size={20} /> },
  { href: "/ia-apuestas", label: "IA", icon: <Bot size={20} /> },
];
const isActive = (path: string, href: string) => (href === "/" ? path === "/" : path.startsWith(href));

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
  const current = NAV.find((n) => isActive(path, n.href) && n.href !== "/") || (path === "/" ? NAV[0]
    : path.startsWith("/partido") ? { label: "Partido" } : null);
  useEffect(() => { setOpen(false); }, [path]);
  const nav = (compact: boolean) => (
    <nav className="space-y-5 p-3">
      {groups.map((g) => (
        <div key={g}>
          <div className="px-2 pb-1 text-[11px] font-semibold uppercase tracking-widest text-ink-muted">{g}</div>
          {NAV.filter((n) => n.group === g).map((n) => {
            const active = isActive(path, n.href);
            return (
              <Link key={n.href} href={n.href} onClick={() => setOpen(false)}
                className={`flex items-center gap-3 rounded-lg px-2 ${compact ? "py-1.5" : "py-2.5"} text-sm ${active ? "bg-surface-3 text-ink" : "text-ink-2 hover:bg-surface-2"}`}>
                <span className={active ? "text-accent" : "text-ink-muted"}>{n.icon}</span>
                <span className="min-w-0">
                  <span className="block leading-tight">{n.label}</span>
                  {!compact && n.desc && <span className="block text-[11px] leading-tight text-ink-muted">{n.desc}</span>}
                </span>
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
        <Link href="/" className="block border-b border-line px-4 py-4">
          <div className="text-sm font-semibold">Apuestas Intel <span className="text-accent">CO</span></div>
          <div className="text-[11px] text-ink-muted">Análisis deportivo · +18</div>
        </Link>
        {nav(true)}
      </aside>
      {open && (
        <div className="fixed inset-0 z-50 bg-black/70 lg:hidden" onClick={() => setOpen(false)}>
          <aside className="h-full w-[86vw] max-w-sm overflow-y-auto bg-surface-1 pb-24" onClick={(e) => e.stopPropagation()}
            style={{ paddingTop: "env(safe-area-inset-top)" }}>
            <div className="flex items-center justify-between border-b border-line px-4 py-3">
              <div className="text-sm font-semibold">Apuestas Intel <span className="text-accent">CO</span></div>
              <button className="btn-ghost px-2" onClick={() => setOpen(false)} aria-label="Cerrar menú"><X size={18} /></button>
            </div>
            {nav(false)}
          </aside>
        </div>
      )}
      <div className="min-w-0 flex-1">
        <header style={{ paddingTop: "max(0.5rem, env(safe-area-inset-top))" }} className="sticky top-0 z-30 flex items-center justify-between gap-3 border-b border-line bg-page/90 px-4 py-2 backdrop-blur">
          <button className="btn-ghost px-2 lg:hidden" onClick={() => setOpen(true)} aria-label="Menú"><Menu size={18} /></button>
          <span className="min-w-0 flex-1 truncate text-sm font-medium lg:hidden">{current?.label || "Apuestas Intel CO"}</span>
          <div className="hidden min-w-0 flex-1 lg:block"><StatusStrip /></div>
          <span className="shrink-0 rounded-md border border-line-strong px-1.5 py-0.5 text-[11px] text-ink-muted">+18</span>
        </header>
        <UpdateBanner />
        <main className="mx-auto max-w-[1400px] px-4 pb-28 pt-5 lg:pb-8">{children}</main>
      </div>
      <nav className="fixed inset-x-0 bottom-0 z-40 grid grid-cols-5 border-t border-line bg-surface-1/95 backdrop-blur lg:hidden"
        style={{ paddingBottom: "env(safe-area-inset-bottom)" }} aria-label="Navegación principal">
        {TABS.map((t) => {
          const active = isActive(path, t.href);
          return (
            <Link key={t.href} href={t.href} className={`flex flex-col items-center gap-0.5 py-2 text-[11px] ${active ? "text-accent" : "text-ink-muted"}`}>
              {t.icon}<span>{t.label}</span>
            </Link>
          );
        })}
        <button onClick={() => setOpen(true)} className="flex flex-col items-center gap-0.5 py-2 text-[11px] text-ink-muted"><Menu size={20} /><span>Más</span></button>
      </nav>
    </div>
  );
}
