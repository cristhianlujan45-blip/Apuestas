"""Predicción de eventos, registro inmutable y generación de candidatos para PARLAY AI."""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from ..engine.football.engine import LEAGUE_TO_GROUP, FootballEngine, FootballPrediction
from ..engine.football.live import LiveState, live_outcomes
from ..engine.markets import Outcomes, Selection, UnsupportedMarket, price
from ..engine.montecarlo import matrix_outcomes, probability_interval
from ..models import Event, EventStats, Operator, Prediction
from ..names import similarity
from ..services.parlay.optimizer import Candidate
from . import model_store
from .events import aware
from .odds import latest_quotes, quote_selection

log = logging.getLogger(__name__)

COMPETITION_CODES = {
    "premier league": "E0", "epl": "E0", "championship": "E1", "laliga": "SP1", "la liga": "SP1",
    "serie a": "I1", "bundesliga": "D1", "ligue 1": "F1", "eredivisie": "N1", "primeira liga": "P1",
    "liga portugal": "P1", "super lig": "T1", "süper lig": "T1", "liga profesional": "ARG", "brasileirao": "BRA",
    "liga mx": "MEX", "mls": "USA", "primera a": "COL", "liga betplay": "COL", "liga dimayor": "COL",
}


@dataclass
class EventModel:
    event: Event
    sport: str
    outcomes: Outcomes | None
    summary: dict
    draws: list[Outcomes]
    sufficient: bool
    model_version: str
    reason: str | None = None
    matrix: np.ndarray | None = None  # matriz de marcadores (fútbol), filas = goles local


def _football_names(engine: FootballEngine, ev: Event) -> tuple[str | None, str, str]:
    """Resuelve grupo de ligas y nombres tal como los conoce el modelo."""
    code = None
    if ev.competition is not None:
        code = (ev.competition.external_ids or {}).get("code") or COMPETITION_CODES.get(ev.competition.name.lower())
    names_h = [ev.home.name, *(ev.home.aliases or [])]
    names_a = [ev.away.name, *(ev.away.aliases or [])]
    best = (None, ev.home.name, ev.away.name, 0.0)
    groups = [LEAGUE_TO_GROUP.get(code, code)] if code else []
    groups += [g for g in engine.dc if g not in groups]
    for g in groups:
        dc = engine.dc.get(g)
        if dc is None:
            continue
        h = max(((t, max(similarity(n, t) for n in names_h)) for t in dc.teams), key=lambda x: x[1], default=(None, 0))
        a = max(((t, max(similarity(n, t) for n in names_a)) for t in dc.teams), key=lambda x: x[1], default=(None, 0))
        score = min(h[1], a[1])
        if score > best[3]:
            best = (g, h[0], a[0], score)
        if score >= 0.99:
            break
    if best[3] < 0.8:
        return (LEAGUE_TO_GROUP.get(code, code) if code else None), ev.home.name, ev.away.name
    return best[0], best[1], best[2]


def _reference_1x2(db: Session, ev: Event) -> tuple[float, float, float] | None:
    """Cuotas de referencia (Pinnacle si existe; si no, consenso internacional)."""
    quotes = [q for q in latest_quotes(db, [ev.id], ["pinnacle", "intl_consensus"]) if q.market_key == "1x2"]
    for op in ("pinnacle", "intl_consensus"):
        sel = {q.selection: q.odds for q in quotes if q.operator_key == op}
        if {"home", "draw", "away"} <= set(sel):
            return sel["home"], sel["draw"], sel["away"]
    return None


def _latest_live_stats(db: Session, ev: Event) -> dict:
    st = db.scalars(select(EventStats).where(EventStats.event_id == ev.id).order_by(EventStats.captured_at.desc())).first()
    return st.stats if st else {}


def model_event(db: Session, ev: Event, n_draws: int = 120) -> EventModel:
    if ev.sport == "football":
        eng = model_store.football_engine(db)
        if eng is None:
            return EventModel(ev, ev.sport, None, {}, [], False, "-", "Modelo de fútbol no entrenado")
        group, home, away = _football_names(eng, ev)
        league = next((lg for lg, g in LEAGUE_TO_GROUP.items() if g == group), group or "UNK")
        pred: FootballPrediction = eng.predict(league, home, away, aware(ev.start_time), _reference_1x2(db, ev),
                                               n_draws=n_draws)
        summary = pred.summary()
        summary["model_names"] = {"home": home, "away": away, "group": group}
        if ev.status == "live" and ev.minute is not None:
            st = _latest_live_stats(db, ev)
            red_h, red_a = int(st.get("home_red") or 0), int(st.get("away_red") or 0)
            live_state = LiveState(minute=ev.minute, home_goals=ev.home_score or 0, away_goals=ev.away_score or 0,
                                   home_red=red_h, away_red=red_a, home_xg=st.get("home_xg"), away_xg=st.get("away_xg"),
                                   home_sot=st.get("home_sot"), away_sot=st.get("away_sot"))
            lam, mu = pred.exp_goals
            out, info = live_outcomes(lam, mu, live_state)
            summary["live"] = info
            shape = (int(out["home"].max()) + 1, int(out["away"].max()) + 1)
            return EventModel(ev, ev.sport, out, summary, [], pred.data_quality.get("sufficient", False),
                              pred.model_version, matrix=out.weights.reshape(shape))
        has_counts = bool(pred.count_params)
        out = pred.sample_outcomes(20000) if has_counts else pred.grid_outcomes()
        draws = [matrix_outcomes(m) for m in pred.draws_matrices]
        return EventModel(ev, ev.sport, out, summary, draws, pred.data_quality.get("sufficient", False),
                          pred.model_version, matrix=pred.matrix)
    sm = model_store.sport_model(db, ev.sport)
    if sm is None:
        return EventModel(ev, ev.sport, None, {}, [], False, "-",
                          f"Sin modelo entrenado para {ev.sport}: importe histórico real (ver docs/DATOS.md)")
    m = sm["model"]
    if ev.sport == "basketball":
        players = {}
        props = sm.get("props")
        if props is not None:
            for team in (ev.home.name, ev.away.name):
                for p in props.team_players(team):
                    proj = props.projection(team, p)
                    if proj:
                        players[p] = proj
        out = m.outcomes(ev.home.name, ev.away.name, players=players)
        pr = out.meta["prediction"]
        ok = pr["data_quality"]["home_known"] and pr["data_quality"]["away_known"]
        return EventModel(ev, ev.sport, out, {"prediction": pr, "players": list(players)}, [], ok, sm["version"])
    if ev.sport == "tennis":
        out = m.outcomes(ev.home.name, ev.away.name, ev.surface or "Hard", ev.best_of or 3)
        pr = out.meta["prediction"]
        return EventModel(ev, ev.sport, out, {"prediction": pr}, [], pr["data_quality"]["sufficient"], sm["version"])
    out = m.outcomes(ev.home.name, ev.away.name)
    dq = out.meta.get("data_quality", {})
    ok = all(v for k, v in dq.items() if k.endswith("known")) and all(v >= 5 for k, v in dq.items() if k.startswith("games"))
    return EventModel(ev, ev.sport, out, {"meta": {k: v for k, v in out.meta.items()}}, [], ok, sm["version"])


# ---------------------------------------------------------------------------
# Registro inmutable con cadena de hashes
# ---------------------------------------------------------------------------

def _canon(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def record_prediction(db: Session, em: EventModel, kind: str = "prematch") -> Prediction | None:
    if em.outcomes is None:
        return None
    payload = {"summary": em.summary, "sport": em.sport, "sufficient": em.sufficient}
    if em.sport == "football" and "probs" in em.summary:
        payload["probs_1x2"] = em.summary["probs"]
    else:
        out = em.outcomes
        try:
            ph = price(Selection("moneyline", "home"), out).p_win
            payload["probs_moneyline"] = {"home": ph, "away": 1 - ph}
        except UnsupportedMarket:
            pass
    if em.sport == "football":
        payload["totals"] = {f"over_{line}": price(Selection("total_goals", "over", line), em.outcomes).p_win
                             for line in (1.5, 2.5, 3.5)}
    # Foto de las mejores cuotas colombianas en el momento de la predicción (para ROI posterior)
    probs = payload.get("probs_1x2") or payload.get("probs_moneyline") or {}
    market = "1x2" if "probs_1x2" in payload else "moneyline"
    authorized = {o.key for o in db.scalars(select(Operator).where(Operator.status == "authorized"))}
    snap: dict = {}
    for q in latest_quotes(db, [em.event.id], sorted(authorized)):
        if q.market_key == market and q.is_available and q.selection in probs:
            cur = snap.get(q.selection)
            if cur is None or q.odds > cur["odds"]:
                snap[q.selection] = {"odds": q.odds, "operator": q.operator_key,
                                     "ev": probs[q.selection] * q.odds - 1,
                                     "captured_at": aware(q.captured_at).isoformat()}
    payload["market_snapshot"] = snap
    payload = json.loads(_canon(payload))
    prev = db.scalars(select(Prediction).order_by(Prediction.id.desc())).first()
    prev_hash = prev.hash if prev else "0" * 64
    created = datetime.now(timezone.utc)
    h = hashlib.sha256((prev_hash + _canon(payload) + str(em.event.id) + created.isoformat()).encode()).hexdigest()
    p = Prediction(event_id=em.event.id, model_name=f"{em.sport}_ensemble", model_version=em.model_version, kind=kind,
                   minute=em.event.minute if kind == "live" else None, payload=payload, created_at=created,
                   prev_hash=prev_hash, hash=h)
    db.add(p)
    db.flush()
    return p


def verify_chain(db: Session) -> dict:
    prev = "0" * 64
    n = 0
    for p in db.scalars(select(Prediction).order_by(Prediction.id)):
        created = aware(p.created_at)
        expect = hashlib.sha256((prev + _canon(p.payload) + str(p.event_id) + created.isoformat()).encode()).hexdigest()
        if p.prev_hash != prev or p.hash != expect:
            return {"valid": False, "broken_at": p.id, "checked": n}
        prev = p.hash
        n += 1
    return {"valid": True, "checked": n}


# ---------------------------------------------------------------------------
# Candidatos para el optimizador
# ---------------------------------------------------------------------------

def build_candidates(db: Session, events: list[Event] | None = None, include_live: bool = False,
                     cache: dict[int, EventModel] | None = None) -> tuple[list[Candidate], dict[int, Outcomes], dict]:
    authorized = {o.key for o in db.scalars(select(Operator).where(Operator.status == "authorized"))}
    if events is None:
        stmt = select(Event).options(joinedload(Event.home), joinedload(Event.away), joinedload(Event.competition))
        if include_live:
            stmt = stmt.where(Event.status.in_(["scheduled", "live"]))
        else:
            stmt = stmt.where(Event.status == "scheduled", Event.start_time > datetime.now(timezone.utc))
        events = list(db.scalars(stmt).unique())
    quotes = latest_quotes(db, [e.id for e in events], sorted(authorized))
    by_event: dict[int, list] = {}
    for q in quotes:
        if q.is_available:
            by_event.setdefault(q.event_id, []).append(q)
    cands: list[Candidate] = []
    outcomes: dict[int, Outcomes] = {}
    report = {"events_with_quotes": len(by_event), "events_modeled": 0, "unpriceable": 0, "no_model": {}}
    cache = cache if cache is not None else {}
    for ev in events:
        qs = by_event.get(ev.id)
        if not qs:
            continue
        em = cache.get(ev.id) or model_event(db, ev)
        cache[ev.id] = em
        if em.outcomes is None:
            report["no_model"][ev.sport] = em.reason
            continue
        report["events_modeled"] += 1
        outcomes[ev.id] = em.outcomes
        for q in qs:
            sel = quote_selection(q)
            try:
                pr = price(sel, em.outcomes)
            except UnsupportedMarket:
                report["unpriceable"] += 1
                continue
            interval = probability_interval(sel, em.draws) if em.draws and sel.market in GOAL_MARKETS else {}
            cands.append(Candidate(
                event_id=ev.id, event_label=ev.label, sport=ev.sport,
                competition=ev.competition.name if ev.competition else None, start_time=aware(ev.start_time),
                selection=sel, selection_label=sel.describe(ev.home.name, ev.away.name), operator_key=q.operator_key,
                odds=q.odds, captured_at=aware(q.captured_at), pricing=pr,
                p_low=interval.get("low"), p_high=interval.get("high"), data_sufficient=em.sufficient,
                is_live=ev.status == "live", source=q.source,
            ))
    return cands, outcomes, report


GOAL_MARKETS = {"1x2", "double_chance", "dnb", "total_goals", "btts", "correct_score", "asian_handicap",
                "european_handicap", "team_total_home", "team_total_away"}


def value_bets(cands: list[Candidate], min_edge: float = 0.02) -> list[dict]:
    """Selecciones con EV positivo (no confundir con alta probabilidad de acierto)."""
    out = []
    for c in cands:
        if c.ev >= min_edge:
            d = c.as_dict()
            d["implied_probability"] = 1 / c.odds
            d["edge_pct"] = c.ev * 100
            d["kelly_quarter"] = max(0.0, (c.p * c.odds - 1) / (c.odds - 1) / 4) if c.odds > 1 else 0
            out.append(d)
    return sorted(out, key=lambda d: d["ev"], reverse=True)


def outcome_draw_summary(draws: list[np.ndarray]) -> dict:
    if not draws:
        return {}
    arr = np.array(draws)
    return {"p10": np.percentile(arr, 10, axis=0).tolist(), "p90": np.percentile(arr, 90, axis=0).tolist()}
