# Apuestas Intel CO

Plataforma de inteligencia deportiva para el mercado colombiano. Reúne predicciones estadísticas, comparación de
cuotas y **PARLAY AI**, un optimizador de combinadas con la función **BUSCAR MI CUOTA**.

> Herramienta de análisis y apoyo a decisiones. **No garantiza ganancias, no coloca apuestas y no mueve dinero.**
> Uso exclusivo para mayores de 18 años. Solo trabaja con operadores autorizados por Coljuegos.

## Qué hace

| Módulo | Descripción |
|---|---|
| Operadores (Coljuegos) | Registro verificado de los 14 operadores vigentes. Se reverifica cada semana contra la página oficial y genera alertas si un operador desaparece. |
| Comparador de cuotas | Mejor cuota por selección, operador que la ofrece, diferencia entre casas, margen de cada operador, evolución temporal y hora de consulta. |
| Motor predictivo | Poisson, Dixon-Coles bayesiano, Poisson bivariado, Elo, Glicko-2, LogReg, Random Forest, LightGBM, XGBoost, CatBoost y MLP (PyTorch), combinados en un ensemble validado en el tiempo. |
| Otros deportes | Baloncesto (ORtg/DRtg, pace, Four Factors, props de jugador), tenis (Elo por superficie + Markov saque/resto), béisbol y voleibol. |
| Directo | Actualización bayesiana con minuto, marcador, expulsiones y xG o tiros. Se emite por WebSocket. |
| Monte Carlo | Miles de escenarios por evento: distribuciones, intervalos de incertidumbre (aleatoria y de parámetros) y mercados conjuntos. |
| Detector de valor | Probabilidad implícita, margen, probabilidad propia, cuota justa, EV y Kelly fraccional. |
| PARLAY AI / BUSCAR MI CUOTA | Mochila por grupos exacta en log-cuotas. Genera los Parlays **A** (mayor probabilidad), **B** (equilibrio), **C** (mejor EV) y **D** (menos selecciones), siempre por operador, y los compara entre casas. |
| Validación de combinadas | Encuentros confirmados, cuotas vigentes, duplicados, contradicciones, correlación del mismo partido, reglas del operador, cálculo de la cuota y suficiencia de datos. |
| Calculadora COP | Retorno, ganancia, cuota necesaria (buscador inverso), inversión necesaria y control de capital. |
| Historial y aprendizaje | Predicciones inmutables encadenadas por hash (y bloqueadas por trigger en PostgreSQL), con Brier, log loss, RPS, calibración, MAE/RMSE, ROI, detección de degradación, versionado y reentrenamiento controlado. |
| Asistente IA | Con `ANTHROPIC_API_KEY` usa Claude con herramientas de la plataforma; sin clave, un enrutador local en español. Los números siempre salen de los modelos. |
| IA de apuestas (simulada) | Agente que aprende con validación walk-forward la regla que gana a largo plazo (mejor cuota frente al precio justo de Pinnacle), recomienda antes de cada partido, apuesta en simulado con banca virtual y sella cada recomendación. Después compara lo que predijo con lo que pasó y endurece la regla si su CLV real es negativo. **No coloca apuestas reales.** |
| Cuotas retrasadas | Compara cada cuota colombiana con el precio justo de Pinnacle o del consenso internacional. La marca *retrasada* cuando la referencia se movió después del último cambio de la casa. |
| Bonos y apuestas gratis | Convierte apuestas gratis y de calificación en saldo cubriendo el resultado contrario en otra casa; busca la mejor cobertura con las cuotas disponibles. |
| Córners y tarjetas | Modelo de fuerza por equipo (binomial negativa) con cuota justa por línea en la ficha del partido; las cuotas de córners y tarjetas se valoran como las de goles. |
| Banca | Importe sugerido por oportunidad: Kelly fraccional con tope por apuesta, a partir de su banca y de sus apuestas liquidadas. |
| Mis apuestas · CLV | Registro de lo apostado (desde PARLAY AI, Valor o a mano). Se liquida con los resultados reales y mide el CLV contra el cierre de Pinnacle sin margen. |
| Cuotas desde foto | OCR en el propio teléfono (tesseract.js): detecta partido, 1X2, totales y ambos marcan en una captura de su casa. Usted revisa antes de guardar. |
| Alertas | Surebets y apuestas de valor: notificación local en la app y push al teléfono con [ntfy](https://ntfy.sh) desde el pipeline. |
| Bajas | Con `API_FOOTBALL_KEY`, las lesiones y sanciones recortan el ataque esperado según el peso del jugador en los goles del equipo. |
| Copia y sincronización | Exporta e importa un archivo, o sincroniza solo entre celular y web con un Gist secreto de su cuenta de GitHub. |
| Actualizaciones | La app Android avisa cuando hay una APK nueva. |
| Juego responsable | Verificación de mayoría de edad, límites de gasto y de sesión (los aumentos se aplican tras 24 h), autoexclusión y recursos de ayuda. |

## App Android (APK)

- **Descarga:** <https://github.com/cristhianlujan45-blip/Apuestas/releases/download/app-latest/apuestas-intel-co.apk>
  (se recompila sola con cada cambio en `frontend/`).
- **Funciona sin servidor:**
  - El flujo `.github/workflows/datos.yml` corre cada 30 minutos: ingiere datos, ejecuta los modelos, registra
    predicciones y publica los JSON en la rama `datos`.
  - La app los descarga y calcula en el teléfono PARLAY AI, el valor esperado, los surebets y la calculadora.
- **Cuotas colombianas:**
  - Gratis: con el secreto `ODDSPAPI_KEY` (cuenta gratuita en <https://oddspapi.io>) llegan BetPlay y Rushbet. Como
    el plan gratuito da 250 peticiones al mes, se consultan cada 8 horas.
  - De pago: con `ODDS_API_NET_KEY` llegan los 14 operadores.
  - Sin claves: copie las cuotas en Configuración → Mis cuotas, o hágales una captura y use *Cuotas desde foto*.
- **Alertas al teléfono:**
  - Instale la app ntfy y suscríbase a un tema difícil de adivinar.
  - Guarde ese tema en el secreto `NTFY_TOPIC`.
- **Secretos del repositorio** (Settings → Secrets and variables → Actions):
  - datos: `ODDSPAPI_KEY`, `ODDS_API_NET_KEY`, `API_FOOTBALL_KEY`, `API_BASKETBALL_KEY`, `NTFY_TOPIC`;
  - firma: `ANDROID_KEYSTORE_BASE64`, `ANDROID_KEYSTORE_PASSWORD`, `ANDROID_KEY_ALIAS`.
- **Firma y Google Play:**
  - Con los secretos de firma, el flujo compila un APK firmado con su propia clave y un `.aab` para Google Play.
  - Sin ellos, compila un APK de depuración.
  - Para pasar de la versión de depuración a la firmada hay que desinstalar la app una vez.
  - Guarde el `.jks` fuera del repositorio: sin él no podrá publicar actualizaciones en Play.
  - Pasos y textos de la ficha: [`docs/GOOGLE_PLAY.md`](docs/GOOGLE_PLAY.md). Política de privacidad:
    <https://cristhianlujan45-blip.github.io/Apuestas/privacidad/>.
- **Directo real con servidor:** ver [`docs/DESPLIEGUE.md`](docs/DESPLIEGUE.md) (Render o VPS). Después, en
  Configuración → Servidor en vivo, pegue la URL del servidor.
- **Compilación local:**
  ```bash
  cd frontend && npm run build:mobile && npx cap sync android
  cd android && ./gradlew assembleDebug
  ```

## Cómo busca ventaja frente a las casas

1. **Surebets (arbitraje):**
   - Si la suma de 1/cuota de todas las salidas (cada una en la casa que más paga) es menor que 1, la sección
     *Ventaja* calcula cuánto apostar en cada casa para asegurar el mismo retorno.
2. **Valor esperado:**
   - La validación con miles de partidos reales muestra que el precio de mercado sin margen y el ensemble predicen
     casi igual, y mejor que cualquier modelo aislado.
   - La ventaja está en encontrar cuotas colombianas **por encima** de esa probabilidad justa.
3. **Cuotas retrasadas:**
   - Pinnacle viaja gratis en la misma consulta de OddsPapi que BetPlay y Rushbet.
   - Cuando una casa colombiana paga más que el precio justo de Pinnacle, la sección *Cuotas
     retrasadas* lo avisa, también por notificación.
   - No depende de ningún modelo propio.
4. **Bonos:** las apuestas gratis de las casas se convierten en saldo cubriendo el resultado contrario
   en otra casa (sección *Bonos y apuestas gratis*).
5. **Mejor precio:** para cada selección se muestra la casa que más paga; en combinadas la diferencia
   se multiplica.

Lo que dicen las validaciones con datos reales:
- En 1X2 y en más/menos 2.5, el precio de mercado sin margen predice tan bien o mejor que los
  modelos.
  - Por eso la matriz de goles se ajusta a la cuota de más/menos del mercado. El peso lo elige la
    validación; hoy es casi todo mercado.
  - Las señales de valor salen de diferencias de precio entre casas, no de que el modelo «sepa más».
- En córners y tarjetas el modelo por equipo mejora un 6 % la desviación frente a la media de la
  liga en córners por equipo. En el total de córners queda prácticamente igual que la media.

Ninguna de estas estrategias garantiza ganancias:
- las cuotas cambian;
- las casas pueden anular cuotas erróneas y limitar cuentas ganadoras.

## Arquitectura

```
frontend (Next.js 15 + TypeScript + Tailwind + Recharts)
   │  /api/* (rewrite)          ws://…/ws/live
   ▼
backend  FastAPI (REST + WebSocket) ──── Redis (pub/sub en directo, caché)
   │        │
   │        └── engine/   modelos matemáticos y de ML (sin estado)
   │        └── services/ ingesta, predicción, comparador, PARLAY AI, historial, asistente, auth
   ▼
PostgreSQL + TimescaleDB  (odds_quotes como hypertable; predictions de solo inserción)
   ▲
worker  APScheduler: ingesta pre-partido y en directo, registro de predicciones,
        liquidación, verificación de Coljuegos, reentrenamiento semanal
```

**Extensible sin reconstruir:**
- **Operador nuevo:** una entrada en `data/operators/coljuegos_registry.json` o `POST /api/operators`.
- **Proveedor nuevo:** un adaptador en `backend/app/providers/` que devuelva `ProviderEvent` / `ProviderQuote`.
- **Deporte o mercado nuevo:** un modelo que produzca `Outcomes` (`engine/markets.py`). La liquidación, el
  comparador, el valor y PARLAY AI funcionan sin cambios.

## Puesta en marcha

### Docker (producción)

```bash
cp .env.example .env        # complete JWT_SECRET y las claves que tenga
docker compose up -d --build
# Frontend: http://localhost:3000   API: http://localhost:8000/docs
```

El *worker* hace el entrenamiento inicial y luego mantiene los datos al día.

### Desarrollo local

```bash
python3 -m venv .venv && .venv/bin/pip install -r backend/requirements.txt
.venv/bin/pip install torch --index-url https://download.pytorch.org/whl/cpu
cd backend
../.venv/bin/python -m app.cli init
../.venv/bin/python -m app.cli ingest-fixtures       # próximos partidos (football-data.co.uk)
../.venv/bin/python -m app.cli train-football        # validación walk-forward + entrenamiento
../.venv/bin/python -m app.cli record-predictions
../.venv/bin/uvicorn app.main:app --reload --port 8000
# en otra terminal
cd frontend && npm install && npm run dev
```

Sin `DATABASE_URL` se usa SQLite en `data/apuestas.db`.

### Pruebas

```bash
cd backend && ../.venv/bin/python -m pytest -q
# contra PostgreSQL:
TEST_DATABASE_URL=postgresql+psycopg://user@host/db ../.venv/bin/python -m pytest -q tests/test_api.py
```

## Datos y claves

| Variable | Para qué | Sin ella |
|---|---|---|
| `ODDSPAPI_KEY` | Cuotas gratuitas de BetPlay y Rushbet (cada 8 h) | Carga manual, CSV o foto |
| `ODDS_API_NET_KEY` | Cuotas de los 14 operadores colombianos | Carga manual, CSV o foto (Configuración) |
| `NTFY_TOPIC` | Alertas push de surebets y valor | Solo notificaciones dentro de la app |
| `API_FOOTBALL_KEY` | Directo, estadísticas, bajas, Liga BetPlay | No hay directo, bajas ni modelo para Colombia |
| `ANTHROPIC_API_KEY` | Asistente conversacional con Claude | Enrutador local de intenciones |
| — | football-data.co.uk y StatsBomb Open Data | Siempre disponibles (gratuitos) |

- Detalles de formatos e importación: [`docs/DATOS.md`](docs/DATOS.md).
- Investigación de operadores, proveedores y modelos: [`docs/INVESTIGACION.md`](docs/INVESTIGACION.md).

## Principios

- **Sin datos inventados.**
  - Si falta un dato o una clave, la interfaz lo dice.
  - Las cuotas guardan su hora de consulta; las desactualizadas no se usan.
  - Los datos sintéticos solo existen dentro de las pruebas automatizadas.
- **Un modelo de lenguaje nunca genera probabilidades.**
- **Una combinada se coloca en un solo operador.** Nunca se presenta una cuota que mezcle casas.
- **No se asume independencia dentro de un mismo partido.** Esas selecciones se evalúan sobre las mismas simulaciones.
- **No se fuerza una cuota.** Si no hay una combinación sólida, el sistema lo informa.
- **Las predicciones no se reescriben.** Se registran antes del partido, quedan encadenadas por hash y la validación
  temporal muestra el rendimiento real.
