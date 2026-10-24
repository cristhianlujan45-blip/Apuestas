"""Calculadora de ganancias en pesos colombianos (COP)."""

from __future__ import annotations

import math


def cop(value: float) -> str:
    """Formato colombiano: $1.234.567"""
    neg = value < 0
    s = f"{abs(round(value)):,.0f}".replace(",", ".")
    return f"{'-' if neg else ''}${s}"


def returns(stake: float, odds: float) -> dict:
    if stake <= 0:
        raise ValueError("La inversión debe ser mayor que 0")
    if odds <= 1:
        raise ValueError("La cuota debe ser mayor que 1.00")
    ret = stake * odds
    return {"stake": stake, "odds": odds, "potential_return": ret, "potential_profit": ret - stake,
            "formatted": {"stake": cop(stake), "return": cop(ret), "profit": cop(ret - stake)}}


def required_odds(stake: float, target_profit: float) -> dict:
    """Buscador inverso: cuota necesaria para ganar ``target_profit`` netos con ``stake``."""
    if stake <= 0 or target_profit <= 0:
        raise ValueError("Inversión y ganancia deseada deben ser mayores que 0")
    odds = (target_profit + stake) / stake
    return {"stake": stake, "target_profit": target_profit, "required_odds": odds,
            "implied_probability": 1 / odds,
            "formatted": {"stake": cop(stake), "profit": cop(target_profit), "return": cop(stake + target_profit)}}


def required_stake(odds: float, target_profit: float) -> dict:
    if odds <= 1 or target_profit <= 0:
        raise ValueError("Cuota > 1 y ganancia > 0")
    stake = target_profit / (odds - 1)
    return {"odds": odds, "target_profit": target_profit, "required_stake": stake,
            "formatted": {"stake": cop(stake), "profit": cop(target_profit)}}


def bankroll_check(stake: float, capital: float, probability: float | None = None, odds: float | None = None) -> dict:
    """Riesgo sobre el capital disponible y referencia de Kelly fraccional."""
    if capital <= 0:
        raise ValueError("El capital disponible debe ser mayor que 0")
    pct = stake / capital
    out = {"stake_pct_of_capital": pct, "warning": None}
    if pct > 0.05:
        out["warning"] = ("La inversión supera el 5 % del capital disponible. Una racha de pérdidas es muy "
                          "probable incluso con estimaciones correctas.")
    if probability is not None and odds is not None and odds > 1:
        b = odds - 1
        k = max(0.0, (probability * b - (1 - probability)) / b)
        out["kelly_full_pct"] = k
        out["kelly_quarter_stake"] = capital * k / 4
        out["formatted_kelly_quarter"] = cop(capital * k / 4)
        out["p_losing_streak_5"] = (1 - probability) ** 5
        if k == 0:
            out["kelly_note"] = "Valor esperado ≤ 0 según el modelo: Kelly recomienda no apostar."
    return out


def expected(stake: float, odds: float, probability: float) -> dict:
    ev = stake * (probability * odds - 1)
    sd = stake * odds * math.sqrt(probability * (1 - probability))
    return {"expected_profit": ev, "sd": sd, "formatted": {"expected_profit": cop(ev)},
            "probability_of_loss": 1 - probability}
