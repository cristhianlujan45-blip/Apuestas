import { Card, PageHeader } from "@/components/ui";

export const metadata = { title: "Política de privacidad · Apuestas Intel CO" };

export default function Privacy() {
  return (
    <div className="space-y-4">
      <PageHeader title="Política de privacidad" subtitle="Apuestas Intel CO · última actualización: 25 de octubre de 2026" />
      <Card>
        <div className="space-y-3 text-sm text-ink-2">
          <p><b>Qué es la app.</b> Una herramienta de análisis estadístico de mercados deportivos para mayores de 18 años en Colombia. No es una casa de apuestas, no coloca apuestas, no mueve dinero y no pide datos de pago.</p>
          <p><b>Datos que guarda.</b> Sus cuotas cargadas, apuestas registradas, combinadas, límites de juego, banca y ajustes se guardan solo en su dispositivo. La app no tiene cuentas de usuario ni envía esos datos a servidores propios.</p>
          <p><b>Fotos.</b> Las capturas que usa en «Cuotas desde foto» se procesan en el propio dispositivo y no se suben a ningún servidor.</p>
          <p><b>Servicios externos.</b> La app descarga datos públicos (partidos, cuotas y predicciones) desde GitHub (raw.githubusercontent.com y api.github.com). Si usted activa la sincronización, sus datos se guardan en un Gist secreto de su propia cuenta de GitHub con el token que usted crea; el token queda solo en su dispositivo. Si configura un servidor propio, la app se conecta a la dirección que usted indique.</p>
          <p><b>Notificaciones.</b> Las alertas se generan en el dispositivo. Las alertas push opcionales usan ntfy.sh con un tema que usted elige.</p>
          <p><b>Lo que nunca hace.</b> No pide ni guarda contraseñas de casas de apuestas, no usa publicidad, no vende datos y no hace seguimiento entre apps.</p>
          <p><b>Borrar sus datos.</b> Desinstale la app o borre los datos de la app en los ajustes de Android. Si usó la sincronización, borre el Gist desde su cuenta de GitHub.</p>
          <p><b>Juego responsable.</b> Línea de ayuda y recursos en la sección «Juego responsable». Las apuestas implican riesgo de pérdida.</p>
          <p><b>Contacto.</b> A través del repositorio del proyecto en GitHub (cristhianlujan45-blip/Apuestas).</p>
        </div>
      </Card>
    </div>
  );
}
