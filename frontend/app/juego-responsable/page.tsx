"use client";
import { Card, Loading, PageHeader } from "@/components/ui";
import { useApi } from "@/lib/useApi";

export default function Responsible() {
  const { data } = useApi("/responsible-gaming");
  if (!data) return <Loading />;
  return (
    <div className="space-y-4">
      <PageHeader title="Juego responsable" subtitle={`Uso exclusivo para mayores de ${data.min_age} años. Esta es una herramienta de análisis, no una casa de apuestas.`} />
      <Card title="Principios"><ul className="list-disc space-y-1 pl-5 text-sm text-ink-2">{data.principles.map((p: string) => <li key={p}>{p}</li>)}</ul></Card>
      <Card title="Herramientas personales">
        <p className="text-sm text-ink-2">En Configuración puede fijar límites diarios, semanales y mensuales de gasto (en COP), un tiempo máximo de sesión y la autoexclusión. Las reducciones se aplican al instante; los aumentos, después de 24 horas. La autoexclusión no puede acortarse.</p>
      </Card>
      <Card title="Ayuda y denuncias">
        <ul className="space-y-1 text-sm">{data.resources.map((r: any) => <li key={r.name}>{r.name}: {r.url ? <a className="text-accent" href={r.url} target="_blank" rel="noreferrer">{r.url}</a> : r.phone || r.email}</li>)}</ul>
      </Card>
    </div>
  );
}
