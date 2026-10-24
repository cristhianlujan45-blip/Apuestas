"""Motor de predicción de fútbol: combina modelos estadísticos y de ML.

Componentes (todos entrenados con datos reales anteriores a la fecha de
referencia):

* Dixon-Coles MAP con aproximación de Laplace (incertidumbre de parámetros)
* Poisson independiente
* Poisson bivariado
* Elo con margen de goles + logit ordenado
* Glicko-2 + logit ordenado
* Clasificadores de ML (LogReg, RF, LightGBM, XGBoost, CatBoost, MLP PyTorch)
* Mercado (cuotas de referencia sin margen), cuando existen

El ensemble usa pesos estimados con validación temporal. La matriz de
marcadores de Dixon-Coles se recalibra a las probabilidades 1X2 del ensemble
para derivar todos los mercados de goles de forma coherente.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from ..markets import Outcomes
from ..ml import ML_MODELS, combine, fit_predict
from ..odds_math import devig
from ..ratings import OrderedLogit
from .features import FEATURE_COLUMNS, MARKET_COLUMNS, FeatureBuilder, build_training_table
from .goals import (
    MAX_GOALS,
    BivariatePoissonModel,
    TeamRatingModel,
    calibrate_matrix,
    matrix_from_rates,
    outcome_probs,
)

log = logging.getLogger(__name__)

# Agrupación por país: los equipos ascendidos/descendidos conectan las
# divisiones y permiten estimar fuerzas comparables.
LEAGUE_GROUPS = {
    "ENG": ["E0", "E1", "E2", "E3", "EC"], "ESP": ["SP1", "SP2"], "ITA": ["I1", "I2"],
    "GER": ["D1", "D2"], "FRA": ["F1", "F2"], "SCO": ["SC0", "SC1", "SC2", "SC3"],
    "NED": ["N1"], "BEL": ["B1"], "POR": ["P1"], "TUR": ["T1"], "GRE": ["G1"],
    "ARG": ["ARG"], "BRA": ["BRA"], "MEX": ["MEX"], "USA": ["USA"], "CHN": ["CHN"], "JPN": ["JPN"],
    "COL": ["COL"],
}
LEAGUE_TO_GROUP = {lg: g for g, lgs in LEAGUE_GROUPS.items() for lg in lgs}

COUNT_STATS = {
    "corners": ("hc", "ac"),
    "cards": ("hcards", "acards"),
    "shots": ("hs", "as"),
    "sot": ("hst", "ast"),
}

DEFAULT_WEIGHTS = {"dixon_coles": 0.25, "elo": 0.1, "lightgbm": 0.15, "logreg": 0.15, "market": 0.35}


def group_of(league: str) -> str:
    return LEAGUE_TO_GROUP.get(league, league)


@dataclass
class FootballPrediction:
    league: str
    home: str
    away: str
    kickoff: datetime | None
    components: dict[str, list[float]]
    weights: dict[str, float]
    probs: np.ndarray
    matrix: np.ndarray
    exp_goals: tuple[float, float]
    count_params: dict[str, dict]
    uncertainty: dict[str, list[float]]
    data_quality: dict
    model_version: str
    draws_matrices: list[np.ndarray] = field(default_factory=list)

    # ------------------------------------------------------------ resultados
    def grid_outcomes(self) -> Outcomes:
        n = self.matrix.shape[0]
        h, a = np.meshgrid(np.arange(n), np.arange(n), indexing="ij")
        return Outcomes("football", {"home": h.ravel(), "away": a.ravel()}, self.matrix.ravel(), exact=True)

    def sample_outcomes(self, n: int = 20000, seed: int = 0) -> Outcomes:
        """Muestras Monte Carlo conjuntas (goles + conteos) para combinadas."""
        rng = np.random.default_rng(seed)
        flat = self.matrix.ravel()
        idx = rng.choice(len(flat), size=n, p=flat / flat.sum())
        size = self.matrix.shape[0]
        values = {"home": idx // size, "away": idx % size}
        for stat, p in self.count_params.items():
            for side in ("home", "away"):
                values[f"{stat}_{side}"] = _nb_sample(rng, p[side], p["dispersion"], n)
        return Outcomes("football", values, np.ones(n), exact=False)

    def summary(self) -> dict:
        lam, mu = self.exp_goals
        n = self.matrix.shape[0]
        top = np.dstack(np.unravel_index(np.argsort(self.matrix.ravel())[::-1][:8], self.matrix.shape))[0]
        totals = np.zeros(2 * n - 1)
        for i in range(n):
            for j in range(n):
                totals[i + j] += self.matrix[i, j]
        return {
            "league": self.league, "home": self.home, "away": self.away,
            "kickoff": self.kickoff.isoformat() if self.kickoff else None,
            "probs": {"home": float(self.probs[0]), "draw": float(self.probs[1]), "away": float(self.probs[2])},
            "components": self.components, "weights": self.weights,
            "expected_goals": {"home": lam, "away": mu},
            "top_scores": [{"score": f"{i}-{j}", "p": float(self.matrix[i, j])} for i, j in top],
            "total_goals_dist": [float(x) for x in totals[:11]],
            "counts": self.count_params,
            "uncertainty": self.uncertainty,
            "data_quality": self.data_quality,
            "model_version": self.model_version,
        }


def _nb_sample(rng: np.random.Generator, mean: float, dispersion: float, n: int) -> np.ndarray:
    if dispersion <= 1e-6:
        return rng.poisson(mean, n)
    r = 1.0 / dispersion
    p = r / (r + mean)
    return rng.negative_binomial(r, p, n)


class FootballEngine:
    def __init__(self, ml_models: list[str] | None = None, fit_bivariate: bool = True,
                 laplace: bool = True, weights: dict[str, float] | None = None,
                 weights_no_market: dict[str, float] | None = None):
        self.ml_models = ml_models if ml_models is not None else ["logreg", "lightgbm"]
        self.fit_bivariate = fit_bivariate
        self.laplace = laplace
        self.weights = weights or dict(DEFAULT_WEIGHTS)
        self.weights_no_market = weights_no_market or {k: v for k, v in DEFAULT_WEIGHTS.items() if k != "market"}
        self.dc: dict[str, TeamRatingModel] = {}
        self.poisson: dict[str, TeamRatingModel] = {}
        self.bivariate: dict[str, BivariatePoissonModel] = {}
        self.counts: dict[str, dict[str, TeamRatingModel]] = {}
        self.fb: FeatureBuilder | None = None
        self.elo_logit = OrderedLogit()
        self.glicko_logit = OrderedLogit()
        self.ml: dict[str, object] = {}
        self.ml_columns: dict[str, list[str]] = {}
        self.ref_date: datetime | None = None
        self.version = "unfitted"
        self.history_size = 0

    # ---------------------------------------------------------------- ajuste
    def fit(self, history: pd.DataFrame, ref_date: datetime | None = None,
            groups: list[str] | None = None) -> "FootballEngine":
        ref_date = ref_date or datetime.now(timezone.utc)
        hist = history[pd.to_datetime(history["date"]) < pd.Timestamp(ref_date)].dropna(subset=["hg", "ag"])
        self.ref_date = ref_date
        self.history_size = len(hist)
        hist = hist.assign(group=hist["league"].map(group_of))
        target_groups = groups or sorted(hist["group"].unique())
        window_start = pd.Timestamp(ref_date) - pd.Timedelta(days=730)
        for g in target_groups:
            d = hist[(hist["group"] == g) & (pd.to_datetime(hist["date"]) >= window_start)]
            if len(d) < 60:
                continue
            try:
                dc = TeamRatingModel(name="dixon_coles", use_rho=True, compute_cov=self.laplace)
                self.dc[g] = dc.fit(d, ref_date)
                self.poisson[g] = TeamRatingModel(name="poisson", use_rho=False, compute_cov=False).fit(d, ref_date)
                if self.fit_bivariate:
                    self.bivariate[g] = BivariatePoissonModel().fit(d, ref_date)
            except ValueError as exc:
                log.info("Grupo %s sin datos suficientes: %s", g, exc)
                continue
            self.counts[g] = {}
            for stat, (ch, ca) in COUNT_STATS.items():
                ds = d.dropna(subset=[ch, ca])
                if len(ds) < 60:
                    continue
                m = TeamRatingModel(name=f"{stat}_model", use_rho=False, prior_sd=0.3, compute_cov=False)
                self.counts[g][stat] = m.fit(ds, ref_date, y_home=ch, y_away=ca)

        # Ratings secuenciales + variables de ML sobre todo el histórico
        table, fb = build_training_table(hist)
        self.fb = fb
        self.elo_logit.fit(table["elo_diff"].to_numpy(), table["result"].to_numpy())
        self.glicko_logit.fit((table["glicko_exp"].to_numpy() - 0.5) * 1000, table["result"].to_numpy())
        for name in self.ml_models:
            base = name.removesuffix("_mkt")
            cols = FEATURE_COLUMNS + (MARKET_COLUMNS if name.endswith("_mkt") else [])
            t = table.dropna(subset=MARKET_COLUMNS) if name.endswith("_mkt") else table
            if len(t) < 300:
                continue
            model, _ = fit_predict(base, t[cols].to_numpy(float), t["result"].to_numpy(), t[cols].to_numpy(float)[:1])
            self.ml[name] = model
            self.ml_columns[name] = cols
        self.version = f"football-{pd.Timestamp(ref_date).strftime('%Y%m%d')}-{len(hist)}"
        return self

    # ------------------------------------------------------------ predicción
    def predict(self, league: str, home: str, away: str, kickoff: datetime | None = None,
                market_odds: tuple[float, float, float] | None = None, n_draws: int = 200,
                seed: int = 0) -> FootballPrediction:
        g = group_of(league)
        components: dict[str, list[float]] = {}
        quality = {"group": g, "issues": []}
        dc = self.dc.get(g)
        matrix = None
        exp_goals = (math.nan, math.nan)
        draws: list[np.ndarray] = []
        unc: dict[str, list[float]] = {}
        if dc is not None:
            known_h, known_a = dc.knows(home), dc.knows(away)
            quality["home_known"], quality["away_known"] = known_h, known_a
            if not known_h:
                quality["issues"].append(f"{home}: sin historial en el modelo de goles")
            if not known_a:
                quality["issues"].append(f"{away}: sin historial en el modelo de goles")
            matrix = dc.score_matrix(home, away)
            exp_goals = dc.rates(home, away)
            components["dixon_coles"] = outcome_probs(matrix).tolist()
            pm = self.poisson.get(g)
            if pm is not None:
                components["poisson"] = outcome_probs(pm.score_matrix(home, away)).tolist()
            bp = self.bivariate.get(g)
            if bp is not None:
                components["bivariate_poisson"] = outcome_probs(bp.score_matrix(home, away)).tolist()
            if dc.cov is not None and n_draws > 0:
                rng = np.random.default_rng(seed)
                thetas = dc.posterior_draws(n_draws, rng)
                for th in thetas:
                    draws.append(dc.score_matrix(home, away, th))
        else:
            quality["issues"].append(f"Sin modelo de goles para el grupo {g}")

        if self.fb is not None:
            date = pd.Timestamp(kickoff or self.ref_date).tz_localize(None) if (kickoff or self.ref_date) else pd.Timestamp.now()
            feats = self.fb.features_for(home, away, date, market_odds)
            components["elo"] = self.elo_logit.probs(feats["elo_diff"]).tolist()
            components["glicko2"] = self.glicko_logit.probs((feats["glicko_exp"] - 0.5) * 1000).tolist()
            quality["games_home"] = int(feats["exp_home"])
            quality["games_away"] = int(feats["exp_away"])
            for name, model in self.ml.items():
                cols = self.ml_columns[name]
                x = np.array([[feats[c] for c in cols]], dtype=float)
                if name.endswith("_mkt") and np.isnan(x[0, -3:]).any():
                    continue
                p = np.clip(model.predict_proba(x)[0], 1e-6, 1)
                components[name] = (p / p.sum()).tolist()
        if market_odds is not None and all(o and o > 1 for o in market_odds):
            components["market"] = devig(list(market_odds), "power").tolist()

        wset = self.weights if "market" in components else self.weights_no_market
        avail = {k: w for k, w in wset.items() if k in components and w > 1e-4}
        if not avail:
            avail = {k: 1.0 for k in components}
        total = sum(avail.values())
        weights = {k: v / total for k, v in avail.items()}
        probs = combine([np.array(components[k]) for k in weights], np.array(list(weights.values())))

        if matrix is None:
            # Sin modelo de goles: matriz Poisson con tasas medias calibrada al ensemble
            matrix = matrix_from_rates(1.45, 1.15)
            quality["issues"].append("Matriz de marcadores genérica (baja confianza en mercados de goles)")
        calibrated = calibrate_matrix(matrix, probs)
        if draws:
            ratio = calibrated / np.clip(matrix, 1e-15, None)
            cal_draws = []
            for m in draws:
                cm = m * ratio
                cal_draws.append(cm / cm.sum())
            draws = cal_draws
            stacked = np.array([outcome_probs(m) for m in draws])
            over25 = np.array([1 - sum(m[i, j] for i in range(3) for j in range(3 - i)) for m in draws])
            unc = {
                "home": [float(np.percentile(stacked[:, 0], 10)), float(np.percentile(stacked[:, 0], 90))],
                "draw": [float(np.percentile(stacked[:, 1], 10)), float(np.percentile(stacked[:, 1], 90))],
                "away": [float(np.percentile(stacked[:, 2], 10)), float(np.percentile(stacked[:, 2], 90))],
                "over_2_5": [float(np.percentile(over25, 10)), float(np.percentile(over25, 90))],
            }

        count_params: dict[str, dict] = {}
        for stat, cm in self.counts.get(g, {}).items():
            lh, la = cm.rates(home, away)
            count_params[stat] = {"home": lh, "away": la, "dispersion": cm.dispersion}
        if not count_params:
            quality["issues"].append("Sin estadísticas de córners/tarjetas/tiros para esta liga")

        quality["sufficient"] = (dc is not None and quality.get("home_known", False)
                                 and quality.get("away_known", False)
                                 and quality.get("games_home", 0) >= 5 and quality.get("games_away", 0) >= 5)
        return FootballPrediction(
            league=league, home=home, away=away, kickoff=kickoff, components=components, weights=weights,
            probs=probs, matrix=calibrated, exp_goals=exp_goals, count_params=count_params,
            uncertainty=unc, data_quality=quality, model_version=self.version, draws_matrices=draws,
        )


def matrix_total_goals_quantiles(matrix: np.ndarray) -> dict:
    n = matrix.shape[0]
    tot = np.zeros(2 * n - 1)
    for i in range(n):
        for j in range(n):
            tot[i + j] += matrix[i, j]
    c = np.cumsum(tot)
    q = lambda p: int(np.searchsorted(c, p))  # noqa: E731
    return {"p10": q(0.1), "p50": q(0.5), "p90": q(0.9), "mean": float(np.dot(np.arange(len(tot)), tot))}


__all__ = ["FootballEngine", "FootballPrediction", "LEAGUE_GROUPS", "group_of", "MAX_GOALS", "ML_MODELS"]
