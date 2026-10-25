"""Pruebas del motor matemático (datos sintéticos generados en la prueba)."""

from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from app.engine import odds_math as om
from app.engine.basketball import BasketballModel
from app.engine.football.goals import TeamRatingModel, calibrate_matrix, matrix_from_rates, outcome_probs
from app.engine.football.live import LiveState, live_outcomes
from app.engine.markets import Outcomes, Selection, joint_same_event, price
from app.engine.metrics import brier, log_loss, rps
from app.engine.other_sports import BaseballModel, VolleyballModel
from app.engine.tennis import game_win_prob, match_win_prob, simulate_match


def test_devig_methods_sum_to_one():
    odds = [2.10, 3.40, 3.60]
    for m in ("multiplicative", "additive", "power", "shin"):
        p = om.devig(odds, m)
        assert abs(p.sum() - 1) < 1e-9
        assert p[0] > p[2]
    assert om.overround(odds) > 0
    assert om.from_american(150) == pytest.approx(2.5)
    assert om.to_american(2.5) == "+150"


def test_expected_value_and_kelly():
    assert om.expected_value(0.5, 2.2) == pytest.approx(0.1)
    assert om.kelly_fraction(0.5, 2.2, fraction=1) == pytest.approx(0.1 / 1.2)
    assert om.kelly_fraction(0.3, 2.0) == 0


def _grid(matrix):
    n = matrix.shape[0]
    h, a = np.meshgrid(np.arange(n), np.arange(n), indexing="ij")
    return Outcomes("football", {"home": h.ravel(), "away": a.ravel()}, matrix.ravel(), exact=True)


def test_market_pricing_consistency():
    m = matrix_from_rates(1.6, 1.1, -0.05)
    out = _grid(m)
    ph = price(Selection("1x2", "home"), out).p_win
    pd_ = price(Selection("1x2", "draw"), out).p_win
    pa = price(Selection("1x2", "away"), out).p_win
    assert ph + pd_ + pa == pytest.approx(1, abs=1e-9)
    assert price(Selection("double_chance", "1X"), out).p_win == pytest.approx(ph + pd_)
    dnb = price(Selection("dnb", "home"), out)
    assert dnb.p_push == pytest.approx(pd_)
    o = price(Selection("total_goals", "over", 2.5), out).p_win
    u = price(Selection("total_goals", "under", 2.5), out).p_win
    assert o + u == pytest.approx(1)
    # Línea asiática de cuarto: medio push / media ganada
    q = price(Selection("asian_handicap", "home", -0.25), out)
    assert q.p_half_lose == pytest.approx(pd_)
    assert q.p_win == pytest.approx(ph)
    # AH 0 == DNB
    ah0 = price(Selection("asian_handicap", "home", 0.0), out)
    assert ah0.p_win == pytest.approx(dnb.p_win)
    fair = q.fair_odds()
    assert q.ev(fair) == pytest.approx(0, abs=1e-9)


def test_joint_same_event_captures_correlation():
    m = matrix_from_rates(1.8, 0.9)
    out = _grid(m)
    a, b = Selection("1x2", "home"), Selection("total_goals", "over", 2.5)
    j = joint_same_event([(a, 2.0), (b, 2.0)], out)
    indep = price(a, out).p_win * price(b, out).p_win
    assert j["p_all_win"] > indep  # victoria local y over están correlacionados positivamente


def test_calibrate_matrix_matches_target():
    m = matrix_from_rates(1.3, 1.2)
    t = np.array([0.5, 0.25, 0.25])
    assert outcome_probs(calibrate_matrix(m, t)) == pytest.approx(t)


def _synthetic_league(seed=1, n_rounds=40):
    rng = np.random.default_rng(seed)
    teams = [f"T{i}" for i in range(12)]
    att = {t: a for t, a in zip(teams, np.linspace(-0.4, 0.4, 12))}
    rows = []
    d0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
    for r in range(n_rounds):
        perm = rng.permutation(teams)
        for i in range(0, 12, 2):
            h, a = perm[i], perm[i + 1]
            lam = np.exp(0.1 + att[h] - att[a] * 0.5 + 0.25)
            mu = np.exp(0.1 + att[a] - att[h] * 0.5)
            rows.append({"date": d0 + timedelta(days=7 * r), "home": h, "away": a,
                         "hg": rng.poisson(lam), "ag": rng.poisson(mu), "league": "SYN"})
    return pd.DataFrame(rows), att


def test_dixon_coles_recovers_strength_order():
    df, att = _synthetic_league()
    ref = df["date"].max() + timedelta(days=1)
    m = TeamRatingModel(xi=0.0).fit(df, ref)
    order = [t for t, _ in sorted(att.items(), key=lambda kv: kv[1])]
    est = {t: m.attack[m.teams.index(t)] for t in order}
    assert np.corrcoef(list(att.values()), [est[t] for t in att])[0, 1] > 0.8
    assert m.home_adv > 0
    assert m.cov is not None
    draws = m.posterior_draws(20, np.random.default_rng(0))
    assert draws.shape == (20, len(m._theta()))


def test_live_model_updates():
    out, info = live_outcomes(1.5, 1.0, LiveState(minute=80, home_goals=2, away_goals=0))
    assert info["probs"]["home"] > 0.9
    out2, info2 = live_outcomes(1.5, 1.0, LiveState(minute=10, home_goals=0, away_goals=0, home_red=1))
    _, base = live_outcomes(1.5, 1.0, LiveState(minute=10, home_goals=0, away_goals=0))
    assert info2["probs"]["home"] < base["probs"]["home"]


def test_tennis_markov():
    assert game_win_prob(0.5) == pytest.approx(0.5)
    assert game_win_prob(0.6) == pytest.approx(0.7357, abs=1e-3)
    assert match_win_prob(0.64, 0.64, 3) == pytest.approx(0.5, abs=1e-6)
    assert match_win_prob(0.68, 0.62, 5) > match_win_prob(0.68, 0.62, 3) > 0.5
    sim = simulate_match(0.68, 0.62, 3, 20000, np.random.default_rng(0))
    p_sim = (sim["home_sets"] > sim["away_sets"]).mean()
    assert p_sim == pytest.approx(match_win_prob(0.68, 0.62, 3), abs=0.015)
    assert set(np.unique(sim["home_sets"] + sim["away_sets"])) <= {2, 3}


def test_basketball_and_other_sports():
    rng = np.random.default_rng(3)
    teams = [f"B{i}" for i in range(8)]
    strength = dict(zip(teams, np.linspace(-6, 6, 8)))
    rows = []
    for d in range(120):
        h, a = rng.choice(teams, 2, replace=False)
        rows.append({"date": datetime(2025, 1, 1) + timedelta(days=d), "home": h, "away": a,
                     "hpts": 112 + strength[h] - strength[a] / 2 + 2 + rng.normal(0, 11),
                     "apts": 110 + strength[a] - strength[h] / 2 + rng.normal(0, 11)})
    df = pd.DataFrame(rows)
    m = BasketballModel().fit(df, datetime(2025, 6, 1))
    out = m.outcomes("B7", "B0")
    assert price(Selection("moneyline", "home"), out).p_win > 0.6
    assert (out["home"] != out["away"]).all()

    bb = df.rename(columns={"hpts": "hruns", "apts": "aruns"})
    bb["hruns"] = (bb["hruns"] / 25).round().clip(0)
    bb["aruns"] = (bb["aruns"] / 25).round().clip(0)
    bm = BaseballModel().fit(bb, datetime(2025, 6, 1))
    bo = bm.outcomes("B7", "B0")
    assert (bo["home"] != bo["away"]).all()

    vm = VolleyballModel().fit(df, datetime(2025, 6, 1))
    vo = vm.outcomes("B7", "B0", n=5000)
    assert set(np.unique(np.maximum(vo["home_sets"], vo["away_sets"]))) == {3}


def test_metrics():
    p = np.array([[0.6, 0.25, 0.15], [0.2, 0.3, 0.5]])
    y = np.array([0, 2])
    assert brier(p, y) == pytest.approx(((0.4 ** 2 + 0.25 ** 2 + 0.15 ** 2) + (0.2 ** 2 + 0.3 ** 2 + 0.5 ** 2)) / 2)
    assert log_loss(p, y) == pytest.approx(-(np.log(0.6) + np.log(0.5)) / 2)
    assert 0 < rps(p, y) < 1


def test_models_are_picklable():
    import pickle

    from app.engine.football.engine import FootballEngine
    from app.engine.tennis import TennisModel

    df, _ = _synthetic_league(n_rounds=30)
    for c in ("hs", "as", "hst", "ast", "hc", "ac", "hcards", "acards"):
        df[c] = 3
    eng = FootballEngine(ml_models=["logreg"], fit_bivariate=True).fit(df, df["date"].max() + timedelta(days=1))
    eng2 = pickle.loads(pickle.dumps(eng))
    p1 = eng.predict("SYN", "T0", "T11", n_draws=0).probs
    p2 = eng2.predict("SYN", "T0", "T11", n_draws=0).probs
    assert np.allclose(p1, p2)
    t = TennisModel()
    t.fit(pd.DataFrame([{"date": datetime(2025, 1, 1), "surface": "Clay", "winner": "A", "loser": "B"}]), datetime(2025, 2, 1))
    pickle.loads(pickle.dumps(t))
    pickle.loads(pickle.dumps(BaseballModel()))
    pickle.loads(pickle.dumps(VolleyballModel()))


def test_availability_adjustment():
    from app.engine.football.engine import FootballEngine, apply_availability

    df, _ = _synthetic_league(n_rounds=30)
    for c in ("hs", "as", "hst", "ast", "hc", "ac", "hcards", "acards"):
        df[c] = 3
    eng = FootballEngine(ml_models=["logreg"], fit_bivariate=False).fit(df, df["date"].max() + timedelta(days=1))
    base = eng.predict("SYN", "T0", "T11", n_draws=20)
    p0, (l0, _) = base.probs.copy(), base.exp_goals
    adj = apply_availability(base, 0.8, 1.0, {"missing_home": ["X"]})
    assert adj.probs[0] < p0[0] and adj.exp_goals[0] == pytest.approx(l0 * 0.8)
    assert adj.matrix.sum() == pytest.approx(1)


def test_totals_calibration_keeps_1x2():
    from app.engine.football.engine import calibrate_matrix_totals, over_prob
    from app.engine.football.goals import matrix_from_rates, outcome_probs

    m = matrix_from_rates(1.05, 0.65)
    p = outcome_probs(m)
    for target in (0.30, 0.45, 0.60):
        c = calibrate_matrix_totals(m, p, target)
        assert abs(over_prob(c, 2.5) - target) < 2e-3
        assert np.allclose(outcome_probs(c), p, atol=1e-6)
        assert abs(c.sum() - 1) < 1e-9


def test_margin_calibration_matches_handicap_and_keeps_1x2():
    from app.engine.football.engine import ah_cover_prob, calibrate_matrix_margin
    from app.engine.football.goals import matrix_from_rates, outcome_probs

    m = matrix_from_rates(2.4, 0.6)
    p = outcome_probs(m)
    for line, target in ((-2.25, 0.50), (-1.5, 0.42)):
        c = calibrate_matrix_margin(m, p, line, target)
        assert abs(ah_cover_prob(c, line) - target) < 5e-3
        assert np.allclose(outcome_probs(c), p, atol=1e-6)
