"use client";
import { AlertTriangle, CheckCircle2, Info, Loader2, XCircle } from "lucide-react";
import type { ReactNode } from "react";
import { pct } from "@/lib/format";

export function Card({ title, right, children, className = "" }: {
  title?: ReactNode; right?: ReactNode; children: ReactNode; className?: string;
}) {
  return (
    <section className={`card ${className}`}>
      {(title || right) && (
        <header className="mb-3 flex items-center justify-between gap-2">
          {title && <h2 className="card-title">{title}</h2>}
          {right}
        </header>
      )}
      {children}
    </section>
  );
}

export function PageHeader({ title, subtitle, right }: { title: string; subtitle?: ReactNode; right?: ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
        {subtitle && <p className="mt-1 max-w-3xl text-sm text-ink-2">{subtitle}</p>}
      </div>
      {right}
    </div>
  );
}

export function Stat({ label, value, hint }: { label: string; value: ReactNode; hint?: ReactNode }) {
  return (
    <div className="card">
      <div className="card-title">{label}</div>
      <div className="mt-2 text-2xl font-semibold">{value}</div>
      {hint && <div className="mt-1 text-xs text-ink-muted">{hint}</div>}
    </div>
  );
}

type Status = "good" | "warning" | "serious" | "critical" | "info";
const STATUS_STYLE: Record<Status, string> = {
  good: "border-good/40 text-good",
  warning: "border-warning/40 text-warning",
  serious: "border-serious/40 text-serious",
  critical: "border-critical/50 text-critical",
  info: "border-line-strong text-ink-2",
};
const STATUS_ICON: Record<Status, ReactNode> = {
  good: <CheckCircle2 size={14} />, warning: <AlertTriangle size={14} />, serious: <AlertTriangle size={14} />,
  critical: <XCircle size={14} />, info: <Info size={14} />,
};

/** Estado con icono + texto: el color nunca transmite el significado solo. */
export function StatusBadge({ status, children }: { status: Status; children: ReactNode }) {
  return (
    <span className={`inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-xs ${STATUS_STYLE[status]}`}>
      {STATUS_ICON[status]}
      <span className="text-ink-2">{children}</span>
    </span>
  );
}

export function Badge({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <span className={`rounded-md bg-surface-3 px-2 py-0.5 text-xs text-ink-2 ${className}`}>{children}</span>;
}

export function Loading({ label = "Cargando…" }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 py-6 text-sm text-ink-muted">
      <Loader2 className="animate-spin" size={16} /> {label}
    </div>
  );
}

export function ErrorBox({ error }: { error: unknown }) {
  if (!error) return null;
  const e = error as { message?: string; detail?: unknown };
  const detail = e.detail && typeof e.detail === "object" ? (e.detail as { message?: string }).message : null;
  return (
    <div className="rounded-lg border border-critical/40 bg-critical/10 p-3 text-sm">
      <StatusBadge status="critical">Error</StatusBadge>
      <p className="mt-2 text-ink-2">{detail || e.message || String(error)}</p>
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="rounded-lg border border-dashed border-line-strong p-6 text-center text-sm text-ink-muted">{children}</div>;
}

/** Barra apilada L/E/V con etiquetas directas y separación de 2 px. */
export function ProbBar({ probs, labels }: { probs: { home: number; draw?: number; away: number }; labels?: [string, string, string] }) {
  const parts = [
    { k: "home", v: probs.home, c: "#3987e5", l: labels?.[0] ?? "L" },
    ...(probs.draw != null && probs.draw > 0 ? [{ k: "draw", v: probs.draw, c: "#898781", l: labels?.[1] ?? "E" }] : []),
    { k: "away", v: probs.away, c: "#d95926", l: labels?.[2] ?? "V" },
  ];
  return (
    <div className="w-full" role="img" aria-label={parts.map((p) => `${p.l} ${pct(p.v)}`).join(", ")}>
      <div className="flex h-2.5 w-full gap-[2px] overflow-hidden rounded">
        {parts.map((p) => (
          <div key={p.k} style={{ width: `${p.v * 100}%`, background: p.c }} title={`${p.l}: ${pct(p.v)}`} />
        ))}
      </div>
      <div className="mt-1 flex justify-between text-[11px] text-ink-2 num">
        {parts.map((p) => (
          <span key={p.k}>
            <span className="inline-block h-2 w-2 rounded-sm align-middle" style={{ background: p.c }} /> {p.l} {pct(p.v, 0)}
          </span>
        ))}
      </div>
    </div>
  );
}

export function Disclaimer() {
  return (
    <p className="text-xs text-ink-muted">
      Estimaciones estadísticas, no garantías. +18. Juega con responsabilidad. La plataforma no coloca apuestas ni mueve dinero.
    </p>
  );
}
