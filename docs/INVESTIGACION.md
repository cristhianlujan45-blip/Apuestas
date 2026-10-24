# Investigación técnica (fases 1 y 2)

Fecha de la investigación: **24 de octubre de 2026**.

## 1. Operadores autorizados en Colombia (Coljuegos)

**Fuente principal:** <https://www.coljuegos.gov.co/publicaciones/301841/juegosonline/>.
Publicada el 14/06/2018 y **modificada por última vez el 13/10/2026**. Lista **14 operadores** vigentes.

**Fuente secundaria:** <https://www.coljuegos.gov.co/publicaciones/306375/juegos-operados-por-internet/>.
Modificada por última vez el 30/01/2024. Es más antigua: trae números de contrato anteriores y marcas que ya no
aparecen en el listado vigente.

| # | Marca | Razón social | Dominio(s) | Contrato vigente | Contrato en página 2024 |
|---|---|---|---|---|---|
| 1 | Wplay | Aquila Global Group S.A.S. | wplay.co, apuestas.wplay.co | 2182 | 1741 |
| 2 | BetPlay | Corredor Empresarial S.A. | betplay.com.co | 1876 | 1876 |
| 3 | Betsson | Colbet S.A.S. | betsson.co | 1895-B | 1895 |
| 4 | Zamba | E Total Gaming S.A.S. | zamba.co | 1894 | 1894 |
| 5 | Codere | Codere Online Colombia S.A.S. | codere.com.co | 2218 | 1901 |
| 6 | Luckia | Luckia Colombia S.A.S. | luckia.co | 1932 | 1932 |
| 7 | Sportium | Sportium Apuestas Colombia S.A.S. | sportium.com.co, sports.sportium.com.co | 1942 | 1942 |
| 8 | Rushbet | Rush Street Interactive Colombia S.A.S. | rushbet.co | 1972 | 1972 |
| 9 | Rivalo | Teclino S.A.S. | rivalo.co | 1997 | 1997 |
| 10 | Yajuego | Games and Betting S.A.S. | yajuego.co, sports.yajuego.co | 2240 | 1841 |
| 11 | Bwin | Bwin Latam S.A.S. | sports.bwin.co | 2229 | 1747 |
| 12 | Stake | Stake Colombia S.A.S. | stake.com.co | 2226 | (1751 figuraba como Betfair) |
| 13 | Betano | Kaizen Gaming Colombia S.A.S. | betano.co | 2104 | — |
| 14 | MrYoker | Global Vitxo S.A.S. | mryoker.co | C2261 | — |

**Marcas de la página de 2024 que no figuran en el listado vigente:** Wonderbet (Alfabet S.A.S., contrato 2007),
Megapuesta (Servicios Distrired S.A.S., 1631), Fullreto (Grupo Vinnare S.A.S., 1695) y Betfair.com.co (1751).
La plataforma las registra como `not_in_current_list` y **nunca las usa ni las recomienda**.

**Cómo se mantiene al día:**
- El registro vive en `data/operators/coljuegos_registry.json`.
- Cada lunes el *worker* descarga la página pública de Coljuegos (`verify_against_coljuegos`) y compara los dominios.
- Si un operador autorizado desaparece del listado, se degrada a `not_in_current_list` y se genera una alerta crítica.
- Si aparece un dominio nuevo, se genera una alerta informativa.
- Para añadir un operador nuevo: `POST /api/operators` (requiere administrador). Queda como `pending_verification`
  hasta que su dominio aparece en la página oficial.

### Capacidades por operador

**API pública oficial:** ninguno de los 14 operadores ofrece una API pública documentada de cuotas. La plataforma
**no extrae datos de sus webs**: no se accede a cuentas, no se eluden CAPTCHA, protecciones ni controles de acceso.

**Plataforma tecnológica:**
- **BetPlay:** Kambi. La prensa especializada informa un acuerdo desde 2017, renovado en 2023, que incluye Bet Builder.
- **Rushbet:** Kambi integrado en la plataforma propia de Rush Street Interactive.
- **Betsson, Codere, Bwin (Entain), Stake y Betano (Kaizen):** plataformas propias de sus grupos.
- **Resto de operadores:** no verificado.

**Combinadas y mercados del mismo partido:**
- Todos ofrecen combinadas.
- Combinar mercados del mismo partido solo se marca como permitido en BetPlay (Bet Builder reportado).
- En el resto figura como *no verificado*. El optimizador lo trata como **no permitido** y la validación lo advierte.

**Formato de cuotas:** decimal en todos. La calculadora convierte a americana, fraccional, Hong Kong, indonesia y malaya.

**Máximo de selecciones por combinada:** no publicado de forma verificable. El campo existe en el registro
(`max_parlay_legs`) y el optimizador lo respeta si se completa.

## 2. Proveedores de datos

| Proveedor | Qué aporta | Cobertura Colombia | Coste / límites (según su documentación pública) | Estado |
|---|---|---|---|---|
| **odds-api.net** | Cuotas pre-partido y en vivo de casas colombianas; REST (`X-API-Key`), SSE y WebSocket | Lista 15 casas para CO: betano, betplay, betsson, bwin, codere, luckia, mryoker, rivalo, rushbet, sportiumco, stakeco, wplay, yajuego, zamba + pinnacle | Planes mensuales en USD; no publica precios en la referencia de la API | **Integrado** (`providers/odds_api_net.py`) — fuente principal de cuotas CO |
| odds-api.io | Cuotas (página específica de BetPlay); WebSocket | BetPlay confirmado; resto no listado | Desde £49/mes; nuevas claves gratuitas pausadas; 5.000 peticiones/h | Alternativa documentada |
| OddsPapi | Cuotas (página de BetPlay), REST + WebSocket | BetPlay | Plan gratuito informado de 250 peticiones/mes | Alternativa documentada |
| OpticOdds | Cuotas (Betano) | No especifica Colombia | Empresarial | Alternativa documentada |
| The Odds API | Cuotas internacionales | **No incluye casas colombianas** (regiones us, uk, eu, au, ca, fr, se, fi) | Créditos por petición | Configurable como referencia; no para recomendar |
| **API-Football (api-sports.io)** | Partidos, directo, estadísticas, xG (algunas ligas), alineaciones, eventos | Liga BetPlay (id 239), Torneo BetPlay (240), Copa Colombia (241) | Gratis: 100 peticiones/día por API | **Integrado** (`providers/api_sports.py`) |
| API-Basketball (api-sports.io) | Partidos y estadísticas de baloncesto | Liga colombiana y NBA | Igual que el anterior | **Integrado** (adaptador de partidos) |
| Sportmonks | Fútbol, xG como complemento | Sí | De pago | No integrado: la interfaz de proveedores permite añadirlo |
| Sportradar | Datos oficiales, directo de baja latencia | Sí | Contrato empresarial | No integrado (requiere contrato) |
| **football-data.co.uk** | Resultados, tiros, tiros al arco, córners, faltas, tarjetas y cuotas de apertura/cierre de 20+ ligas | No tiene Colombia | Gratuito | **Integrado**: entrenamiento, validación y cuotas de referencia |
| **StatsBomb Open Data** | Datos de eventos (pases, conducciones, tiros con xG) | — | Gratuito, uso no comercial con atribución | **Integrado** para xT/xA |
| Jeff Sackmann (tenis) | Partidos ATP/WTA con estadísticas de saque | — | CC BY-NC-SA | No accesible desde este entorno (404). El importador CSV acepta su formato |
| tennis-data.co.uk | Partidos y cuotas de tenis | — | Gratuito | Respondió 403 desde este entorno |

**Decisión:**
- Las cuotas colombianas llegan **solo** desde un agregador con licencia (odds-api.net) o desde la carga manual/CSV
  del usuario.
- Las cuotas internacionales (football-data.co.uk, Pinnacle) se usan **solo como referencia de mercado** para estimar
  probabilidades justas.
- Una combinada nunca mezcla operadores distintos.

## 3. Modelos matemáticos y de IA

| Familia | Implementación | Uso |
|---|---|---|
| Poisson independiente | `engine/football/goals.py` (`TeamRatingModel`, `use_rho=False`) | Goles, carreras (béisbol) y conteos de córners, tarjetas y tiros |
| Dixon-Coles | Mismo módulo: MAP con prior normal y ponderación temporal ξ = 0.0019/día; aproximación de Laplace para la incertidumbre | Matriz de marcadores y mercados de goles |
| Poisson bivariado (Karlis-Ntzoufras) | `BivariatePoissonModel` | Covarianza de goles |
| Elo con margen de goles | `engine/ratings.py` + logit ordenado | 1X2 |
| Glicko-2 | `engine/ratings.py` | 1X2, con medida de incertidumbre (RD) |
| Inferencia bayesiana | MAP + Laplace (goles); Gamma-Poisson en directo; binomial negativa en conteos | Intervalos y directo |
| xG | Del proveedor cuando existe; si no, proxy por tiros ajustado por mínimos cuadrados (indicado como proxy) | Variables de ML y directo |
| xT / xA | `engine/football/xt.py`: iteración de valor (Singh 2018) sobre StatsBomb | Análisis de jugadores |
| ML supervisado | LogReg, Random Forest, LightGBM, XGBoost, CatBoost y MLP en PyTorch (`engine/ml.py`) | 1X2 con variables pre-partido sin fuga |
| Ensemble | Stacking convexo que minimiza el log loss sobre predicciones fuera de muestra (`engine/validation.py`) | Probabilidad final |
| Monte Carlo | `engine/montecarlo.py` + simuladores por deporte | Distribuciones, mercados conjuntos, parlays |
| Baloncesto | ORtg/DRtg por 100 posesiones (Oliver), ritmo, Four Factors, normal bivariante con prórrogas, props de jugador | `engine/basketball.py` |
| Tenis | Elo por superficie, saque/resto (Barnett-Clarke), Markov analítico y simulación | `engine/tennis.py` |
| Béisbol / voleibol | Carreras con binomial negativa y entradas extra; rally a rally | `engine/other_sports.py` |

**Selección de modelos:**
- Se usa validación temporal (walk-forward). Los modelos de goles se reajustan cada semana con datos anteriores a esa
  semana; los de ML y ratings, cada 8 semanas.
- Métricas: log loss, Brier, RPS, acierto, ECE, MAE y RMSE de goles totales, y ROI con intervalo bootstrap y CLV.
- El campeón es el modelo o ensemble con menor log loss en el conjunto común.
- Un modelo nuevo solo se promueve si no empeora la validación.

**Hallazgo principal de la validación con datos reales:**
- El precio de mercado sin margen (consenso de casas internacionales) es el predictor más difícil de superar, como
  indica la literatura.
- Por eso el ensemble lo incluye con su peso estimado.
- Además, se reportan con honestidad los ROI negativos de apostar solo con modelos propios.
