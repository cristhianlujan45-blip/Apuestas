"""Modelos de goles: Poisson, Dixon-Coles (MAP bayesiano) y Poisson bivariado.

* Fuerzas ofensivas/defensivas log-lineales con ventaja de localía.
* Ponderación temporal exponencial (Dixon & Coles, 1997).
* Prior normal sobre las fuerzas (equivale a regularización ridge) → el
  ajuste es un MAP bayesiano y la inversa del Hessiano da una aproximación
  de Laplace a la posterior, que se usa para intervalos de incertidumbre.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.special import gammaln

MAX_GOALS = 10


def _days_before(dates: pd.Series, ref: datetime) -> np.ndarray:
    d = (pd.Timestamp(ref).tz_localize(None) - pd.to_datetime(dates).dt.tz_localize(None)).dt.days
    return np.clip(d.to_numpy(dtype=float), 0, None)


def dc_tau_matrix(lam: float, mu: float, rho: float, n: int = MAX_GOALS + 1) -> np.ndarray:
    tau = np.ones((n, n))
    tau[0, 0] = 1 - lam * mu * rho
    tau[0, 1] = 1 + lam * rho
    tau[1, 0] = 1 + mu * rho
    tau[1, 1] = 1 - rho
    return np.clip(tau, 1e-10, None)


def poisson_pmf_vec(lam: float, n: int = MAX_GOALS + 1) -> np.ndarray:
    k = np.arange(n)
    return np.exp(k * math.log(max(lam, 1e-12)) - lam - gammaln(k + 1))


@dataclass
class TeamRatingModel:
    """Modelo log-lineal de conteos por equipo (goles, córners, tarjetas...).

    ``use_rho=True`` activa la corrección Dixon-Coles para marcadores bajos.
    """

    name: str = "dixon_coles"
    xi: float = 0.0019
    prior_sd: float = 0.5
    use_rho: bool = True
    teams: list[str] = field(default_factory=list)
    attack: np.ndarray | None = None
    defense: np.ndarray | None = None
    home_adv: float = 0.0
    intercept: float = 0.0
    rho: float = 0.0
    cov: np.ndarray | None = None
    n_matches: int = 0
    fitted_at: datetime | None = None
    dispersion: float = 0.0  # para binomial negativa en conteos no-goles
    compute_cov: bool = True

    # -------------------------------------------------------------- ajuste
    def fit(self, df: pd.DataFrame, ref_date: datetime, y_home: str = "hg", y_away: str = "ag") -> "TeamRatingModel":
        df = df.dropna(subset=[y_home, y_away])
        df = df[pd.to_datetime(df["date"]).dt.tz_localize(None) < pd.Timestamp(ref_date).tz_localize(None)]
        if len(df) < 30:
            raise ValueError("Datos insuficientes para ajustar el modelo (mínimo 30 partidos)")
        teams = sorted(set(df["home"]) | set(df["away"]))
        idx = {t: i for i, t in enumerate(teams)}
        hi = df["home"].map(idx).to_numpy()
        ai = df["away"].map(idx).to_numpy()
        x = df[y_home].to_numpy(dtype=float)
        y = df[y_away].to_numpy(dtype=float)
        w = np.exp(-self.xi * _days_before(df["date"], ref_date))
        n = len(teams)
        lam_prior = 1.0 / (2 * self.prior_sd ** 2)
        use_rho = self.use_rho

        m00 = (x == 0) & (y == 0)
        m01 = (x == 0) & (y == 1)
        m10 = (x == 1) & (y == 0)
        m11 = (x == 1) & (y == 1)
        lgx = gammaln(x + 1) + gammaln(y + 1)

        def unpack(theta: np.ndarray):
            att = theta[:n]
            de = theta[n:2 * n]
            home, c = theta[2 * n], theta[2 * n + 1]
            rho = theta[2 * n + 2] if use_rho else 0.0
            return att, de, home, c, rho

        def nll_grad(theta: np.ndarray):
            att, de, home, c, rho = unpack(theta)
            ll_l = att[hi] + de[ai] + home + c
            ll_m = att[ai] + de[hi] + c
            lam = np.exp(ll_l)
            mu = np.exp(ll_m)
            ll = x * ll_l - lam + y * ll_m - mu - lgx
            g_l = x - lam  # d ll / d log λ
            g_m = y - mu
            g_rho = np.zeros_like(lam)
            if use_rho:
                tau = np.ones_like(lam)
                tau[m00] = 1 - lam[m00] * mu[m00] * rho
                tau[m01] = 1 + lam[m01] * rho
                tau[m10] = 1 + mu[m10] * rho
                tau[m11] = 1 - rho
                tau = np.clip(tau, 1e-10, None)
                ll = ll + np.log(tau)
                g_l[m00] += -lam[m00] * mu[m00] * rho / tau[m00]
                g_m[m00] += -lam[m00] * mu[m00] * rho / tau[m00]
                g_rho[m00] = -lam[m00] * mu[m00] / tau[m00]
                g_l[m01] += lam[m01] * rho / tau[m01]
                g_rho[m01] = lam[m01] / tau[m01]
                g_m[m10] += mu[m10] * rho / tau[m10]
                g_rho[m10] = mu[m10] / tau[m10]
                g_rho[m11] = -1 / tau[m11]
            f = -np.sum(w * ll) + lam_prior * (np.sum(att ** 2) + np.sum(de ** 2))
            wl, wm = w * g_l, w * g_m
            g_att = -(np.bincount(hi, wl, n) + np.bincount(ai, wm, n)) + 2 * lam_prior * att
            g_def = -(np.bincount(ai, wl, n) + np.bincount(hi, wm, n)) + 2 * lam_prior * de
            g_home = -np.sum(wl)
            g_c = -np.sum(wl + wm)
            grad = [g_att, g_def, [g_home, g_c]]
            if use_rho:
                grad.append([-np.sum(w * g_rho)])
            return f, np.concatenate(grad)

        base = math.log(max((np.average(x, weights=w) + np.average(y, weights=w)) / 2, 0.05))
        theta0 = np.zeros(2 * n + 2 + (1 if use_rho else 0))
        theta0[2 * n] = 0.2
        theta0[2 * n + 1] = base
        bounds = [(-3, 3)] * (2 * n) + [(-1, 1), (-5, 5)] + ([(-0.3, 0.3)] if use_rho else [])
        res = minimize(nll_grad, theta0, jac=True, method="L-BFGS-B", bounds=bounds,
                       options={"maxiter": 2000})
        theta = res.x
        att, de, home, c, rho = unpack(theta)
        self.teams = teams
        self.attack, self.defense = att.copy(), de.copy()
        self.home_adv, self.intercept, self.rho = float(home), float(c), float(rho)
        self.n_matches = int(len(df))
        self.fitted_at = ref_date
        self.cov = self._laplace_cov(nll_grad, theta) if self.compute_cov else None

        # Dispersión (binomial negativa) por método de momentos
        lam = np.exp(att[hi] + de[ai] + home + c)
        mu = np.exp(att[ai] + de[hi] + c)
        resid = np.concatenate([(x - lam) ** 2 - lam, (y - mu) ** 2 - mu])
        means2 = np.concatenate([lam ** 2, mu ** 2])
        ww = np.concatenate([w, w])
        self.dispersion = float(max(0.0, np.sum(ww * resid) / np.sum(ww * means2)))
        return self

    @staticmethod
    def _laplace_cov(nll_grad, theta: np.ndarray) -> np.ndarray | None:
        """Hessiano numérico del gradiente analítico → covarianza posterior."""
        k = len(theta)
        h = 1e-4
        H = np.zeros((k, k))
        for i in range(k):
            e = np.zeros(k)
            e[i] = h
            H[i] = (nll_grad(theta + e)[1] - nll_grad(theta - e)[1]) / (2 * h)
        H = (H + H.T) / 2
        try:
            cov = np.linalg.inv(H + 1e-8 * np.eye(k))
            # Asegurar semidefinida positiva
            vals, vecs = np.linalg.eigh(cov)
            vals = np.clip(vals, 1e-10, None)
            return (vecs * vals) @ vecs.T
        except np.linalg.LinAlgError:
            return None

    # ----------------------------------------------------------- predicción
    def _theta(self) -> np.ndarray:
        parts = [self.attack, self.defense, [self.home_adv, self.intercept]]
        if self.use_rho:
            parts.append([self.rho])
        return np.concatenate(parts)

    def knows(self, team: str) -> bool:
        return team in self.teams

    def rates(self, home: str, away: str, theta: np.ndarray | None = None, neutral: bool = False) -> tuple[float, float]:
        n = len(self.teams)
        th = self._theta() if theta is None else theta
        att, de = th[:n], th[n:2 * n]
        hadv, c = th[2 * n], th[2 * n + 1]
        idx = {t: i for i, t in enumerate(self.teams)}
        ah = att[idx[home]] if home in idx else 0.0
        dh = de[idx[home]] if home in idx else 0.0
        aa = att[idx[away]] if away in idx else 0.0
        da = de[idx[away]] if away in idx else 0.0
        lam = math.exp(ah + da + (0 if neutral else hadv) + c)
        mu = math.exp(aa + dh + c)
        return lam, mu

    def score_matrix(self, home: str, away: str, theta: np.ndarray | None = None) -> np.ndarray:
        lam, mu = self.rates(home, away, theta)
        rho = (theta[-1] if (theta is not None and self.use_rho) else self.rho) if self.use_rho else 0.0
        return matrix_from_rates(lam, mu, rho)

    def posterior_draws(self, n_draws: int, rng: np.random.Generator) -> np.ndarray:
        theta = self._theta()
        if self.cov is None:
            return np.repeat(theta[None, :], n_draws, axis=0)
        return rng.multivariate_normal(theta, self.cov, size=n_draws, method="eigh")

    # --------------------------------------------------------- persistencia
    def to_dict(self) -> dict:
        return {
            "name": self.name, "xi": self.xi, "prior_sd": self.prior_sd, "use_rho": self.use_rho,
            "teams": self.teams, "attack": self.attack.tolist(), "defense": self.defense.tolist(),
            "home_adv": self.home_adv, "intercept": self.intercept, "rho": self.rho,
            "cov": None if self.cov is None else self.cov.tolist(), "n_matches": self.n_matches,
            "fitted_at": self.fitted_at.isoformat() if self.fitted_at else None,
            "dispersion": self.dispersion,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "TeamRatingModel":
        m = cls(name=d["name"], xi=d["xi"], prior_sd=d["prior_sd"], use_rho=d["use_rho"])
        m.teams = d["teams"]
        m.attack, m.defense = np.array(d["attack"]), np.array(d["defense"])
        m.home_adv, m.intercept, m.rho = d["home_adv"], d["intercept"], d["rho"]
        m.cov = None if d["cov"] is None else np.array(d["cov"])
        m.n_matches = d["n_matches"]
        m.fitted_at = datetime.fromisoformat(d["fitted_at"]) if d["fitted_at"] else None
        m.dispersion = d.get("dispersion", 0.0)
        return m

    def ratings_table(self) -> list[dict]:
        out = []
        for i, t in enumerate(self.teams):
            out.append({
                "team": t,
                "attack": float(self.attack[i]),
                "defense": float(self.defense[i]),
                "exp_goals_for_vs_avg": math.exp(self.attack[i] + self.intercept + self.home_adv / 2),
                "exp_goals_against_vs_avg": math.exp(self.defense[i] + self.intercept + self.home_adv / 2),
            })
        return sorted(out, key=lambda r: r["attack"] - r["defense"], reverse=True)


def matrix_from_rates(lam: float, mu: float, rho: float = 0.0, n: int = MAX_GOALS + 1) -> np.ndarray:
    m = np.outer(poisson_pmf_vec(lam, n), poisson_pmf_vec(mu, n))
    if rho:
        m = m * dc_tau_matrix(lam, mu, rho, n)
    return m / m.sum()


# ---------------------------------------------------------------------------
# Poisson bivariado (Karlis & Ntzoufras, 2003)
# ---------------------------------------------------------------------------

@dataclass
class BivariatePoissonModel:
    name: str = "bivariate_poisson"
    xi: float = 0.0019
    prior_sd: float = 0.5
    teams: list[str] = field(default_factory=list)
    theta: np.ndarray | None = None
    n_matches: int = 0

    @staticmethod
    def _log_pmf(x: np.ndarray, y: np.ndarray, l1: np.ndarray, l2: np.ndarray, l3: np.ndarray) -> np.ndarray:
        kmax = int(min(x.max(), y.max())) if len(x) else 0
        base = -(l1 + l2 + l3) + x * np.log(l1) - gammaln(x + 1) + y * np.log(l2) - gammaln(y + 1)
        terms = []
        ratio = np.log(l3) - np.log(l1) - np.log(l2)
        for k in range(kmax + 1):
            valid = (x >= k) & (y >= k)
            t = (gammaln(x + 1) - gammaln(x - k + 1) - gammaln(k + 1)
                 + gammaln(y + 1) - gammaln(y - k + 1) + k * ratio)
            terms.append(np.where(valid, t, -np.inf))
        s = np.logaddexp.reduce(np.vstack(terms), axis=0) if terms else 0.0
        return base + s

    def fit(self, df: pd.DataFrame, ref_date: datetime) -> "BivariatePoissonModel":
        df = df.dropna(subset=["hg", "ag"])
        df = df[pd.to_datetime(df["date"]).dt.tz_localize(None) < pd.Timestamp(ref_date).tz_localize(None)]
        if len(df) < 30:
            raise ValueError("Datos insuficientes para el Poisson bivariado")
        # Inicializar con el modelo Poisson independiente (rápido y analítico)
        init = TeamRatingModel(name="poisson", xi=self.xi, prior_sd=self.prior_sd, use_rho=False).fit(df, ref_date)
        teams = init.teams
        idx = {t: i for i, t in enumerate(teams)}
        hi = df["home"].map(idx).to_numpy()
        ai = df["away"].map(idx).to_numpy()
        x = df["hg"].to_numpy(dtype=float)
        y = df["ag"].to_numpy(dtype=float)
        w = np.exp(-self.xi * _days_before(df["date"], ref_date))
        n = len(teams)
        lam_prior = 1.0 / (2 * self.prior_sd ** 2)

        def nll(theta):
            att, de = theta[:n], theta[n:2 * n]
            home, c, c3 = theta[2 * n], theta[2 * n + 1], theta[2 * n + 2]
            l1 = np.exp(att[hi] + de[ai] + home + c)
            l2 = np.exp(att[ai] + de[hi] + c)
            l3 = np.full_like(l1, np.exp(c3))
            return -np.sum(w * self._log_pmf(x, y, l1, l2, l3)) + lam_prior * (np.sum(att ** 2) + np.sum(de ** 2))

        theta0 = np.concatenate([init.attack, init.defense, [init.home_adv, init.intercept - 0.1, math.log(0.1)]])
        bounds = [(-3, 3)] * (2 * n) + [(-1, 1), (-5, 5), (math.log(1e-4), math.log(1.0))]
        res = minimize(nll, theta0, method="L-BFGS-B", bounds=bounds, options={"maxiter": 500})
        self.teams = teams
        self.theta = res.x
        self.n_matches = int(len(df))
        return self

    def rates(self, home: str, away: str) -> tuple[float, float, float]:
        n = len(self.teams)
        th = self.theta
        idx = {t: i for i, t in enumerate(self.teams)}
        att, de = th[:n], th[n:2 * n]
        g = lambda arr, t: arr[idx[t]] if t in idx else 0.0  # noqa: E731
        l1 = math.exp(g(att, home) + g(de, away) + th[2 * n] + th[2 * n + 1])
        l2 = math.exp(g(att, away) + g(de, home) + th[2 * n + 1])
        return l1, l2, math.exp(th[2 * n + 2])

    def score_matrix(self, home: str, away: str, n: int = MAX_GOALS + 1) -> np.ndarray:
        l1, l2, l3 = self.rates(home, away)
        xs, ys = np.meshgrid(np.arange(n), np.arange(n), indexing="ij")
        lp = self._log_pmf(xs.ravel().astype(float), ys.ravel().astype(float),
                           np.full(n * n, l1), np.full(n * n, l2), np.full(n * n, l3))
        m = np.exp(lp).reshape(n, n)
        return m / m.sum()

    def knows(self, team: str) -> bool:
        return team in self.teams

    def to_dict(self) -> dict:
        return {"name": self.name, "xi": self.xi, "prior_sd": self.prior_sd, "teams": self.teams,
                "theta": self.theta.tolist(), "n_matches": self.n_matches}

    @classmethod
    def from_dict(cls, d: dict) -> "BivariatePoissonModel":
        m = cls(name=d["name"], xi=d["xi"], prior_sd=d["prior_sd"])
        m.teams, m.theta, m.n_matches = d["teams"], np.array(d["theta"]), d["n_matches"]
        return m


def outcome_probs(matrix: np.ndarray) -> np.ndarray:
    """[P(local), P(empate), P(visitante)] a partir de la matriz de marcadores."""
    return np.array([np.tril(matrix, -1).sum(), np.trace(matrix), np.triu(matrix, 1).sum()])


def calibrate_matrix(matrix: np.ndarray, target: np.ndarray) -> np.ndarray:
    """Reescala las regiones local/empate/visitante para igualar ``target``.

    Mantiene la forma condicional de los marcadores del modelo de goles y
    hace la matriz coherente con las probabilidades 1X2 del ensemble.
    """
    cur = outcome_probs(matrix)
    m = matrix.copy()
    n = m.shape[0]
    low = np.tril(np.ones((n, n), dtype=bool), -1)
    up = np.triu(np.ones((n, n), dtype=bool), 1)
    diag = np.eye(n, dtype=bool)
    for mask, c, t in ((low, cur[0], target[0]), (diag, cur[1], target[1]), (up, cur[2], target[2])):
        if c > 0:
            m[mask] *= t / c
    return m / m.sum()
