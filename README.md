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
| Juego responsable | Verificación de mayoría de edad, límites de gasto y de sesión (los aumentos se aplican tras 24 h), autoexclusión y recursos de ayuda. |

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
| `ODDS_API_NET_KEY` | Cuotas de los 14 operadores colombianos | Carga manual o CSV de cuotas (Configuración) |
| `API_FOOTBALL_KEY` | Directo, estadísticas, alineaciones, Liga BetPlay | No hay directo ni modelo para Colombia |
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
