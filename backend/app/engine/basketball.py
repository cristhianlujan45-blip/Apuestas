"""Baloncesto: ratings ofensivo/defensivo por posesión, ritmo y Four Factors.

* Posesiones (Oliver): FGA + 0.44·FTA − 1.07·ORB%·(FGA − FGM) + TOV.
* ORtg/DRtg ajustados por rival mediante regresión ridge ponderada en el
  tiempo sobre puntos por 100 posesiones; ritmo log-aditivo por equipo.
* Puntos simulados con normal bivariante (correlación por ritmo) y prórrogas.
* Props de jugador: tasas por minuto con media exponencial y binomial negativa.

Si no hay estadísticas de caja, el modelo cae a un modelo de puntos sin
posesiones (se indica en ``data_quality``).
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np
import pandas as pd

from .markets import Outcomes

BOX = ["fga", "fgm", "fg3a", "fg3m", "fta", "ftm", "orb", "drb", "tov"]


def possessions(df: pd.DataFrame) -> pd.Series | None:
    need = [f"{s}_{c}" for s in ("h", "a") for c in BOX]
    if not all(c in df.columns for c in need) or df[need].isna().all().any():
        return None

    def side(s: str, o: str) -> pd.Series:
        orb_pct = df[f"{s}_orb"] / (df[f"{s}_orb"] + df[f"{o}_drb"]).replace(0, np.nan)
        return (df[f"{s}_fga"] + 0.4 * df[f"{s}_fta"] - 1.07 * orb_pct * (df[f"{s}_fga"] - df[f"{s}_fgm"])
                + df[f"{s}_tov"])

    return 0.5 * (side("h", "a") + side("a", "h"))


def four_factors(df: pd.DataFrame, side: str, opp: str) -> pd.DataFrame:
    return pd.DataFrame({
        "efg": (df[f"{side}_fgm"] + 0.5 * df[f"{side}_fg3m"]) / df[f"{side}_fga"],
        "tov_pct": df[f"{side}_tov"] / (df[f"{side}_fga"] + 0.44 * df[f"{side}_fta"] + df[f"{side}_tov"]),
        "orb_pct": df[f"{side}_orb"] / (df[f"{side}_orb"] + df[f"{opp}_drb"]),
        "ftr": df[f"{side}_ftm"] / df[f"{side}_fga"],
    })


@dataclass
class BasketballModel:
    xi: float = 0.008       # decaimiento diario (vida media ≈ 87 días)
    ridge: float = 4.0
    teams: list[str] = field(default_factory=list)
    mu: float = 110.0       # puntos por 100 posesiones (o por partido si no hay caja)
    hca: float = 2.5
    off: np.ndarray | None = None
    deff: np.ndarray | None = None
    pace_c: float = 0.0
    pace: np.ndarray | None = None
    uses_possessions: bool = False
    sigma: float = 12.0
    rho: float = 0.3
    factors: dict = field(default_factory=dict)
    n_games: int = 0

    def fit(self, df: pd.DataFrame, ref_date: datetime) -> "BasketballModel":
        df = df[pd.to_datetime(df["date"]).dt.tz_localize(None) < pd.Timestamp(ref_date).tz_localize(None)]
        df = df.dropna(subset=["hpts", "apts"]).reset_index(drop=True)
        if len(df) < 40:
            raise ValueError("Datos insuficientes de baloncesto (mínimo 40 partidos)")
        teams = sorted(set(df["home"]) | set(df["away"]))
        idx = {t: i for i, t in enumerate(teams)}
        n, k = len(df), len(teams)
        hi, ai = df["home"].map(idx).to_numpy(), df["away"].map(idx).to_numpy()
        days = (pd.Timestamp(ref_date).tz_localize(None) - pd.to_datetime(df["date"]).dt.tz_localize(None)).dt.days
        w = np.exp(-self.xi * days.to_numpy(float))
        poss = possessions(df)
        self.uses_possessions = poss is not None and poss.notna().mean() > 0.8
        if self.uses_possessions:
            poss = poss.fillna(poss.median()).to_numpy(float)
            yh = 100 * df["hpts"].to_numpy(float) / poss
            ya = 100 * df["apts"].to_numpy(float) / poss
        else:
            poss = None
            yh, ya = df["hpts"].to_numpy(float), df["apts"].to_numpy(float)
        # Diseño: [mu, hca, off(k), def(k)]
        X = np.zeros((2 * n, 2 + 2 * k))
        X[:, 0] = 1
        X[:n, 1], X[n:, 1] = 0.5, -0.5
        X[np.arange(n), 2 + hi] = 1
        X[np.arange(n), 2 + k + ai] = 1
        X[n + np.arange(n), 2 + ai] = 1
        X[n + np.arange(n), 2 + k + hi] = 1
        y = np.concatenate([yh, ya])
        ww = np.sqrt(np.concatenate([w, w]))
        R = np.zeros((2 * k, 2 + 2 * k))
        R[:, 2:] = np.sqrt(self.ridge) * np.eye(2 * k)
        A = np.vstack([X * ww[:, None], R])
        b = np.concatenate([y * ww, np.zeros(2 * k)])
        beta, *_ = np.linalg.lstsq(A, b, rcond=None)
        self.mu, self.hca = float(beta[0]), float(beta[1])
        self.off, self.deff = beta[2:2 + k], beta[2 + k:]
        self.teams = teams
        if poss is not None:
            P = np.zeros((n, 1 + k))
            P[:, 0] = 1
            P[np.arange(n), 1 + hi] += 1
            P[np.arange(n), 1 + ai] += 1
            Rp = np.zeros((k, 1 + k))
            Rp[:, 1:] = np.sqrt(self.ridge * 0.01) * np.eye(k)
            Ap = np.vstack([P * np.sqrt(w)[:, None], Rp])
            bp = np.concatenate([np.log(poss) * np.sqrt(w), np.zeros(k)])
            gp, *_ = np.linalg.lstsq(Ap, bp, rcond=None)
            self.pace_c, self.pace = float(gp[0]), gp[1:]
        # Residuales en puntos
        ph, pa = np.array([self._means(teams[i], teams[j]) for i, j in zip(hi, ai)]).T
        rh = df["hpts"].to_numpy(float) - ph
        ra = df["apts"].to_numpy(float) - pa
        self.sigma = float(np.sqrt(np.average(np.concatenate([rh, ra]) ** 2, weights=np.concatenate([w, w]))))
        self.rho = float(np.clip(np.corrcoef(rh, ra)[0, 1], -0.2, 0.8))
        self.n_games = n
        if all(f"h_{c}" in df.columns for c in BOX):
            self._fit_factors(df, w)
        return self

    def _fit_factors(self, df: pd.DataFrame, w: np.ndarray) -> None:
        acc: dict[str, dict] = defaultdict(lambda: defaultdict(list))
        fh, fa = four_factors(df, "h", "a"), four_factors(df, "a", "h")
        for i, row in df.iterrows():
            for team, own, opp in ((row["home"], fh.iloc[i], fa.iloc[i]), (row["away"], fa.iloc[i], fh.iloc[i])):
                for kf in own.index:
                    acc[team][f"off_{kf}"].append((own[kf], w[i]))
                    acc[team][f"def_{kf}"].append((opp[kf], w[i]))
        self.factors = {
            t: {kf: float(np.average([v for v, _ in vals], weights=[ww for _, ww in vals]))
                for kf, vals in d.items() if vals and not any(pd.isna(v) for v, _ in vals)}
            for t, d in acc.items()
        }

    def _means(self, home: str, away: str) -> tuple[float, float]:
        idx = {t: i for i, t in enumerate(self.teams)}
        g = lambda arr, t: float(arr[idx[t]]) if t in idx else 0.0  # noqa: E731
        rh = self.mu + self.hca / 2 + g(self.off, home) + g(self.deff, away)
        ra = self.mu - self.hca / 2 + g(self.off, away) + g(self.deff, home)
        if self.uses_possessions and self.pace is not None:
            poss = math.exp(self.pace_c + g(self.pace, home) + g(self.pace, away))
            return rh * poss / 100, ra * poss / 100
        return rh, ra

    def predict(self, home: str, away: str) -> dict:
        mh, ma = self._means(home, away)
        quality = {"home_known": home in self.teams, "away_known": away in self.teams,
                   "uses_possessions": self.uses_possessions, "n_games": self.n_games}
        idx = {t: i for i, t in enumerate(self.teams)}
        pace = None
        if self.pace is not None:
            pace = math.exp(self.pace_c + (self.pace[idx[home]] if home in idx else 0)
                            + (self.pace[idx[away]] if away in idx else 0))
        return {"mean_home": mh, "mean_away": ma, "sigma": self.sigma, "rho": self.rho,
                "pace": pace, "factors": {"home": self.factors.get(home), "away": self.factors.get(away)},
                "data_quality": quality}

    def outcomes(self, home: str, away: str, n: int = 20000, seed: int = 0,
                 players: dict[str, dict] | None = None) -> Outcomes:
        p = self.predict(home, away)
        rng = np.random.default_rng(seed)
        cov = np.array([[1, p["rho"]], [p["rho"], 1]]) * p["sigma"] ** 2
        pts = rng.multivariate_normal([p["mean_home"], p["mean_away"]], cov, size=n)
        h, a = np.rint(pts[:, 0]), np.rint(pts[:, 1])
        ot_frac = 5 / 48
        for _ in range(4):  # prórrogas
            tie = h == a
            if not tie.any():
                break
            m = int(tie.sum())
            ot = rng.multivariate_normal([p["mean_home"] * ot_frac, p["mean_away"] * ot_frac],
                                         cov * ot_frac, size=m)
            h[tie] += np.rint(ot[:, 0])
            a[tie] += np.rint(ot[:, 1])
        tie = h == a
        if tie.any():  # desempate final aleatorio proporcional a la fuerza
            coin = rng.random(int(tie.sum())) < (p["mean_home"] / (p["mean_home"] + p["mean_away"]))
            h[tie] += np.where(coin, 1, 0)
            a[tie] += np.where(coin, 0, 1)
        values = {"home": h, "away": a}
        for player, pp in (players or {}).items():
            for stat, (mean, disp) in pp.items():
                if disp <= 1e-6:
                    values[f"player:{player}:{stat}"] = rng.poisson(mean, n)
                else:
                    r = 1 / disp
                    values[f"player:{player}:{stat}"] = rng.negative_binomial(r, r / (r + mean), n)
        return Outcomes("basketball", values, np.ones(n), meta={"prediction": p})


@dataclass
class PlayerPropsModel:
    """Tasas por minuto (media exponencial) + minutos proyectados."""

    alpha: float = 0.15
    stats: tuple[str, ...] = ("points", "rebounds", "assists", "threes")
    state: dict = field(default_factory=dict)

    def fit(self, df: pd.DataFrame, ref_date: datetime) -> "PlayerPropsModel":
        df = df[pd.to_datetime(df["date"]).dt.tz_localize(None) < pd.Timestamp(ref_date).tz_localize(None)]
        df = df.sort_values("date", kind="mergesort")
        for row in df.to_dict("records"):
            if not row.get("minutes") or row["minutes"] <= 0:
                continue
            key = (row["team"], row["player"])
            st = self.state.setdefault(key, {"minutes": row["minutes"], "n": 0,
                                             **{s: None for s in self.stats}, "resid": {s: [] for s in self.stats}})
            st["minutes"] = (1 - self.alpha) * st["minutes"] + self.alpha * row["minutes"]
            for s in self.stats:
                v = row.get(s)
                if v is None or pd.isna(v):
                    continue
                rate = v / row["minutes"]
                if st[s] is not None:
                    st["resid"][s].append((v, st[s] * row["minutes"]))
                st[s] = rate if st[s] is None else (1 - self.alpha) * st[s] + self.alpha * rate
            st["n"] += 1
        return self

    def projection(self, team: str, player: str, minutes: float | None = None) -> dict[str, tuple[float, float]]:
        st = self.state.get((team, player))
        if not st or st["n"] < 5:
            return {}
        mins = minutes or st["minutes"]
        out = {}
        for s in self.stats:
            if st[s] is None:
                continue
            mean = st[s] * mins
            res = st["resid"][s][-40:]
            if len(res) >= 10:
                v = np.array([x for x, _ in res])
                m = np.array([y for _, y in res])
                disp = max(0.0, float(np.mean((v - m) ** 2 - m) / max(np.mean(m ** 2), 1e-6)))
            else:
                disp = 0.1
            out[s] = (float(mean), disp)
        return out

    def team_players(self, team: str, min_games: int = 5) -> list[str]:
        return [p for (t, p), st in self.state.items() if t == team and st["n"] >= min_games]
