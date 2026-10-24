"""Sistemas de rating: Elo (con margen y por superficie) y Glicko-2.

Se recorren los partidos en orden cronológico; cada predicción usa solo
información anterior al partido (sin fuga de datos).
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from functools import partial

import numpy as np
from scipy.optimize import minimize
from scipy.special import expit


@dataclass
class Elo:
    k: float = 20.0
    home_adv: float = 65.0
    initial: float = 1500.0
    use_margin: bool = True
    ratings: dict[str, float] = field(default_factory=partial(defaultdict, partial(float, 1500.0)))
    games: dict[str, int] = field(default_factory=partial(defaultdict, int))

    def expected(self, home: str, away: str, neutral: bool = False) -> float:
        dr = self.ratings[home] - self.ratings[away] + (0 if neutral else self.home_adv)
        return 1.0 / (1.0 + 10 ** (-dr / 400.0))

    def diff(self, home: str, away: str, neutral: bool = False) -> float:
        return self.ratings[home] - self.ratings[away] + (0 if neutral else self.home_adv)

    def update(self, home: str, away: str, score_home: float, score_away: float, neutral: bool = False) -> None:
        e = self.expected(home, away, neutral)
        if score_home > score_away:
            s = 1.0
        elif score_home < score_away:
            s = 0.0
        else:
            s = 0.5
        k = self.k
        if self.use_margin:
            # Multiplicador de margen del World Football Elo
            gd = abs(score_home - score_away)
            k *= 1 if gd <= 1 else (1.5 if gd == 2 else (11 + gd) / 8)
        delta = k * (s - e)
        self.ratings[home] += delta
        self.ratings[away] -= delta
        self.games[home] += 1
        self.games[away] += 1

    def snapshot(self) -> dict[str, float]:
        return dict(self.ratings)


@dataclass
class SurfaceElo:
    """Elo de tenis por superficie (mezcla general + superficie, estilo FiveThirtyEight)."""

    blend: float = 0.5
    overall: dict[str, float] = field(default_factory=partial(defaultdict, partial(float, 1500.0)))
    surface: dict[tuple[str, str], float] = field(default_factory=partial(defaultdict, partial(float, 1500.0)))
    n_overall: dict[str, int] = field(default_factory=partial(defaultdict, int))
    n_surface: dict[tuple[str, str], int] = field(default_factory=partial(defaultdict, int))

    @staticmethod
    def _k(n: int) -> float:
        return 250.0 / ((n + 5) ** 0.4)

    def rating(self, player: str, surface: str) -> float:
        return (1 - self.blend) * self.overall[player] + self.blend * self.surface[(player, surface)]

    def win_prob(self, a: str, b: str, surface: str) -> float:
        dr = self.rating(a, surface) - self.rating(b, surface)
        return 1.0 / (1.0 + 10 ** (-dr / 400.0))

    def update(self, winner: str, loser: str, surface: str) -> None:
        for table, counts, kw, kl in (
            (self.overall, self.n_overall, winner, loser),
            (self.surface, self.n_surface, (winner, surface), (loser, surface)),
        ):
            e = 1.0 / (1.0 + 10 ** (-(table[kw] - table[kl]) / 400.0))
            table[kw] += self._k(counts[kw]) * (1 - e)
            table[kl] -= self._k(counts[kl]) * (1 - e)
            counts[kw] += 1
            counts[kl] += 1


# ---------------------------------------------------------------------------
# Glicko-2 (Glickman, 2012)
# ---------------------------------------------------------------------------

GLICKO_SCALE = 173.7178


@dataclass
class Glicko2:
    tau: float = 0.5
    initial_rating: float = 1500.0
    initial_rd: float = 350.0
    initial_vol: float = 0.06
    home_adv: float = 60.0
    state: dict[str, list[float]] = field(default_factory=dict)

    def _get(self, p: str) -> list[float]:
        if p not in self.state:
            self.state[p] = [self.initial_rating, self.initial_rd, self.initial_vol]
        return self.state[p]

    @staticmethod
    def _g(phi: float) -> float:
        return 1.0 / math.sqrt(1.0 + 3.0 * phi ** 2 / math.pi ** 2)

    def expected(self, home: str, away: str, neutral: bool = False) -> float:
        rh, rdh, _ = self._get(home)
        ra, rda, _ = self._get(away)
        mu = (rh + (0 if neutral else self.home_adv) - 1500) / GLICKO_SCALE
        mu_j = (ra - 1500) / GLICKO_SCALE
        phi = math.sqrt((rdh / GLICKO_SCALE) ** 2 + (rda / GLICKO_SCALE) ** 2)
        return 1.0 / (1.0 + math.exp(-self._g(phi) * (mu - mu_j)))

    def rd(self, p: str) -> float:
        return self._get(p)[1]

    def _update_one(self, p: str, opp: str, score: float, adv: float) -> list[float]:
        r, rd, vol = self._get(p)
        ro, rdo, _ = self._get(opp)
        mu, phi = (r + adv - 1500) / GLICKO_SCALE, rd / GLICKO_SCALE
        mu_j, phi_j = (ro - 1500) / GLICKO_SCALE, rdo / GLICKO_SCALE
        g = self._g(phi_j)
        e = 1.0 / (1.0 + math.exp(-g * (mu - mu_j)))
        v = 1.0 / (g ** 2 * e * (1 - e))
        delta = v * g * (score - e)
        a = math.log(vol ** 2)
        tau = self.tau

        def f(x: float) -> float:
            ex = math.exp(x)
            return (ex * (delta ** 2 - phi ** 2 - v - ex) / (2 * (phi ** 2 + v + ex) ** 2)) - (x - a) / tau ** 2

        A = a
        if delta ** 2 > phi ** 2 + v:
            B = math.log(delta ** 2 - phi ** 2 - v)
        else:
            k = 1
            while f(a - k * tau) < 0:
                k += 1
            B = a - k * tau
        fa, fb = f(A), f(B)
        for _ in range(100):
            if abs(B - A) < 1e-6:
                break
            C = A + (A - B) * fa / (fb - fa)
            fc = f(C)
            if fc * fb <= 0:
                A, fa = B, fb
            else:
                fa /= 2
            B, fb = C, fc
        new_vol = math.exp(A / 2)
        phi_star = math.sqrt(phi ** 2 + new_vol ** 2)
        new_phi = 1.0 / math.sqrt(1.0 / phi_star ** 2 + 1.0 / v)
        new_mu = mu + new_phi ** 2 * g * (score - e)
        return [new_mu * GLICKO_SCALE + 1500 - adv, min(new_phi * GLICKO_SCALE, self.initial_rd), new_vol]

    def update(self, home: str, away: str, score_home: float, score_away: float, neutral: bool = False) -> None:
        s = 1.0 if score_home > score_away else (0.0 if score_home < score_away else 0.5)
        adv = 0 if neutral else self.home_adv
        new_h = self._update_one(home, away, s, adv)
        new_a = self._update_one(away, home, 1 - s, -adv)
        self.state[home], self.state[away] = new_h, new_a


# ---------------------------------------------------------------------------
# Logit ordenado: convierte una diferencia de rating en P(L), P(E), P(V)
# ---------------------------------------------------------------------------

@dataclass
class OrderedLogit:
    beta: float = 0.004
    cut1: float = -0.4   # P(V) = σ(cut1 − β·x)
    cut2: float = 0.6    # P(V o E) = σ(cut2 − β·x)

    def fit(self, x: np.ndarray, outcome: np.ndarray) -> "OrderedLogit":
        """``outcome``: 0 local, 1 empate, 2 visitante."""
        x = np.asarray(x, float)
        y = np.asarray(outcome, int)

        def nll(p):
            b, c1, d = p
            c2 = c1 + math.exp(d)
            pa = expit(c1 - b * x)
            pad = expit(c2 - b * x)
            probs = np.stack([1 - pad, pad - pa, pa], axis=1)
            return -np.sum(np.log(np.clip(probs[np.arange(len(y)), y], 1e-12, None)))

        res = minimize(nll, [0.004, -0.4, 0.0], method="Nelder-Mead", options={"maxiter": 4000, "xatol": 1e-7})
        b, c1, d = res.x
        self.beta, self.cut1, self.cut2 = float(b), float(c1), float(c1 + math.exp(d))
        return self

    def probs(self, x: float | np.ndarray) -> np.ndarray:
        x = np.asarray(x, float)
        pa = expit(self.cut1 - self.beta * x)
        pad = expit(self.cut2 - self.beta * x)
        return np.stack([1 - pad, pad - pa, pa], axis=-1)
