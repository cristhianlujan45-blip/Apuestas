"""Béisbol y voleibol.

Béisbol: carreras con modelo log-lineal ataque/defensa (mismo núcleo que los
goles, sin corrección DC) y binomial negativa; entradas extra simuladas.

Voleibol: probabilidad de ganar cada rally estimada a partir de la cuota de
puntos ganados (ajustada por rival) y simulación rally a rally de sets a 25
(15 el quinto) con diferencia de 2.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from functools import partial
from datetime import datetime

import numpy as np
import pandas as pd

from .football.goals import TeamRatingModel
from .markets import Outcomes


@dataclass
class BaseballModel:
    model: TeamRatingModel = field(default_factory=partial(
        TeamRatingModel, name="baseball_runs", use_rho=False, xi=0.004, prior_sd=0.25, compute_cov=False))

    def fit(self, df: pd.DataFrame, ref_date: datetime) -> "BaseballModel":
        d = df.rename(columns={"hruns": "hg", "aruns": "ag"})
        self.model.fit(d, ref_date)
        return self

    def outcomes(self, home: str, away: str, n: int = 20000, seed: int = 0) -> Outcomes:
        rng = np.random.default_rng(seed)
        lh, la = self.model.rates(home, away)
        disp = max(self.model.dispersion, 1e-6)

        def nb(mean: float, size: int) -> np.ndarray:
            r = 1 / disp
            return rng.negative_binomial(r, r / (r + mean), size)

        h, a = nb(lh, n), nb(la, n)
        for _ in range(10):  # entradas extra: una entrada cada equipo
            tie = h == a
            if not tie.any():
                break
            m = int(tie.sum())
            h[tie] += rng.poisson(lh / 9 * 1.15, m)  # corredor fantasma en extras (MLB desde 2020)
            a[tie] += rng.poisson(la / 9 * 1.15, m)
        tie = h == a
        if tie.any():
            coin = rng.random(int(tie.sum())) < lh / (lh + la)
            h[tie] += coin
            a[tie] += ~coin
        return Outcomes("baseball", {"home": h, "away": a}, np.ones(n),
                        meta={"expected_runs": {"home": lh, "away": la},
                              "data_quality": {"home_known": self.model.knows(home),
                                               "away_known": self.model.knows(away)}})


@dataclass
class VolleyballModel:
    alpha: float = 0.1
    share: dict = field(default_factory=partial(defaultdict, partial(float, 0.5)))
    conceded: dict = field(default_factory=partial(defaultdict, partial(float, 0.5)))
    n: dict = field(default_factory=partial(defaultdict, int))
    home_edge: float = 0.008

    def fit(self, df: pd.DataFrame, ref_date: datetime) -> "VolleyballModel":
        """Columnas: date, home, away, hpts, apts (puntos totales del partido)."""
        df = df[pd.to_datetime(df["date"]).dt.tz_localize(None) < pd.Timestamp(ref_date).tz_localize(None)]
        for r in df.sort_values("date", kind="mergesort").to_dict("records"):
            tot = r["hpts"] + r["apts"]
            if not tot:
                continue
            sh = r["hpts"] / tot
            for team, s in ((r["home"], sh), (r["away"], 1 - sh)):
                self.share[team] = (1 - self.alpha) * self.share[team] + self.alpha * s
                self.n[team] += 1
        return self

    def rally_prob(self, home: str, away: str) -> float:
        q = 0.5 + (self.share[home] - 0.5) - (self.share[away] - 0.5) + self.home_edge
        return float(np.clip(q, 0.3, 0.7))

    def outcomes(self, home: str, away: str, n: int = 20000, seed: int = 0) -> Outcomes:
        rng = np.random.default_rng(seed)
        q = self.rally_prob(home, away)
        sets_h = np.zeros(n, int)
        sets_a = np.zeros(n, int)
        pts_h = np.zeros(n, int)
        pts_a = np.zeros(n, int)
        for s in range(5):
            active = (sets_h < 3) & (sets_a < 3)
            if not active.any():
                break
            target = 15 if s == 4 else 25
            x = np.zeros(n, int)
            y = np.zeros(n, int)
            done = ~active
            for _ in range(200):
                live = ~done
                if not live.any():
                    break
                w = rng.random(n) < q
                x += live & w
                y += live & ~w
                done |= ((x >= target) | (y >= target)) & (np.abs(x - y) >= 2)
            sets_h += active & (x > y)
            sets_a += active & (y > x)
            pts_h += np.where(active, x, 0)
            pts_a += np.where(active, y, 0)
        return Outcomes("volleyball", {"home_sets": sets_h, "away_sets": sets_a, "home_points": pts_h,
                                       "away_points": pts_a, "home": sets_h, "away": sets_a}, np.ones(n),
                        meta={"rally_prob_home": q,
                              "data_quality": {"games_home": self.n[home], "games_away": self.n[away]}})
