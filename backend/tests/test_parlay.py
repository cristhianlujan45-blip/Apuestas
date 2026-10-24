"""Pruebas del optimizador PARLAY AI (candidatos sintéticos generados en la prueba)."""

import itertools
import math
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from app.engine.football.goals import matrix_from_rates
from app.engine.markets import LegPricing, Outcomes, Selection
from app.services.calculator import cop, required_odds, returns
from app.services.parlay.optimizer import Candidate, ParlayRequest, evaluate, optimize
from app.services.parlay.validation import validate

NOW = datetime(2026, 10, 24, 12, tzinfo=timezone.utc)


def cand(eid, p, odds, op="betplay", market="1x2", sel="home", line=None, suff=True):
    return Candidate(
        event_id=eid, event_label=f"E{eid}", sport="football", competition="Liga", start_time=NOW + timedelta(hours=5),
        selection=Selection(market, sel, line), selection_label=f"{market}:{sel}", operator_key=op, odds=odds,
        captured_at=NOW - timedelta(minutes=2), pricing=LegPricing(p, 0, 0, 0, 1 - p), data_sufficient=suff,
    )


def make_pool(n_events=10, seed=0, ops=("betplay", "wplay")):
    rng = np.random.default_rng(seed)
    pool = []
    for e in range(n_events):
        for k, sel in enumerate(["home", "draw", "away"]):
            p = float(rng.uniform(0.2, 0.75))
            fair = 1 / p
            for op in ops:
                pool.append(cand(e, p, round(fair * rng.uniform(0.9, 1.06), 2), op=op, sel=sel))
    return pool


def brute_force(pool, op, lo, hi, kmin, kmax):
    by_event = {}
    for c in pool:
        if c.operator_key == op:
            by_event.setdefault(c.event_id, []).append(c)
    best, best_p = None, -1
    events = list(by_event)
    for k in range(kmin, kmax + 1):
        for evs in itertools.combinations(events, k):
            for legs in itertools.product(*[by_event[e] for e in evs]):
                o = math.prod(c.odds for c in legs)
                if lo <= o <= hi:
                    p = math.prod(c.p for c in legs)
                    if p > best_p:
                        best, best_p = legs, p
    return best, best_p


def test_dp_matches_brute_force_conservative():
    pool = make_pool(7, seed=3, ops=("betplay",))
    req = ParlayRequest(target_odds=5.0, min_odds=4.5, max_odds=5.5, min_legs=2, max_legs=3, risk="high")
    res = optimize(pool, req, {"betplay"}, now=NOW)
    a = res.alternatives["A"]
    _, bp = brute_force([c for c in pool if c.p >= 0.2], "betplay", 4.5, 5.5, 2, 3)
    assert a is not None
    assert 4.5 <= a.total_odds <= 5.5
    # La discretización (0.5 %) puede desplazar levemente el borde de la banda
    assert a.joint_probability == pytest.approx(bp, rel=0.02)


def test_modes_and_constraints():
    pool = make_pool(15, seed=1)
    req = ParlayRequest(target_odds=8.0, min_legs=2, max_legs=5, risk="high")
    res = optimize(pool, req, {"betplay", "wplay"}, now=NOW)
    lo, hi = req.band()
    for label, sol in res.alternatives.items():
        if sol is None:
            continue
        assert lo * 0.995 <= sol.total_odds <= hi * 1.005
        assert len({c.event_id for c in sol.legs}) == len(sol.legs)  # una selección por evento
        assert len({c.operator_key for c in sol.legs}) == 1           # una sola casa por combinada
    if res.alternatives["C"] is not None:
        assert res.alternatives["C"].ev > 0
        assert all(c.ev >= 0.01 for c in res.alternatives["C"].legs)
    d = res.alternatives["D"]
    others = [s for s in res.alternatives.values() if s is not None]
    assert len(d.legs) == min(len(s.legs) for s in others)


def test_excludes_unauthorized_stale_and_insufficient():
    pool = make_pool(6, seed=2, ops=("betplay", "unlicensed"))
    pool.append(cand(99, 0.9, 1.5, suff=False))
    stale = cand(98, 0.9, 1.6)
    stale.captured_at = NOW - timedelta(hours=3)
    pool.append(stale)
    req = ParlayRequest(target_odds=3.0, risk="high")
    res = optimize(pool, req, {"betplay"}, now=NOW)
    disc = res.considered["discarded"]
    assert disc["operador no autorizado por Coljuegos"] == 18
    assert disc["datos insuficientes para el modelo"] == 1
    assert disc["cuota desactualizada"] == 1
    for sol in res.alternatives.values():
        if sol:
            assert all(c.operator_key == "betplay" for c in sol.legs)


def test_no_forced_result():
    pool = [cand(i, 0.3, 2.0) for i in range(3)]  # EV muy negativo
    req = ParlayRequest(target_odds=8.0, min_legs=3, max_legs=3, risk="low")
    res = optimize(pool, req, {"betplay"}, now=NOW)
    assert all(v is None for v in res.alternatives.values())
    assert any("No existe una combinación" in m for m in res.messages)


def test_same_event_joint_probability_and_validation():
    m = matrix_from_rates(1.9, 0.8)
    n = m.shape[0]
    h, a = np.meshgrid(np.arange(n), np.arange(n), indexing="ij")
    out = Outcomes("football", {"home": h.ravel(), "away": a.ravel()}, m.ravel(), exact=True)
    from app.engine.markets import price

    c1 = cand(1, 0, 1.6, sel="home")
    c1.pricing = price(Selection("1x2", "home"), out)
    c2 = cand(1, 0, 1.9, market="total_goals", sel="over", line=2.5)
    c2.selection = Selection("total_goals", "over", 2.5)
    c2.pricing = price(c2.selection, out)
    sol = evaluate("betplay", "conservative", [c1, c2], outcomes={1: out})
    # sin compuesta: se evalúa como independiente; validación debe advertir del mismo evento
    v = validate(sol, {1: {"status": "scheduled"}}, {"status": "authorized", "capabilities": {"parlays": True,
                                                                                               "same_event_parlays": False}},
                 now=NOW, outcomes={1: out})
    rules = next(c for c in v["checks"] if c["check"] == "reglas_operador")
    assert not rules["ok"]
    corr = next(c for c in v["checks"] if c["check"] == "correlaciones")
    assert "si fueran independientes" in corr["detail"]


def test_calculator_cop():
    r = returns(10000, 10.0)
    assert r["potential_return"] == 100000
    assert r["formatted"]["profit"] == "$90.000"
    assert required_odds(10000, 90000)["required_odds"] == pytest.approx(10.0)
    assert cop(1234567) == "$1.234.567"
