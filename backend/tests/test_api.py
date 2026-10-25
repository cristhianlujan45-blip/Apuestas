"""Prueba de integración de la API con una base temporal y datos sintéticos de prueba.

Los datos sintéticos existen SOLO en esta prueba para verificar el flujo
completo (registro → cuotas manuales → modelo → BUSCAR MI CUOTA → historial).
"""

from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    from app import db as dbmod
    from app.config import get_settings

    import os

    path = tmp_path_factory.mktemp("db") / "test.db"
    # TEST_DATABASE_URL permite ejecutar la misma prueba contra PostgreSQL
    get_settings().database_url = os.environ.get("TEST_DATABASE_URL") or f"sqlite:///{path}"
    get_settings().anthropic_api_key = None
    dbmod.reset_engine()
    from app.engine.football.engine import FootballEngine
    from app.main import app
    from app.services import model_store

    rng = np.random.default_rng(5)
    teams = ["Arsenal", "Chelsea", "Liverpool", "Everton", "Fulham", "Brentford", "Wolves", "Burnley"]
    strength = dict(zip(teams, np.linspace(0.4, -0.4, len(teams))))
    rows = []
    d0 = datetime(2025, 1, 4, 15, tzinfo=timezone.utc)
    for r in range(70):
        perm = rng.permutation(teams)
        for i in range(0, len(teams), 2):
            h, a = perm[i], perm[i + 1]
            lam = np.exp(0.25 + strength[h] - 0.5 * strength[a])
            mu = np.exp(0.05 + strength[a] - 0.5 * strength[h])
            rows.append({"date": d0 + timedelta(days=4 * r), "league": "E0", "home": h, "away": a,
                         "hg": rng.poisson(lam), "ag": rng.poisson(mu), "hs": 12, "as": 10, "hst": 4, "ast": 3,
                         "hc": rng.poisson(5.5), "ac": rng.poisson(4.5), "hcards": 2, "acards": 2,
                         "match_id": f"E0:{r}:{h}:{a}", "odds_h": np.nan, "odds_d": np.nan, "odds_a": np.nan})
    hist = pd.DataFrame(rows)
    eng = FootballEngine(ml_models=["logreg"], fit_bivariate=False).fit(hist, datetime.now(timezone.utc))
    with TestClient(app) as c:
        model_store._cache["football"] = eng
        yield c
    model_store.clear_cache()


def test_status_and_operators(client):
    s = client.get("/api/status").json()
    assert s["providers"]["football_data_uk"]["configured"]
    ops = client.get("/api/operators").json()["operators"]
    keys = {o["key"] for o in ops if o["status"] == "authorized"}
    assert {"betplay", "wplay", "rushbet", "betano", "codere", "bwin", "stake", "mryoker"} <= keys
    assert len(keys) == 14
    assert next(o for o in ops if o["key"] == "pinnacle")["status"] == "reference_only"


def test_full_flow(client):
    r = client.post("/api/auth/register", json={"email": "a@b.co", "password": "secreta123",
                                                "birthdate": "2010-01-01", "accept_terms": True})
    assert r.status_code == 400  # menor de edad
    r = client.post("/api/auth/register", json={"email": "a@b.co", "password": "secreta123",
                                                "birthdate": "1990-05-05", "accept_terms": True})
    assert r.status_code == 200, r.text
    token = r.json()["token"]
    H = {"Authorization": f"Bearer {token}"}

    start = (datetime.now(timezone.utc) + timedelta(hours=20)).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    pairs = [("Arsenal", "Burnley"), ("Liverpool", "Wolves"), ("Chelsea", "Brentford"), ("Everton", "Fulham")]
    rows = []
    for home, away in pairs:
        for op, f in (("betplay", 1.0), ("wplay", 1.03)):
            for sel, o in (("home", 1.7), ("draw", 3.8), ("away", 4.8)):
                rows.append({"sport": "football", "competition": "Premier League", "start_time": start, "home": home,
                             "away": away, "operator": op, "market": "1x2", "selection": sel, "odds": round(o * f, 2)})
            rows.append({"sport": "football", "competition": "Premier League", "start_time": start, "home": home,
                         "away": away, "operator": op, "market": "total_goals", "selection": "over", "line": 1.5,
                         "odds": round(1.33 * f, 2)})
    rows.append({"sport": "football", "start_time": start, "home": "X", "away": "Y", "operator": "unlicensed",
                 "market": "1x2", "selection": "home", "odds": 2.0})
    r = client.post("/api/odds/manual", json=rows, headers=H)
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["imported"] == len(rows) - 1
    assert "no está autorizado" in res["errors"][0]["error"]

    evs = client.get("/api/events?scope=upcoming").json()["events"]
    ev = next(e for e in evs if e["home"] == "Arsenal")
    assert ev["colombian_operators"] == 2
    assert ev["probs"]["home"] > ev["probs"]["away"]

    detail = client.get(f"/api/events/{ev['id']}").json()
    row = next(m for m in detail["markets"] if m["market"] == "1x2" and m["selection"] == "home")
    assert row["best"]["operator"] == "wplay"
    assert "model" in row and 0 < row["model"]["p"] < 1
    assert any(m["operator"] == "betplay" and m["market"] == "1x2" for m in detail["margins"])

    sim = client.get(f"/api/events/{ev['id']}/simulate").json()
    assert sim["samples"] > 0 and "total" in sim["variables"]

    cmp = client.get("/api/odds/operators-compare?a=wplay&b=betplay").json()
    assert cmp["a_better"] == cmp["common_selections"]

    res = client.post("/api/parlay/search", json={"target_odds": 3.0, "min_legs": 2, "max_legs": 4, "risk": "high"},
                      headers=H).json()
    assert res["considered"]["candidates_in"] > 0
    assert any(v["available"] for v in res["alternatives"].values()), res["messages"]
    a = res["alternatives"]["A"]
    if a["available"]:
        assert 2.7 * 0.99 <= a["total_odds"] <= 3.45 * 1.01
        assert len({l["operator"] for l in a["legs"]}) == 1
        assert a["comparison"]["per_operator_totals"]
        assert any(c["check"] == "reglas_operador" for c in a["validation"]["checks"])
    hist = client.get("/api/parlays", headers=H).json()
    assert len(hist["parlays"]) >= 1 or not a["available"]

    calc = client.post("/api/calculator", json={"stake_cop": 10000, "odds": 10, "target_profit_cop": 90000}).json()
    assert calc["returns"]["potential_return"] == 100000
    assert calc["required_odds"]["required_odds"] == pytest.approx(10)

    chat = client.post("/api/assistant", json={"messages": [{"role": "user", "content": "Busca una cuota de 3"}]}).json()
    assert chat["tools_used"] == ["buscar_mi_cuota"]
    chat = client.post("/api/assistant", json={"messages": [{"role": "user", "content": "Compara BetPlay con Wplay"}]}).json()
    assert chat["tools_used"] == ["comparar_operadores"]

    # Límites: reducción inmediata, aumento diferido, autoexclusión bloquea
    lim = client.put("/api/limits", json={"daily_stake_cop": 50000}, headers=H).json()
    assert lim["daily_stake_cop"] == 50000
    lim = client.put("/api/limits", json={"daily_stake_cop": 900000}, headers=H).json()
    assert lim["daily_stake_cop"] == 50000 and lim["pending_changes"]["daily_stake_cop"] == 900000
    client.post("/api/bets", json={"operator": "betplay", "description": "x", "stake_cop": 60000, "odds": 2}, headers=H)
    r = client.post("/api/parlay/search", json={"target_odds": 3.0}, headers=H)
    assert r.status_code == 423
    client.post("/api/limits/self-exclude", json={"days": 2}, headers=H)
    r = client.post("/api/assistant", json={"messages": [{"role": "user", "content": "hola"}]}, headers=H)
    assert r.status_code == 423


def test_stale_lines_and_reference_parlay(client):
    from app.db import session_scope
    from app.models import Event
    from app.providers.base import ProviderQuote
    from app.services.events import add_quotes

    now = datetime.now(timezone.utc)
    with session_scope() as db:
        ev = next(e for e in db.query(Event).all() if e.home.name == "Arsenal" and e.status == "scheduled")
        eid = ev.id
        # Pinnacle antes y después de un movimiento hacia el local; las casas colombianas no cambiaron
        for ts, (h, d, a) in ((now - timedelta(hours=5), (1.80, 3.80, 4.60)), (now, (1.55, 4.30, 6.50))):
            add_quotes(db, ev, [ProviderQuote("t", "x", "pinnacle", "1x2", s, o) for s, o in (("home", h), ("draw", d), ("away", a))],
                       {}, "oddspapi", ts)
        db.commit()
    lines = client.get("/api/stale-lines?min_edge=0.02").json()["lines"]
    row = next(r for r in lines if r["event_id"] == eid and r["operator"] == "wplay" and r["selection_key"].startswith("1x2|home"))
    assert row["status"] == "retrasada" and row["ref_operator"] == "pinnacle"
    assert row["edge"] == pytest.approx(row["odds"] * row["p_fair"] - 1)
    assert all(r["operator"] not in ("pinnacle", "intl_consensus") for r in lines)

    # Sin cuotas colombianas para el filtro → combinada con cuotas de referencia, señalada como tal
    res = client.post("/api/parlay/search", json={"target_odds": 1.6, "min_odds": 1.4, "max_odds": 1.8, "min_legs": 1,
                                                  "max_legs": 1, "risk": "high", "operators": ["codere"]}).json()
    assert res["reference"] is True
    alt = next(a for a in res["alternatives"].values() if a["available"])
    assert alt["reference"] and alt["operator"] == "pinnacle" and "Referencia" in alt["operator_name"]
    assert "REFERENCIA" in res["messages"][0]
    res = client.post("/api/parlay/search", json={"target_odds": 1.6, "min_legs": 1, "max_legs": 1, "risk": "high",
                                                  "operators": ["codere"], "use_reference": False}).json()
    assert res["reference"] is False and not any(a["available"] for a in res["alternatives"].values())

    # Filtro por día: el día del partido lo incluye, otro día lo excluye
    day = client.get("/api/events/days").json()["days"]
    assert day and all({"date", "count", "finished"} <= set(d) for d in day)
    ev_day = next(e for e in client.get("/api/events?scope=upcoming").json()["events"] if e["id"] == eid)["start_time"]
    from zoneinfo import ZoneInfo

    d0 = datetime.fromisoformat(ev_day).astimezone(ZoneInfo("America/Bogota")).date()
    on = client.get(f"/api/events?date={d0.isoformat()}").json()["events"]
    assert any(e["id"] == eid for e in on)
    off = client.get(f"/api/events?date={(d0 + timedelta(days=3)).isoformat()}").json()["events"]
    assert all(e["id"] != eid for e in off)
    base = {"target_odds": 1.6, "min_odds": 1.4, "max_odds": 1.8, "min_legs": 1, "max_legs": 1, "risk": "high", "operators": ["codere"]}
    r_on = client.post("/api/parlay/search", json={**base, "dates": [d0.isoformat()]}).json()
    assert any(a["available"] for a in r_on["alternatives"].values())
    r_off = client.post("/api/parlay/search", json={**base, "dates": [(d0 + timedelta(days=3)).isoformat()]}).json()
    assert not any(a["available"] for a in r_off["alternatives"].values())

    q = client.get("/api/quotes").json()["quotes"]
    assert q and all(x["operator"] not in ("pinnacle", "intl_consensus") for x in q)


def _synthetic_odds_history(seed: int = 3) -> pd.DataFrame:
    """Partidos con cuota justa de Pinnacle y una «mejor cuota» que a veces la supera."""
    rng = np.random.default_rng(seed)
    rows = []
    for i in range(4000):
        p = rng.dirichlet([4, 2.5, 3])
        r = rng.choice(3, p=p)
        hg, ag = (1, 0) if r == 0 else (1, 1) if r == 1 else (0, 1)
        ps = 1 / (p * 1.03)
        mx = ps * rng.choice([0.97, 1.0, 1.08], size=3, p=[0.5, 0.35, 0.15])
        rows.append({"date": pd.Timestamp("2021-08-01", tz="UTC") + pd.Timedelta(hours=8 * i), "league": "E0",
                     "hg": hg, "ag": ag, "ps_h": ps[0], "ps_d": ps[1], "ps_a": ps[2], "psc_h": ps[0], "psc_d": ps[1],
                     "psc_a": ps[2], "max_h": mx[0], "max_d": mx[1], "max_a": mx[2], "odds_h": ps[0] * 0.97,
                     "odds_d": ps[1] * 0.97, "odds_a": ps[2] * 0.97})
    return pd.DataFrame(rows)


def test_agent_learns_picks_and_settles(client):
    from app.db import session_scope
    from app.models import AgentBet, Event
    from app.services import agent

    with session_scope() as db:
        res = agent.learn(db, _synthetic_odds_history())
        assert res["out_of_sample"]["n"] > 0 and res["policy"]["min_edge"] in agent.GRID
        pol, mv = agent.current_policy(db)
        assert mv is not None and mv.status == "champion"
        run = agent.run(db)
        assert run["new_picks"] >= 1
        picks = db.query(AgentBet).all()
        assert all(b.odds <= pol.max_odds and b.edge >= pol.min_edge for b in picks)
        assert len({b.event_id for b in picks}) == len(picks)  # una por partido
        assert agent.run(db)["new_picks"] == 0  # no repite
        b = picks[0]
        h0 = b.hash
        ev = db.get(Event, b.event_id)
        ev.status, ev.home_score, ev.away_score = "finished", 2, 0
        db.commit()
        assert agent.settle(db) >= 1
        db.refresh(b)
        assert b.result in ("won", "lost", "void", "half_won", "half_lost") and b.hash == h0
        payload = agent.export_payload(db)
        assert payload["record"]["settled"] >= 1 and payload["bankroll"]["current"] != agent.START_BANKROLL or b.result == "void"
        assert payload["backtest"]["out_of_sample"]["n"] > 0
        ev.status, ev.home_score, ev.away_score = "scheduled", None, None
        db.commit()
    r = client.get("/api/agent").json()
    assert "policy" in r and "predictions_check" in r


def test_stale_limit_by_source():
    from app.services.odds import stale_limit

    assert stale_limit("odds_api_net", False) == 900
    assert stale_limit("oddspapi", False) >= 8 * 3600
    assert stale_limit("manual", False) == 2 * 3600
    assert stale_limit("oddspapi", True) <= 60


def test_prediction_chain(client):
    from app.api.routes import record_upcoming
    from app.db import session_scope
    from app.services.predictions import verify_chain

    with session_scope() as db:
        out = record_upcoming(db)
        assert out["recorded"] >= 4
        assert verify_chain(db)["valid"]
    preds = client.get("/api/predictions").json()
    assert preds["chain"]["valid"]
    assert preds["predictions"][0]["probs"]


def test_results_with_closing_and_alerts(client, monkeypatch):
    from app.db import session_scope
    from app.export_static import _results_with_closing
    from app.models import Event
    from app.services import model_store
    from app.services.alerts import current_alerts

    with session_scope() as db:
        ev = db.query(Event).first()
        ev.status, ev.home_score, ev.away_score = "finished", 2, 1
        ev.start_time = datetime.now(timezone.utc) - timedelta(days=1)
        ev.external_ids = {**(ev.external_ids or {}), "football_data_uk": "X1"}
        db.flush()
        hist = pd.DataFrame([{"match_id": "X1", "psc_h": 1.9, "psc_d": 3.6, "psc_a": 4.4, "close_h": 1.85,
                              "close_d": 3.5, "close_a": 4.2, "close_o25": 1.95, "close_u25": 1.92}])
        monkeypatch.setattr(model_store, "football_history", lambda include_colombia=False: hist)
        res = _results_with_closing(db)
        r = next(x for x in res if x["event_id"] == ev.id)
        assert r["closing"]["source"] == "pinnacle_cierre"
        assert abs(sum(r["closing"]["fair_1x2"].values()) - 1) < 1e-9
        assert r["closing"]["fair_total_2_5"]["over"] < 0.5
        alerts = current_alerts(db)
        assert isinstance(alerts, list)
