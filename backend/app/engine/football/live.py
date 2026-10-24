"""Modelo de fútbol en directo.

Parte de las tasas de gol pre-partido y las actualiza con:

* tiempo restante (incluido añadido estimado),
* marcador actual (los goles restantes se suman al marcador),
* expulsiones (multiplicadores de ataque/defensa),
* rendimiento observado (xG en vivo o, si no hay, proxy por tiros al arco)
  mediante actualización bayesiana Gamma-Poisson de la tasa,
* estado del marcador (el equipo que va perdiendo tiende a atacar más).

Los multiplicadores por expulsión y por estado del marcador son parámetros
configurables con valores de referencia de la literatura (p. ej. Titman et
al., 2015; Vecer et al., 2009). Se documentan como supuestos del modelo.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..markets import Outcomes
from .goals import MAX_GOALS, poisson_pmf_vec

RED_CARD_ATTACK = 0.70     # multiplicador de ataque del equipo con un jugador menos
RED_CARD_CONCEDE = 1.25    # multiplicador de goles concedidos por ese equipo
TRAILING_BOOST = 1.08      # el equipo que pierde aumenta su ritmo ofensivo
LEADING_DAMP = 0.95
PRIOR_STRENGTH_MIN = 30.0  # peso del prior pre-partido en "minutos equivalentes"
SOT_XG = 0.30              # proxy de xG por tiro al arco


@dataclass
class LiveState:
    minute: float
    home_goals: int
    away_goals: int
    home_red: int = 0
    away_red: int = 0
    home_xg: float | None = None
    away_xg: float | None = None
    home_sot: int | None = None
    away_sot: int | None = None
    home_corners: int | None = None
    away_corners: int | None = None
    home_possession: float | None = None
    added_time: float | None = None
    period: str = "2H"  # 1H, HT, 2H, ET, FT
    extra: dict = field(default_factory=dict)


def _observed_rate(xg: float | None, sot: int | None) -> float | None:
    if xg is not None:
        return float(xg)
    if sot is not None:
        return SOT_XG * sot
    return None


def live_rates(pre_home: float, pre_away: float, st: LiveState) -> dict:
    minute = min(max(st.minute, 0.0), 120.0)
    total = 90.0 + (st.added_time if st.added_time is not None else 5.0)
    remaining = max(total - minute, 0.0)
    # Actualización Gamma-Poisson: prior con media pre-partido y peso equivalente
    # a PRIOR_STRENGTH_MIN minutos (aumenta con el tiempo jugado).
    out = {}
    for side, pre, obs in (("home", pre_home, _observed_rate(st.home_xg, st.home_sot)),
                           ("away", pre_away, _observed_rate(st.away_xg, st.away_sot))):
        per_min_prior = pre / 90.0
        if obs is not None and minute > 0:
            alpha = per_min_prior * PRIOR_STRENGTH_MIN * 3 + obs
            beta = PRIOR_STRENGTH_MIN * 3 + minute
            per_min = alpha / beta
        else:
            per_min = per_min_prior
        out[side] = per_min
    h_mult = a_mult = 1.0
    h_mult *= RED_CARD_ATTACK ** st.home_red * RED_CARD_CONCEDE ** st.away_red
    a_mult *= RED_CARD_ATTACK ** st.away_red * RED_CARD_CONCEDE ** st.home_red
    diff = st.home_goals - st.away_goals
    if diff > 0:
        h_mult *= LEADING_DAMP
        a_mult *= TRAILING_BOOST
    elif diff < 0:
        h_mult *= TRAILING_BOOST
        a_mult *= LEADING_DAMP
    lam = out["home"] * remaining * h_mult
    mu = out["away"] * remaining * a_mult
    return {"lambda_home_remaining": lam, "lambda_away_remaining": mu, "remaining_minutes": remaining,
            "multipliers": {"home": h_mult, "away": a_mult}}


def live_matrix(pre_home: float, pre_away: float, st: LiveState) -> tuple[np.ndarray, dict]:
    r = live_rates(pre_home, pre_away, st)
    n = MAX_GOALS + 1
    rem = np.outer(poisson_pmf_vec(r["lambda_home_remaining"], n), poisson_pmf_vec(r["lambda_away_remaining"], n))
    size = n + max(st.home_goals, st.away_goals)
    full = np.zeros((size, size))
    full[st.home_goals:st.home_goals + n, st.away_goals:st.away_goals + n] = rem
    full = full[: n + st.home_goals, : n + st.away_goals]
    return full / full.sum(), r


def live_outcomes(pre_home: float, pre_away: float, st: LiveState) -> tuple[Outcomes, dict]:
    m, info = live_matrix(pre_home, pre_away, st)
    h, a = np.meshgrid(np.arange(m.shape[0]), np.arange(m.shape[1]), indexing="ij")
    out = Outcomes("football", {"home": h.ravel(), "away": a.ravel()}, m.ravel(), exact=True)
    probs = {
        "home": float(m[h > a].sum()),
        "draw": float(m[h == a].sum()),
        "away": float(m[h < a].sum()),
    }
    info["probs"] = probs
    info["expected_final"] = {"home": float((m.sum(axis=1) * np.arange(m.shape[0])).sum()),
                              "away": float((m.sum(axis=0) * np.arange(m.shape[1])).sum())}
    return out, info
