"""Catálogo de mercados y liquidación vectorizada sobre resultados simulados.

Cada modelo deportivo produce un conjunto de resultados ``Outcomes`` (una
rejilla exacta con pesos o muestras Monte Carlo). Cualquier selección se
liquida sobre esos resultados, lo que permite:

* probabilidades exactas por selección (incluidas líneas asiáticas con push
  y medio acierto),
* probabilidad conjunta de varias selecciones del MISMO evento sin asumir
  independencia (se liquidan sobre las mismas muestras).

La liquidación de cada muestra se codifica como ``(a, b)`` de forma que el
multiplicador de retorno con cuota ``o`` es ``a·o + b``:
ganada (1, 0) · perdida (0, 0) · nula (0, 1) · media ganada (½, ½) · media perdida (0, ½).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import numpy as np

# ---------------------------------------------------------------------------
# Catálogo
# ---------------------------------------------------------------------------

MARKETS: dict[str, dict] = {
    # Fútbol
    "1x2": {"sport": "football", "label": "Ganador del partido (1X2)", "selections": ["home", "draw", "away"]},
    "double_chance": {"sport": "football", "label": "Doble oportunidad", "selections": ["1X", "X2", "12"]},
    "dnb": {"sport": "football", "label": "Empate no apuesta", "selections": ["home", "away"]},
    "total_goals": {"sport": "football", "label": "Total de goles (más/menos)", "selections": ["over", "under"], "line": True},
    "btts": {"sport": "football", "label": "Ambos equipos marcan", "selections": ["yes", "no"]},
    "correct_score": {"sport": "football", "label": "Resultado exacto", "selections": ["h-a"]},
    "asian_handicap": {"sport": "football", "label": "Hándicap asiático", "selections": ["home", "away"], "line": True},
    "european_handicap": {"sport": "football", "label": "Hándicap europeo", "selections": ["home", "draw", "away"], "line": True},
    "team_total_home": {"sport": "football", "label": "Goles del local", "selections": ["over", "under"], "line": True},
    "team_total_away": {"sport": "football", "label": "Goles del visitante", "selections": ["over", "under"], "line": True},
    "corners_total": {"sport": "football", "label": "Córners totales", "selections": ["over", "under"], "line": True},
    "corners_home": {"sport": "football", "label": "Córners del local", "selections": ["over", "under"], "line": True},
    "corners_away": {"sport": "football", "label": "Córners del visitante", "selections": ["over", "under"], "line": True},
    "cards_total": {"sport": "football", "label": "Tarjetas totales", "selections": ["over", "under"], "line": True},
    "shots_total": {"sport": "football", "label": "Tiros totales", "selections": ["over", "under"], "line": True},
    "shots_on_target_total": {"sport": "football", "label": "Tiros al arco totales", "selections": ["over", "under"], "line": True},
    # Baloncesto / tenis / béisbol / voleibol
    "moneyline": {"sport": "*", "label": "Ganador", "selections": ["home", "away"]},
    "spread": {"sport": "*", "label": "Hándicap", "selections": ["home", "away"], "line": True},
    "total_points": {"sport": "basketball", "label": "Total de puntos", "selections": ["over", "under"], "line": True},
    "team_points_home": {"sport": "basketball", "label": "Puntos del local", "selections": ["over", "under"], "line": True},
    "team_points_away": {"sport": "basketball", "label": "Puntos del visitante", "selections": ["over", "under"], "line": True},
    "player_points": {"sport": "basketball", "label": "Puntos del jugador", "selections": ["over", "under"], "line": True, "player": True},
    "player_rebounds": {"sport": "basketball", "label": "Rebotes del jugador", "selections": ["over", "under"], "line": True, "player": True},
    "player_assists": {"sport": "basketball", "label": "Asistencias del jugador", "selections": ["over", "under"], "line": True, "player": True},
    "player_threes": {"sport": "basketball", "label": "Triples del jugador", "selections": ["over", "under"], "line": True, "player": True},
    "set_betting": {"sport": "*", "label": "Resultado por sets", "selections": ["h-a"]},
    "total_games": {"sport": "tennis", "label": "Total de juegos", "selections": ["over", "under"], "line": True},
    "games_handicap": {"sport": "tennis", "label": "Hándicap de juegos", "selections": ["home", "away"], "line": True},
    "total_sets": {"sport": "*", "label": "Total de sets", "selections": ["over", "under"], "line": True},
    "total_runs": {"sport": "baseball", "label": "Total de carreras", "selections": ["over", "under"], "line": True},
    "set_handicap": {"sport": "volleyball", "label": "Hándicap de sets", "selections": ["home", "away"], "line": True},
}

SELECTION_LABELS = {
    "home": "Local", "away": "Visitante", "draw": "Empate", "over": "Más de", "under": "Menos de",
    "yes": "Sí", "no": "No", "1X": "1X", "X2": "X2", "12": "12",
}


@dataclass(frozen=True)
class Selection:
    market: str
    selection: str
    line: float | None = None
    player: str | None = None
    period: str = "ft"

    @property
    def key(self) -> str:
        line = "" if self.line is None else f"{self.line:g}"
        player = self.player or ""
        return f"{self.market}|{self.selection}|{line}|{player}|{self.period}"

    @classmethod
    def from_key(cls, key: str) -> "Selection":
        market, selection, line, player, period = key.split("|")
        return cls(market, selection, float(line) if line else None, player or None, period or "ft")

    def describe(self, home: str = "Local", away: str = "Visitante") -> str:
        meta = MARKETS.get(self.market, {"label": self.market})
        sel = {"home": home, "away": away}.get(self.selection, SELECTION_LABELS.get(self.selection, self.selection))
        parts = [meta["label"], "—"]
        if self.player:
            parts.append(self.player)
        parts.append(sel)
        if self.line is not None:
            if self.market in {"asian_handicap", "spread", "games_handicap", "set_handicap", "european_handicap"}:
                parts.append(f"({self.line:+g})")
            else:
                parts.append(f"{self.line:g}")
        return " ".join(parts)


@dataclass
class Outcomes:
    """Resultados de un evento: arrays alineados más pesos (suman 1)."""

    sport: str
    values: dict[str, np.ndarray]
    weights: np.ndarray
    exact: bool = False
    meta: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.weights = np.asarray(self.weights, dtype=float)
        s = self.weights.sum()
        if s <= 0:
            raise ValueError("Pesos inválidos")
        self.weights = self.weights / s

    def __getitem__(self, key: str) -> np.ndarray:
        if key not in self.values:
            raise UnsupportedMarket(f"El modelo no dispone de la variable '{key}'")
        return self.values[key]

    def has(self, key: str) -> bool:
        return key in self.values

    @property
    def n(self) -> int:
        return len(self.weights)


class UnsupportedMarket(Exception):
    """El modelo no puede valorar esta selección con los datos disponibles."""


# ---------------------------------------------------------------------------
# Primitivas de liquidación
# ---------------------------------------------------------------------------

def _is_quarter(line: float) -> bool:
    return abs((line * 4) % 2 - 1) < 1e-9


def _three_way(diff: np.ndarray, win_if_positive: bool = True) -> tuple[np.ndarray, np.ndarray]:
    win = (diff > 0) if win_if_positive else (diff < 0)
    return win.astype(float), np.zeros_like(diff, dtype=float)


def _line_grade(score: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """score > 0 gana, == 0 nula, < 0 pierde."""
    a = (score > 1e-9).astype(float)
    b = (np.abs(score) <= 1e-9).astype(float)
    return a, b


def _split(fn: Callable[[float], tuple[np.ndarray, np.ndarray]], line: float) -> tuple[np.ndarray, np.ndarray]:
    if _is_quarter(line):
        a1, b1 = fn(line - 0.25)
        a2, b2 = fn(line + 0.25)
        # Media apuesta a cada línea: retorno = ½(a1·o + b1) + ½(a2·o + b2)
        return (a1 + a2) / 2, (b1 + b2) / 2
    return fn(line)


def grade_over_under(x: np.ndarray, line: float, side: str) -> tuple[np.ndarray, np.ndarray]:
    sign = 1.0 if side == "over" else -1.0
    return _split(lambda l: _line_grade(sign * (x - l)), line)


def grade_handicap(diff_for_side: np.ndarray, line: float) -> tuple[np.ndarray, np.ndarray]:
    return _split(lambda l: _line_grade(diff_for_side + l), line)


def _require_line(sel: Selection) -> float:
    if sel.line is None:
        raise UnsupportedMarket(f"El mercado {sel.market} requiere una línea")
    return sel.line


def grade(sel: Selection, out: Outcomes) -> tuple[np.ndarray, np.ndarray]:
    """Devuelve (a, b) por resultado para la selección dada."""
    if sel.period != "ft":
        raise UnsupportedMarket("Solo se modelan mercados de tiempo completo")
    m, s = sel.market, sel.selection
    sport = out.sport

    if sport in {"tennis", "volleyball"} and m in {"moneyline", "set_betting", "total_sets", "set_handicap"}:
        h, a = out["home_sets"], out["away_sets"]
    elif m in {"total_games", "games_handicap"}:
        h, a = out["home_games"], out["away_games"]
    elif m.startswith("corners"):
        h, a = out["corners_home"], out["corners_away"]
    elif m == "cards_total":
        h, a = out["cards_home"], out["cards_away"]
    elif m == "shots_total":
        h, a = out["shots_home"], out["shots_away"]
    elif m == "shots_on_target_total":
        h, a = out["sot_home"], out["sot_away"]
    elif m == "total_points" and sport == "volleyball":
        h, a = out["home_points"], out["away_points"]
    elif m.startswith("player_"):
        if not sel.player:
            raise UnsupportedMarket("Mercado de jugador sin nombre de jugador")
        stat = m.removeprefix("player_")
        x = out[f"player:{sel.player}:{stat}"]
        return grade_over_under(x, _require_line(sel), s)
    else:
        h, a = out["home"], out["away"]

    diff = h - a
    if m in {"1x2"}:
        if s == "home":
            return _three_way(diff)
        if s == "away":
            return _three_way(diff, win_if_positive=False)
        if s == "draw":
            return (diff == 0).astype(float), np.zeros_like(diff, dtype=float)
    if m == "moneyline":
        if s == "home":
            return (diff > 0).astype(float), (diff == 0).astype(float)
        if s == "away":
            return (diff < 0).astype(float), (diff == 0).astype(float)
    if m == "double_chance":
        win = {"1X": diff >= 0, "X2": diff <= 0, "12": diff != 0}[s]
        return win.astype(float), np.zeros_like(diff, dtype=float)
    if m == "dnb":
        d = diff if s == "home" else -diff
        return _line_grade(d)
    if m in {"total_goals", "total_points", "total_runs", "total_games", "total_sets", "corners_total",
             "cards_total", "shots_total", "shots_on_target_total"}:
        return grade_over_under(h + a, _require_line(sel), s)
    if m in {"team_total_home", "team_points_home", "corners_home"}:
        return grade_over_under(h, _require_line(sel), s)
    if m in {"team_total_away", "team_points_away", "corners_away"}:
        return grade_over_under(a, _require_line(sel), s)
    if m == "btts":
        both = (h > 0) & (a > 0)
        win = both if s == "yes" else ~both
        return win.astype(float), np.zeros_like(diff, dtype=float)
    if m in {"correct_score", "set_betting"}:
        try:
            hs, as_ = (int(x) for x in s.split("-"))
        except ValueError as exc:
            raise UnsupportedMarket(f"Marcador inválido: {s}") from exc
        win = (h == hs) & (a == as_)
        return win.astype(float), np.zeros_like(diff, dtype=float)
    if m in {"asian_handicap", "spread", "games_handicap", "set_handicap"}:
        d = diff if s == "home" else -diff
        return grade_handicap(d, _require_line(sel))
    if m == "european_handicap":
        line = _require_line(sel)
        adj = diff + line  # línea aplicada al local
        if s == "home":
            return (adj > 0).astype(float), np.zeros_like(diff, dtype=float)
        if s == "away":
            return (adj < 0).astype(float), np.zeros_like(diff, dtype=float)
        if s == "draw":
            return (adj == 0).astype(float), np.zeros_like(diff, dtype=float)
    raise UnsupportedMarket(f"Mercado no soportado por el modelo: {m}/{s}")


@dataclass
class LegPricing:
    p_win: float      # probabilidad de ganar completa
    p_half_win: float
    p_push: float
    p_half_lose: float
    p_lose: float

    @property
    def p_effective(self) -> float:
        """Probabilidad equivalente a ganar (cuenta medias ganadas como ½)."""
        return self.p_win + 0.5 * self.p_half_win

    def expected_return(self, odds: float) -> float:
        return (self.p_win * odds + self.p_half_win * (odds + 1) / 2 + self.p_push
                + self.p_half_lose * 0.5)

    def ev(self, odds: float) -> float:
        return self.expected_return(odds) - 1.0

    def fair_odds(self) -> float:
        """Cuota con EV = 0."""
        # Resolver a·o + b = 1 en esperanza: o = (1 - E[b]) / E[a]
        ea = self.p_win + 0.5 * self.p_half_win
        eb = self.p_push + 0.5 * self.p_half_win + 0.5 * self.p_half_lose
        if ea <= 0:
            return float("inf")
        return (1 - eb) / ea

    def as_dict(self) -> dict:
        return {
            "p_win": self.p_win, "p_half_win": self.p_half_win, "p_push": self.p_push,
            "p_half_lose": self.p_half_lose, "p_lose": self.p_lose,
        }


def price(sel: Selection, out: Outcomes) -> LegPricing:
    a, b = grade(sel, out)
    w = out.weights
    win = float(np.sum(w * (a == 1)))
    half_win = float(np.sum(w * ((a == 0.5) & (b == 0.5))))
    push = float(np.sum(w * ((a == 0) & (b == 1))))
    half_lose = float(np.sum(w * ((a == 0) & (b == 0.5))))
    lose = max(0.0, 1.0 - win - half_win - push - half_lose)
    return LegPricing(win, half_win, push, half_lose, lose)


def joint_same_event(selections: list[tuple[Selection, float]], out: Outcomes) -> dict:
    """Retorno y probabilidad conjunta de varias selecciones del mismo evento.

    Se liquidan sobre las mismas muestras, de modo que la correlación entre
    mercados (p. ej. «gana local» y «más de 2.5») queda capturada exactamente.
    """
    mult = np.ones(out.n)
    no_loss = np.ones(out.n, dtype=bool)
    full_win = np.ones(out.n, dtype=bool)
    for sel, odds in selections:
        a, b = grade(sel, out)
        mult *= a * odds + b
        no_loss &= (a + b) > 0
        full_win &= a == 1
    w = out.weights
    return {
        "expected_return": float(np.sum(w * mult)),
        "p_no_loss": float(np.sum(w * no_loss)),
        "p_all_win": float(np.sum(w * full_win)),
        "multipliers": mult,
    }
