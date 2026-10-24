"""Simulador Monte Carlo: distribuciones e intervalos de incertidumbre.

Dos fuentes de incertidumbre se separan explícitamente:

* aleatoria (el propio partido): se obtiene simulando miles de resultados;
* epistémica (no conocemos los parámetros exactos): se obtiene repitiendo la
  simulación con parámetros muestreados de la posterior (aprox. de Laplace).
"""

from __future__ import annotations

import numpy as np

from .markets import Outcomes, Selection, UnsupportedMarket, price


def distribution(values: np.ndarray, weights: np.ndarray, max_bins: int = 60) -> dict:
    v = np.asarray(values)
    w = np.asarray(weights, float)
    w = w / w.sum()
    uniq = np.unique(v)
    if len(uniq) <= max_bins:
        hist = [{"x": float(u), "p": float(w[v == u].sum())} for u in uniq]
    else:
        edges = np.linspace(v.min(), v.max(), max_bins + 1)
        idx = np.clip(np.digitize(v, edges) - 1, 0, max_bins - 1)
        hist = [{"x": float((edges[i] + edges[i + 1]) / 2), "p": float(w[idx == i].sum())} for i in range(max_bins)]
    order = np.argsort(v)
    cw = np.cumsum(w[order])
    q = lambda p: float(v[order][min(np.searchsorted(cw, p), len(v) - 1)])  # noqa: E731
    mean = float(np.sum(w * v))
    sd = float(np.sqrt(np.sum(w * (v - mean) ** 2)))
    return {"mean": mean, "sd": sd, "p05": q(0.05), "p25": q(0.25), "p50": q(0.5), "p75": q(0.75),
            "p95": q(0.95), "histogram": hist}


def summarize(out: Outcomes) -> dict:
    res = {"sport": out.sport, "samples": int(out.n), "exact": out.exact, "variables": {}}
    for key, arr in out.values.items():
        if key.startswith("player:"):
            continue
        res["variables"][key] = distribution(arr, out.weights)
    if out.has("home") and out.has("away"):
        h, a = out["home"], out["away"]
        res["variables"]["total"] = distribution(h + a, out.weights)
        res["variables"]["margin"] = distribution(h - a, out.weights)
        w = out.weights
        res["outcome"] = {"home": float(w[h > a].sum()), "draw": float(w[h == a].sum()),
                          "away": float(w[h < a].sum())}
    return res


def probability_interval(selection: Selection, outcome_draws: list[Outcomes], level: float = 0.8) -> dict:
    """Intervalo epistémico de la probabilidad de una selección."""
    ps = []
    for o in outcome_draws:
        try:
            ps.append(price(selection, o).p_effective)
        except UnsupportedMarket:
            return {}
    ps = np.array(ps)
    lo, hi = (1 - level) / 2, 1 - (1 - level) / 2
    return {"mean": float(ps.mean()), "low": float(np.quantile(ps, lo)), "high": float(np.quantile(ps, hi)),
            "level": level, "draws": len(ps)}


def matrix_outcomes(matrix: np.ndarray) -> Outcomes:
    n, m = matrix.shape
    h, a = np.meshgrid(np.arange(n), np.arange(m), indexing="ij")
    return Outcomes("football", {"home": h.ravel(), "away": a.ravel()}, matrix.ravel(), exact=True)
