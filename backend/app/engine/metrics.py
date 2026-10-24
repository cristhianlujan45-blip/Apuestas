"""Métricas de evaluación probabilística y de rentabilidad."""

from __future__ import annotations

import math

import numpy as np


def _onehot(y: np.ndarray, k: int) -> np.ndarray:
    o = np.zeros((len(y), k))
    o[np.arange(len(y)), y] = 1
    return o


def brier(probs: np.ndarray, y: np.ndarray) -> float:
    """Brier multiclase (suma sobre clases, promedio sobre partidos)."""
    probs = np.asarray(probs, float)
    if probs.ndim == 1:  # binario
        return float(np.mean((probs - y) ** 2))
    return float(np.mean(np.sum((probs - _onehot(y, probs.shape[1])) ** 2, axis=1)))


def log_loss(probs: np.ndarray, y: np.ndarray) -> float:
    probs = np.asarray(probs, float)
    if probs.ndim == 1:
        p = np.clip(np.where(y == 1, probs, 1 - probs), 1e-12, None)
        return float(-np.mean(np.log(p)))
    return float(-np.mean(np.log(np.clip(probs[np.arange(len(y)), y], 1e-12, None))))


def rps(probs: np.ndarray, y: np.ndarray) -> float:
    """Ranked Probability Score (estándar para resultados ordenados L/E/V)."""
    probs = np.asarray(probs, float)
    k = probs.shape[1]
    cp = np.cumsum(probs, axis=1)
    co = np.cumsum(_onehot(y, k), axis=1)
    return float(np.mean(np.sum((cp - co) ** 2, axis=1) / (k - 1)))


def accuracy(probs: np.ndarray, y: np.ndarray) -> float:
    return float(np.mean(np.argmax(probs, axis=1) == y))


def calibration_table(p: np.ndarray, outcome: np.ndarray, bins: int = 10) -> list[dict]:
    """Fiabilidad: probabilidad media predicha vs frecuencia observada por tramo."""
    p = np.asarray(p, float)
    outcome = np.asarray(outcome, float)
    edges = np.linspace(0, 1, bins + 1)
    out = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        mask = (p >= lo) & (p < hi if hi < 1 else p <= hi)
        n = int(mask.sum())
        if n == 0:
            continue
        freq = float(outcome[mask].mean())
        se = math.sqrt(max(freq * (1 - freq), 1e-9) / n)
        out.append({"bin_low": float(lo), "bin_high": float(hi), "n": n,
                    "mean_predicted": float(p[mask].mean()), "observed": freq,
                    "ci_low": max(0.0, freq - 1.96 * se), "ci_high": min(1.0, freq + 1.96 * se)})
    return out


def ece(p: np.ndarray, outcome: np.ndarray, bins: int = 10) -> float:
    tbl = calibration_table(p, outcome, bins)
    n = sum(r["n"] for r in tbl)
    return float(sum(r["n"] * abs(r["mean_predicted"] - r["observed"]) for r in tbl) / max(n, 1))


def mae(pred: np.ndarray, actual: np.ndarray) -> float:
    return float(np.mean(np.abs(np.asarray(pred) - np.asarray(actual))))


def rmse(pred: np.ndarray, actual: np.ndarray) -> float:
    return float(np.sqrt(np.mean((np.asarray(pred) - np.asarray(actual)) ** 2)))


def multiclass_summary(probs: np.ndarray, y: np.ndarray) -> dict:
    probs = np.asarray(probs, float)
    y = np.asarray(y, int)
    return {
        "n": int(len(y)),
        "log_loss": log_loss(probs, y),
        "brier": brier(probs, y),
        "rps": rps(probs, y),
        "accuracy": accuracy(probs, y),
        "ece_home": ece(probs[:, 0], (y == 0).astype(float)),
        "calibration_home": calibration_table(probs[:, 0], (y == 0).astype(float)),
        "calibration_away": calibration_table(probs[:, -1], (y == probs.shape[1] - 1).astype(float)),
    }


def value_bet_roi(probs: np.ndarray, odds: np.ndarray, y: np.ndarray, min_edge: float = 0.03,
                  closing: np.ndarray | None = None) -> dict:
    """ROI apostando 1 unidad a cada selección con p·o − 1 > ``min_edge``.

    ``odds`` son las cuotas disponibles en el momento de la predicción
    (n × c); ``closing`` (opcional) las de cierre para medir CLV.
    """
    probs = np.asarray(probs, float)
    odds = np.asarray(odds, float)
    ev = probs * odds - 1
    mask = (ev > min_edge) & np.isfinite(odds) & (odds > 1)
    bets = int(mask.sum())
    if bets == 0:
        return {"bets": 0, "roi": None, "profit": 0.0, "hit_rate": None, "avg_odds": None, "clv": None}
    won = np.zeros_like(mask)
    won[np.arange(len(y)), y] = True
    profit = float(np.sum(np.where(won & mask, odds - 1, 0)) - np.sum(mask & ~won))
    res = {
        "bets": bets,
        "profit": profit,
        "roi": profit / bets,
        "hit_rate": float((won & mask).sum() / bets),
        "avg_odds": float(odds[mask].mean()),
        "min_edge": min_edge,
    }
    if closing is not None:
        closing = np.asarray(closing, float)
        valid = mask & np.isfinite(closing) & (closing > 1)
        res["clv"] = float(np.mean(odds[valid] / closing[valid] - 1)) if valid.any() else None
    # Intervalo bootstrap del ROI
    rng = np.random.default_rng(0)
    per_bet = np.where(won & mask, odds - 1, -1.0)[mask]
    boots = [rng.choice(per_bet, len(per_bet)).mean() for _ in range(500)]
    res["roi_ci"] = [float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))]
    return res


# ---------------------------------------------------------------------------
# Detección de degradación
# ---------------------------------------------------------------------------

def page_hinkley(losses: np.ndarray, delta: float = 0.005, threshold: float = 0.5) -> dict:
    """Test de Page-Hinkley sobre una serie de pérdidas (log loss por partido).

    Detecta aumentos sostenidos de la pérdida media (degradación del modelo).
    """
    losses = np.asarray(losses, float)
    mean, cum, min_cum = 0.0, 0.0, 0.0
    alarm_at = None
    for t, x in enumerate(losses, 1):
        mean += (x - mean) / t
        cum += x - mean - delta
        min_cum = min(min_cum, cum)
        if cum - min_cum > threshold and alarm_at is None:
            alarm_at = t
    return {"alarm": alarm_at is not None, "alarm_index": alarm_at, "statistic": float(cum - min_cum)}


def degradation_check(losses: np.ndarray, window: int = 200, z_threshold: float = 3.0) -> dict:
    """Compara la pérdida media reciente con la de referencia (inicio de la serie).

    Combina un test z de la ventana reciente con Page-Hinkley calibrado a la
    escala de la pérdida (la log loss por partido es muy ruidosa).
    """
    losses = np.asarray(losses, float)
    if len(losses) < 2 * window:
        return {"alarm": False, "reason": "serie demasiado corta", "n": int(len(losses))}
    ref, recent = losses[:-window], losses[-window:]
    se = ref.std(ddof=1) / math.sqrt(window)
    z = float((recent.mean() - ref.mean()) / se) if se > 0 else 0.0
    ph = page_hinkley(losses - ref.mean(), delta=0.02, threshold=15 * ref.std(ddof=1))
    return {"alarm": bool(z > z_threshold or ph["alarm"]), "z": z, "reference_mean": float(ref.mean()),
            "recent_mean": float(recent.mean()), "window": window, "page_hinkley": ph, "n": int(len(losses))}


def rolling_metric(losses: np.ndarray, window: int = 50) -> list[float]:
    losses = np.asarray(losses, float)
    if len(losses) < window:
        return []
    c = np.cumsum(np.insert(losses, 0, 0))
    return list(map(float, (c[window:] - c[:-window]) / window))
