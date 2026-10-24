"""Matemática de cuotas: probabilidad implícita, margen, cuotas justas, EV y Kelly."""

from __future__ import annotations

from fractions import Fraction
from typing import Iterable, Literal, Sequence

import numpy as np
from scipy.optimize import brentq

DevigMethod = Literal["multiplicative", "additive", "power", "shin"]


def implied_probability(odds: float) -> float:
    if odds <= 1.0:
        raise ValueError("La cuota decimal debe ser mayor que 1.0")
    return 1.0 / odds


def overround(odds: Sequence[float]) -> float:
    """Suma de probabilidades implícitas menos 1 (margen bruto del operador)."""
    return float(sum(1.0 / o for o in odds) - 1.0)


def margin_pct(odds: Sequence[float]) -> float:
    """Margen sobre el libro completo en porcentaje (1 - 1/Σ(1/o))."""
    total = sum(1.0 / o for o in odds)
    return float((1.0 - 1.0 / total) * 100.0)


def devig(odds: Sequence[float], method: DevigMethod = "power") -> np.ndarray:
    """Probabilidades sin margen para un mercado completo y mutuamente excluyente."""
    q = np.array([1.0 / o for o in odds], dtype=float)
    total = q.sum()
    if len(q) < 2:
        raise ValueError("Se necesita el mercado completo para quitar el margen")
    if method == "multiplicative" or total <= 1.0:
        return q / total
    if method == "additive":
        p = q - (total - 1.0) / len(q)
        p = np.clip(p, 1e-9, None)
        return p / p.sum()
    if method == "power":
        k = brentq(lambda k: np.sum(q ** k) - 1.0, 1.0, 50.0)
        return q ** k
    if method == "shin":
        # Shin (1993): proporción z de apostadores con información privilegiada.
        def probs(z: float) -> np.ndarray:
            return (np.sqrt(z ** 2 + 4 * (1 - z) * q ** 2 / total) - z) / (2 * (1 - z))

        z = brentq(lambda z: probs(z).sum() - 1.0, 0.0, 0.4)
        p = probs(z)
        return p / p.sum()
    raise ValueError(f"Método desconocido: {method}")


def fair_odds(probability: float) -> float:
    if probability <= 0:
        return float("inf")
    return 1.0 / probability


def expected_value(probability: float, odds: float, push_probability: float = 0.0) -> float:
    """EV por unidad apostada. Con push se devuelve la apuesta."""
    lose = 1.0 - probability - push_probability
    return probability * (odds - 1.0) - lose


def kelly_fraction(probability: float, odds: float, fraction: float = 0.25) -> float:
    """Kelly fraccional (por defecto 1/4). Nunca negativo."""
    b = odds - 1.0
    if b <= 0:
        return 0.0
    f = (probability * b - (1.0 - probability)) / b
    return max(0.0, f * fraction)


def edge(probability: float, odds: float) -> float:
    """Ventaja relativa: p·o − 1."""
    return probability * odds - 1.0


def combined_odds(odds: Iterable[float]) -> float:
    out = 1.0
    for o in odds:
        out *= o
    return out


# ---------------------------------------------------------------------------
# Formatos de cuota
# ---------------------------------------------------------------------------

def to_american(odds: float) -> str:
    if odds >= 2.0:
        return f"+{round((odds - 1) * 100)}"
    return f"{round(-100 / (odds - 1))}"


def to_fractional(odds: float) -> str:
    frac = Fraction(odds - 1).limit_denominator(100)
    return f"{frac.numerator}/{frac.denominator}"


def to_hongkong(odds: float) -> float:
    return round(odds - 1, 3)


def to_indonesian(odds: float) -> float:
    return round(odds - 1 if odds >= 2 else -1 / (odds - 1), 3)


def to_malay(odds: float) -> float:
    return round(odds - 1 if odds <= 2 else -1 / (odds - 1), 3)


def from_american(value: float) -> float:
    if value > 0:
        return 1 + value / 100
    return 1 + 100 / abs(value)


def all_formats(odds: float) -> dict:
    return {
        "decimal": round(odds, 3),
        "americana": to_american(odds),
        "fraccional": to_fractional(odds),
        "hong_kong": to_hongkong(odds),
        "indonesia": to_indonesian(odds),
        "malaya": to_malay(odds),
        "probabilidad_implicita": round(1 / odds, 4),
    }
