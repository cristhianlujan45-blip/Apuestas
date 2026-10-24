# Datos: fuentes, importación y formatos

La plataforma **no genera datos ficticios**. Cada módulo funciona con datos reales de una de estas formas:

1. **Proveedores con clave** (`.env`): odds-api.net (cuotas colombianas) y API-Football / API-Basketball (partidos,
   directo, estadísticas y Liga BetPlay).
2. **Fuentes abiertas sin clave:**
   - football-data.co.uk: histórico, estadísticas y cuotas de referencia.
   - StatsBomb Open Data: eventos para calcular xT y xA.
3. **Importación del usuario:** cuotas manuales o en CSV, y CSV de histórico para deportes sin proveedor configurado.

## Cuotas manuales / CSV

Endpoints: `POST /api/odds/manual` (JSON) o `POST /api/odds/import` (CSV). También se pueden cargar desde
*Configuración* en la interfaz.

```csv
sport,competition,start_time,home,away,operator,market,selection,line,player,odds,captured_at
football,Primera A,2026-10-25T18:10,Millonarios,Nacional,betplay,1x2,home,,,2.35,2026-10-24T09:00
football,Primera A,2026-10-25T18:10,Millonarios,Nacional,wplay,total_goals,over,2.5,,2.05,
```

- **Fecha y hora:** `start_time` y `captured_at` en ISO 8601. Si no llevan zona horaria, se interpretan en hora de
  Colombia.
- **Hora de consulta:** si `captured_at` va vacío, se usa la hora de la carga. Las cuotas con más de 15 minutos
  (pre-partido) o 60 segundos (en vivo) se marcan como desactualizadas y no entran en las combinadas.
- **Operador:** debe ser una clave autorizada (`betplay`, `wplay`, `betsson`, `zamba`, `codere`, `luckia`,
  `sportium`, `rushbet`, `rivalo`, `yajuego`, `bwin`, `stake`, `betano`, `mryoker`).
- **Mercados y selecciones:** se listan en `GET /api/markets`.
  - Fútbol: `1x2` (home/draw/away), `double_chance` (1X/X2/12), `dnb`, `total_goals` (over/under + línea), `btts`
    (yes/no), `correct_score` (`2-1`), `asian_handicap` (línea del lado elegido), `european_handicap` (línea del
    local), `team_total_home`/`team_total_away`, `corners_total`, `cards_total`, `shots_total`,
    `shots_on_target_total`.
  - Baloncesto: `moneyline`, `spread`, `total_points`, `team_points_home`/`team_points_away`, `player_points`,
    `player_rebounds`, `player_assists`, `player_threes` (requieren `player`).
  - Tenis: `moneyline`, `set_betting` (`2-0`), `total_games`, `games_handicap`, `total_sets`.

## Histórico de otros deportes (`data/import/`)

Coloque los archivos y ejecute `python -m app.cli train-other`.

| Archivo | Columnas obligatorias | Opcionales |
|---|---|---|
| `basketball_games.csv` | `date,home,away,hpts,apts` | Caja por equipo: `h_fga,h_fgm,h_fg3a,h_fg3m,h_fta,h_ftm,h_orb,h_drb,h_tov` y los mismos con `a_` (activa posesiones y Four Factors) |
| `basketball_players.csv` | `date,team,player,minutes,points,rebounds,assists,threes` | — |
| `tennis_matches.csv` | `date,surface,winner,loser` | `best_of,w_svpt,w_1stWon,w_2ndWon,l_svpt,l_1stWon,l_2ndWon` (formato Sackmann) |
| `baseball_games.csv` | `date,home,away,hruns,aruns` | — |
| `volleyball_games.csv` | `date,home,away,hpts,apts` (puntos totales del partido) | — |

Los modelos registran cuántos partidos tiene cada equipo o jugador. Con menos de 5 partidos (10 en tenis), las
selecciones se marcan con **datos insuficientes** y el optimizador las descarta.

## Liga BetPlay (Colombia)

football-data.co.uk no cubre Colombia. Con `API_FOOTBALL_KEY` configurada:
- el entrenamiento descarga las tres últimas temporadas de la liga 239 (`colombia_history`);
- crea el grupo `COL` en el modelo de goles.

Sin esa clave, los partidos colombianos se muestran con la nota «sin historial en el modelo de goles». En ese caso
no se generan probabilidades para ellos.
