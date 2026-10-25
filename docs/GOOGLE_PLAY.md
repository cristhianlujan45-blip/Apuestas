# Publicar en Google Play

El flujo `.github/workflows/android.yml` compila el `.aab` firmado cuando existen los secretos
`ANDROID_KEYSTORE_BASE64`, `ANDROID_KEYSTORE_PASSWORD` y `ANDROID_KEY_ALIAS`. El archivo queda en
<https://github.com/cristhianlujan45-blip/Apuestas/releases/tag/app-latest> como `apuestas-intel-co.aab`.

## Pasos

1. Cree una cuenta de desarrollador en <https://play.google.com/console> (pago único de USD 25 y
   verificación de identidad).
2. **Crear app** → nombre «Apuestas Intel CO», idioma español (Colombia), tipo *App*, *Gratis*.
3. **Firma de apps de Google Play:** acepte la firma administrada por Google. Su `.jks` queda como
   *clave de subida*: guárdelo; sin él no podrá subir actualizaciones.
4. **Política de privacidad:** <https://cristhianlujan45-blip.github.io/Apuestas/privacidad/>
5. **Contenido de la app:**
   - Público objetivo: 18 años o más.
   - Anuncios: no contiene.
   - Acceso a la app: no requiere inicio de sesión.
   - Seguridad de los datos: no recopila ni comparte datos. Todo queda en el dispositivo; la
     sincronización opcional va a la cuenta de GitHub del propio usuario.
   - Categoría: *Deportes*.
6. **Apuestas y juegos de azar:**
   - La app **no** ofrece juegos con dinero real: no acepta apuestas, no procesa pagos y no
     enlaza a registro en casas.
   - Declárelo así en el cuestionario de clasificación de contenido («simulated gambling: no»;
     «real-money gambling: no»).
   - Google puede pedir más información sobre apps relacionadas con apuestas: responda que es una
     herramienta de análisis estadístico.
   - Mantenga los avisos de +18 y juego responsable.
7. **Ficha de Play Store:** use los textos de abajo y capturas de la app (mínimo 2, 1080×1920).
8. **Versiones → Pruebas internas** → subir `apuestas-intel-co.aab` → revisar y publicar. Cuando
   funcione, promuévala a *Producción*.

Cada compilación aumenta `versionCode` (100 + número de ejecución del flujo), requisito de Play
para aceptar una actualización.

## Textos de la ficha

**Descripción breve (80 caracteres):**
Análisis estadístico de fútbol, cuotas colombianas y combinadas. +18.

**Descripción completa:**

Apuestas Intel CO analiza partidos de fútbol con modelos estadísticos validados con miles de
partidos reales.
- Compara las cuotas de las casas autorizadas por Coljuegos.
- Detecta cuotas retrasadas frente al mercado internacional.
- Arma combinadas con la cuota que usted busca (PARLAY AI).

Funciones:
- Probabilidades por partido: 1X2, goles, ambos marcan, córners y tarjetas.
- Detector de valor y de cuotas retrasadas.
- PARLAY AI «Buscar mi cuota» con validación completa.
- Calculadora de bonos y apuestas gratis.
- Cuotas desde una foto (reconocimiento en el dispositivo).
- Registro de apuestas con CLV, banca y límites personales.

La app no es una casa de apuestas, no coloca apuestas ni mueve dinero, y no garantiza ganancias.
Solo para mayores de 18 años. Juegue con responsabilidad.
