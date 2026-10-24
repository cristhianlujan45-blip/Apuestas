"""Tenis: Elo por superficie + modelo de saque/resto con cadena de Markov.

* Elo general y por superficie (mezcla 50/50) con K decreciente.
* Puntos ganados al saque y al resto (media exponencial por superficie).
* Probabilidad de punto al saque combinada al estilo Barnett-Clarke.
* Probabilidades analíticas de juego, tie-break, set y partido; distribución
  de juegos y resultado por sets por simulación juego a juego.
* La probabilidad final de partido combina Elo y Markov; después se desplazan
  las probabilidades de saque para que la cadena reproduzca ese valor, de modo
  que sets y juegos son coherentes con el ganador estimado.

Formato de datos esperado (compatible con el de Jeff Sackmann): fecha,
superficie, ganador, perdedor, best_of y estadísticas de saque w_*/l_*.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache, partial

import numpy as np
import pandas as pd
from scipy.optimize import brentq

from .markets import Outcomes
from .ratings import SurfaceElo


def game_win_prob(p: float) -> float:
    q = 1 - p
    deuce = p ** 2 / (1 - 2 * p * q) if (1 - 2 * p * q) > 0 else 0.5
    return p ** 4 * (1 + 4 * q + 10 * q ** 2) + 20 * p ** 3 * q ** 3 * deuce


@lru_cache(maxsize=20000)
def _tiebreak(pa: float, pb: float, a: int = 0, b: int = 0, target: int = 7) -> float:
    """P(gana A el tie-break) con A sacando el primer punto."""
    if a >= target and a - b >= 2:
        return 1.0
    if b >= target and b - a >= 2:
        return 0.0
    if a >= target - 1 and b >= target - 1 and a == b:
        # Estado de "deuce" del tie-break: dos puntos (uno con cada saque)
        win2 = pa * (1 - pb)
        lose2 = (1 - pa) * pb
        return win2 / (win2 + lose2) if (win2 + lose2) > 0 else 0.5
    n = a + b
    server_a = (n % 4 == 0) or (n % 4 == 3)
    p = pa if server_a else 1 - pb
    return p * _tiebreak(pa, pb, a + 1, b, target) + (1 - p) * _tiebreak(pa, pb, a, b + 1, target)


@lru_cache(maxsize=20000)
def set_win_prob(pa: float, pb: float, a_serves_first: bool = True) -> float:
    ga, gb = game_win_prob(pa), game_win_prob(pb)
    tb = _tiebreak(round(pa, 6), round(pb, 6))

    @lru_cache(maxsize=None)
    def f(x: int, y: int) -> float:
        if x >= 6 and x - y >= 2:
            return 1.0
        if y >= 6 and y - x >= 2:
            return 0.0
        if x == 6 and y == 6:
            return tb if ((x + y) % 2 == 0) == a_serves_first else 1 - _tiebreak(round(pb, 6), round(pa, 6))
        a_serving = ((x + y) % 2 == 0) == a_serves_first
        p = ga if a_serving else 1 - gb
        return p * f(x + 1, y) + (1 - p) * f(x, y + 1)

    return f(0, 0)


def match_win_prob(pa: float, pb: float, best_of: int = 3) -> float:
    s = 0.5 * (set_win_prob(round(pa, 6), round(pb, 6), True) + set_win_prob(round(pa, 6), round(pb, 6), False))
    need = best_of // 2 + 1

    @lru_cache(maxsize=None)
    def m(x: int, y: int) -> float:
        if x == need:
            return 1.0
        if y == need:
            return 0.0
        return s * m(x + 1, y) + (1 - s) * m(x, y + 1)

    return m(0, 0)


def simulate_match(pa: float, pb: float, best_of: int, n: int, rng: np.random.Generator) -> dict[str, np.ndarray]:
    """Simulación juego a juego vectorizada (sets, juegos)."""
    ga, gb = game_win_prob(pa), game_win_prob(pb)
    tb_a = _tiebreak(round(pa, 6), round(pb, 6))
    need = best_of // 2 + 1
    sets_a = np.zeros(n, int)
    sets_b = np.zeros(n, int)
    games_a = np.zeros(n, int)
    games_b = np.zeros(n, int)
    a_serves = rng.random(n) < 0.5
    for _ in range(best_of):
        active = (sets_a < need) & (sets_b < need)
        if not active.any():
            break
        x = np.zeros(n, int)
        y = np.zeros(n, int)
        done = ~active
        serve = a_serves.copy()
        for _g in range(13):
            live = ~done
            if not live.any():
                break
            tie = live & (x == 6) & (y == 6)
            normal = live & ~tie
            r = rng.random(n)
            win_a = np.where(serve, r < ga, r >= gb)
            x = x + (normal & win_a)
            y = y + (normal & ~win_a)
            tb_win = rng.random(n) < tb_a
            x = x + (tie & tb_win)
            y = y + (tie & ~tb_win)
            serve = np.where(live, ~serve, serve)
            done = done | ((x >= 6) & (x - y >= 2)) | ((y >= 6) & (y - x >= 2)) | (x == 7) | (y == 7)
        won_a = active & (x > y)
        won_b = active & (y > x)
        sets_a += won_a
        sets_b += won_b
        games_a += np.where(active, x, 0)
        games_b += np.where(active, y, 0)
        a_serves = serve
    return {"home_sets": sets_a, "away_sets": sets_b, "home_games": games_a, "away_games": games_b,
            "home": sets_a, "away": sets_b}


@dataclass
class TennisModel:
    alpha: float = 0.08
    elo: SurfaceElo = field(default_factory=SurfaceElo)
    serve: dict = field(default_factory=partial(defaultdict, type(None)))
    ret: dict = field(default_factory=partial(defaultdict, type(None)))
    n_matches: dict = field(default_factory=partial(defaultdict, int))
    tour_serve: float = 0.635
    w_elo: float = 0.5
    fitted_until: datetime | None = None

    def _push(self, table: dict, key, value: float) -> None:
        prev = table[key]
        table[key] = value if prev is None else (1 - self.alpha) * prev + self.alpha * value

    def fit(self, df: pd.DataFrame, ref_date: datetime) -> "TennisModel":
        df = df[pd.to_datetime(df["date"]).dt.tz_localize(None) < pd.Timestamp(ref_date).tz_localize(None)]
        df = df.sort_values("date", kind="mergesort")
        sv = []
        for r in df.to_dict("records"):
            surf = str(r.get("surface") or "Hard")
            w, l = r["winner"], r["loser"]
            self.elo.update(w, l, surf)
            self.n_matches[w] += 1
            self.n_matches[l] += 1
            if all(not pd.isna(r.get(c)) for c in ("w_svpt", "w_1stWon", "w_2ndWon", "l_svpt", "l_1stWon", "l_2ndWon")) \
                    and r["w_svpt"] > 0 and r["l_svpt"] > 0:
                ws = (r["w_1stWon"] + r["w_2ndWon"]) / r["w_svpt"]
                ls = (r["l_1stWon"] + r["l_2ndWon"]) / r["l_svpt"]
                for p, s_own, s_opp in ((w, ws, ls), (l, ls, ws)):
                    self._push(self.serve, (p, surf), s_own)
                    self._push(self.serve, (p, "*"), s_own)
                    self._push(self.ret, (p, surf), 1 - s_opp)
                    self._push(self.ret, (p, "*"), 1 - s_opp)
                sv.extend([ws, ls])
        if sv:
            self.tour_serve = float(np.mean(sv[-5000:]))
        self.fitted_until = ref_date
        return self

    def _serve_ret(self, p: str, surface: str) -> tuple[float, float]:
        s = self.serve[(p, surface)] or self.serve[(p, "*")] or self.tour_serve
        r = self.ret[(p, surface)] or self.ret[(p, "*")] or (1 - self.tour_serve)
        return s, r

    def point_probs(self, a: str, b: str, surface: str) -> tuple[float, float]:
        sa, ra = self._serve_ret(a, surface)
        sb, rb = self._serve_ret(b, surface)
        avg_ret = 1 - self.tour_serve
        pa = self.tour_serve + (sa - self.tour_serve) - (rb - avg_ret)
        pb = self.tour_serve + (sb - self.tour_serve) - (ra - avg_ret)
        return float(np.clip(pa, 0.4, 0.85)), float(np.clip(pb, 0.4, 0.85))

    def predict(self, a: str, b: str, surface: str = "Hard", best_of: int = 3) -> dict:
        p_elo = self.elo.win_prob(a, b, surface)
        pa, pb = self.point_probs(a, b, surface)
        p_markov = match_win_prob(pa, pb, best_of)
        p_final = self.w_elo * p_elo + (1 - self.w_elo) * p_markov
        # Desplazar probabilidades de saque para reproducir p_final
        try:
            d = brentq(lambda d: match_win_prob(np.clip(pa + d, 0.3, 0.95), np.clip(pb - d, 0.3, 0.95), best_of)
                       - p_final, -0.2, 0.2, xtol=1e-5)
        except ValueError:
            d = 0.0
        quality = {"matches_a": self.n_matches[a], "matches_b": self.n_matches[b],
                   "sufficient": self.n_matches[a] >= 10 and self.n_matches[b] >= 10}
        return {"p_elo": p_elo, "p_markov": p_markov, "p_match": p_final,
                "serve_point_a": float(pa + d), "serve_point_b": float(pb - d),
                "elo_a": self.elo.rating(a, surface), "elo_b": self.elo.rating(b, surface),
                "best_of": best_of, "surface": surface, "data_quality": quality}

    def outcomes(self, a: str, b: str, surface: str = "Hard", best_of: int = 3, n: int = 20000,
                 seed: int = 0) -> Outcomes:
        p = self.predict(a, b, surface, best_of)
        rng = np.random.default_rng(seed)
        vals = simulate_match(p["serve_point_a"], p["serve_point_b"], best_of, n, rng)
        return Outcomes("tennis", vals, np.ones(n), meta={"prediction": p})
