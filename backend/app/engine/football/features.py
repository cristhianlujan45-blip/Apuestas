"""Ingeniería de variables pre-partido para fútbol, sin fuga de información.

Se recorre el histórico en orden cronológico. Para cada partido se calcula
el vector de variables con el estado *anterior* al partido y después se
actualiza el estado con el resultado real.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from functools import partial

import numpy as np
import pandas as pd

from ..odds_math import devig
from ..ratings import Elo, Glicko2

EW_ALPHA = 0.12  # media exponencial ≈ últimos 15 partidos

STAT_PAIRS = {
    "goals": ("hg", "ag"),
    "shots": ("hs", "as"),
    "sot": ("hst", "ast"),
    "corners": ("hc", "ac"),
    "cards": ("hcards", "acards"),
    "xg": ("hxg", "axg"),
}

# Proxy de xG basado en tiros (cuando el proveedor no entrega xG real).
# Coeficientes estimados por mínimos cuadrados sin intercepto sobre la
# primera porción del histórico (ver ``fit_xg_proxy``).
DEFAULT_XG_COEF = (0.29, 0.035)


def fit_xg_proxy(df: pd.DataFrame) -> tuple[float, float]:
    d = df.dropna(subset=["hg", "ag", "hs", "as", "hst", "ast"])
    if len(d) < 200:
        return DEFAULT_XG_COEF
    g = np.concatenate([d["hg"], d["ag"]]).astype(float)
    sot = np.concatenate([d["hst"], d["ast"]]).astype(float)
    off = np.concatenate([d["hs"] - d["hst"], d["as"] - d["ast"]]).astype(float)
    X = np.stack([sot, np.clip(off, 0, None)], axis=1)
    coef, *_ = np.linalg.lstsq(X, g, rcond=None)
    return float(coef[0]), float(max(coef[1], 0.0))


@dataclass
class TeamState:
    ew: dict[str, float] = field(default_factory=dict)
    n: int = 0
    last_date: pd.Timestamp | None = None
    points: deque = field(default_factory=partial(deque, maxlen=5))

    def get(self, key: str, default: float) -> float:
        return self.ew.get(key, default)

    def push(self, key: str, value: float) -> None:
        if value is None or (isinstance(value, float) and np.isnan(value)):
            return
        prev = self.ew.get(key)
        self.ew[key] = value if prev is None else (1 - EW_ALPHA) * prev + EW_ALPHA * value


FEATURE_COLUMNS = [
    "elo_diff", "elo_home", "elo_away", "glicko_exp", "glicko_rd_home", "glicko_rd_away",
    "gf_home", "ga_home", "gf_away", "ga_away",
    "shots_f_home", "shots_a_home", "shots_f_away", "shots_a_away",
    "sot_f_home", "sot_a_home", "sot_f_away", "sot_a_away",
    "xg_f_home", "xg_a_home", "xg_f_away", "xg_a_away",
    "corners_f_home", "corners_a_home", "corners_f_away", "corners_a_away",
    "form_home", "form_away", "rest_home", "rest_away", "exp_home", "exp_away",
]
MARKET_COLUMNS = ["mkt_home", "mkt_draw", "mkt_away"]


class FeatureBuilder:
    def __init__(self, xg_coef: tuple[float, float] = DEFAULT_XG_COEF):
        self.elo = Elo()
        self.glicko = Glicko2()
        self.teams: dict[str, TeamState] = defaultdict(TeamState)
        self.league_avg: dict[str, float] = {}
        self.xg_coef = xg_coef

    def _xg(self, row, side: str) -> float | None:
        real = row.get(f"{side}xg")
        if real is not None and not pd.isna(real):
            return float(real)
        s, st = row.get(f"{side}s"), row.get(f"{side}st")
        if s is None or st is None or pd.isna(s) or pd.isna(st):
            return None
        return self.xg_coef[0] * st + self.xg_coef[1] * max(s - st, 0)

    def features_for(self, home: str, away: str, date: pd.Timestamp, market: tuple | None = None) -> dict:
        th, ta = self.teams[home], self.teams[away]
        avg = lambda k: self.league_avg.get(k, {"goals": 1.35, "shots": 12.5, "sot": 4.4, "xg": 1.35, "corners": 5.0}.get(k, 1.0))  # noqa: E731
        f = {
            "elo_diff": self.elo.diff(home, away),
            "elo_home": self.elo.ratings[home],
            "elo_away": self.elo.ratings[away],
            "glicko_exp": self.glicko.expected(home, away),
            "glicko_rd_home": self.glicko.rd(home),
            "glicko_rd_away": self.glicko.rd(away),
        }
        for stat in ("goals", "shots", "sot", "xg", "corners"):
            pre = {"goals": ("gf", "ga")}.get(stat, (f"{stat}_f", f"{stat}_a"))
            f[f"{pre[0]}_home"] = th.get(f"{stat}_for", avg(stat))
            f[f"{pre[1]}_home"] = th.get(f"{stat}_against", avg(stat))
            f[f"{pre[0]}_away"] = ta.get(f"{stat}_for", avg(stat))
            f[f"{pre[1]}_away"] = ta.get(f"{stat}_against", avg(stat))
        f["form_home"] = float(np.mean(th.points)) if th.points else 1.35
        f["form_away"] = float(np.mean(ta.points)) if ta.points else 1.35
        f["rest_home"] = min(14.0, (date - th.last_date).days) if th.last_date is not None else 7.0
        f["rest_away"] = min(14.0, (date - ta.last_date).days) if ta.last_date is not None else 7.0
        f["exp_home"] = min(th.n, 60)
        f["exp_away"] = min(ta.n, 60)
        if market is not None and all(m and m > 1 for m in market):
            p = devig(list(market), "power")
            f["mkt_home"], f["mkt_draw"], f["mkt_away"] = map(float, p)
        else:
            f["mkt_home"] = f["mkt_draw"] = f["mkt_away"] = np.nan
        return f

    def update(self, row) -> None:
        home, away = row["home"], row["away"]
        hg, ag = row["hg"], row["ag"]
        date = pd.Timestamp(row["date"]).tz_localize(None)
        self.elo.update(home, away, hg, ag)
        self.glicko.update(home, away, hg, ag)
        th, ta = self.teams[home], self.teams[away]
        vals = {
            "goals": (hg, ag),
            "shots": (row.get("hs"), row.get("as")),
            "sot": (row.get("hst"), row.get("ast")),
            "corners": (row.get("hc"), row.get("ac")),
            "xg": (self._xg(row, "h"), self._xg(row, "a")),
        }
        for stat, (vh, va) in vals.items():
            if vh is None or va is None or pd.isna(vh) or pd.isna(va):
                continue
            th.push(f"{stat}_for", float(vh))
            th.push(f"{stat}_against", float(va))
            ta.push(f"{stat}_for", float(va))
            ta.push(f"{stat}_against", float(vh))
            prev = self.league_avg.get(stat)
            m = (float(vh) + float(va)) / 2
            self.league_avg[stat] = m if prev is None else 0.995 * prev + 0.005 * m
        th.points.append(3 if hg > ag else (1 if hg == ag else 0))
        ta.points.append(3 if ag > hg else (1 if hg == ag else 0))
        th.n += 1
        ta.n += 1
        th.last_date = ta.last_date = date


def build_training_table(df: pd.DataFrame) -> tuple[pd.DataFrame, FeatureBuilder]:
    """Variables pre-partido para todo el histórico + estado final del constructor."""
    df = df.sort_values("date", kind="mergesort").reset_index(drop=True)
    cut = max(200, int(len(df) * 0.2))
    fb = FeatureBuilder(fit_xg_proxy(df.iloc[:cut]))
    rows = []
    for row in df.to_dict("records"):
        date = pd.Timestamp(row["date"]).tz_localize(None)
        market = (row.get("odds_h"), row.get("odds_d"), row.get("odds_a"))
        market = None if any(m is None or pd.isna(m) for m in market) else market
        f = fb.features_for(row["home"], row["away"], date, market)
        f.update({
            "match_id": row.get("match_id"), "date": date, "league": row.get("league"),
            "home": row["home"], "away": row["away"], "hg": row["hg"], "ag": row["ag"],
            "result": 0 if row["hg"] > row["ag"] else (1 if row["hg"] == row["ag"] else 2),
        })
        rows.append(f)
        fb.update(row)
    return pd.DataFrame(rows), fb
