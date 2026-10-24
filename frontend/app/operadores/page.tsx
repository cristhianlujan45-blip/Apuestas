"use client";
import { Card, ErrorBox, Loading, PageHeader, StatusBadge } from "@/components/ui";
import { useApi } from "@/lib/useApi";

const yn = (v: boolean | null | undefined) => v === true ? "Sí" : v === false ? "No" : "No verificado";

export default function Operators() {
  const { data, error, loading } = useApi("/operators");
  if (loading) return <Loading />;
  if (error) return <ErrorBox error={error} />;
  const auth = data.operators.filter((o: any) => o.status === "authorized");
  const other = data.operators.filter((o: any) => o.status !== "authorized");
  return (
    <div className="space-y-4">
      <PageHeader title="Operadores autorizados en Colombia"
        subtitle={<>Verificado contra el listado oficial de Coljuegos (<a className="text-accent" href={data.source.primary_url} target="_blank" rel="noreferrer">fuente</a>, página modificada el {data.source.primary_page_last_modified}; verificación {data.source.verified_at}). Solo estos operadores se usan para construir combinadas. Ningún operador ofrece API pública oficial: las cuotas llegan por un proveedor con licencia de datos (odds-api.net) o por carga manual.</>} />
      <Card title={`Autorizados (${auth.length})`}>
        <div className="overflow-x-auto"><table className="data min-w-[1000px]">
          <thead><tr><th>Operador</th><th>Razón social</th><th>Dominio</th><th>Contrato</th><th>Plataforma</th><th>API pública</th><th>En vivo</th><th>Combinadas</th><th>Mismo partido</th><th>Formato</th></tr></thead>
          <tbody>{auth.map((o: any) => (
            <tr key={o.key}><td className="font-medium">{o.name}</td><td className="text-ink-2">{o.legal_name}</td><td className="text-xs">{o.domains.join(", ")}</td>
              <td className="num">{o.contract}{o.capabilities.previous_contracts?.filter((c: string) => c !== o.contract).length ? <div className="text-[11px] text-ink-muted">antes {o.capabilities.previous_contracts.join(", ")}</div> : null}</td>
              <td className="text-xs text-ink-2">{o.capabilities.platform_provider || "No verificado"}</td>
              <td>{o.capabilities.official_public_api ? "Sí" : "No"}</td><td>{yn(o.capabilities.live_betting)}</td><td>{yn(o.capabilities.parlays)}</td>
              <td title={o.capabilities.same_event_parlays_note}>{yn(o.capabilities.same_event_parlays)}</td><td>{o.capabilities.odds_format}</td></tr>
          ))}</tbody></table></div>
        <p className="mt-2 text-xs text-ink-muted">{data.source.notes}</p>
      </Card>
      <Card title="No vigentes / solo referencia">
        <table className="data"><tbody>{other.map((o: any) => (
          <tr key={o.key}><td>{o.name}</td><td className="text-ink-2">{o.legal_name}</td>
            <td>{o.status === "reference_only" ? <StatusBadge status="info">Referencia (no autorizado en Colombia)</StatusBadge> : o.status === "pending_verification" ? <StatusBadge status="warning">Pendiente de verificación</StatusBadge> : <StatusBadge status="critical">No aparece en el listado vigente</StatusBadge>}</td></tr>
        ))}</tbody></table>
      </Card>
    </div>
  );
}
