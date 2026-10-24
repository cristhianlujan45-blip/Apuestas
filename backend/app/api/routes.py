"""API REST de la plataforma."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from ..config import get_settings
from ..db import get_db, session_scope
from ..engine.markets import MARKETS
from ..engine.montecarlo import summarize
from ..engine.odds_math import all_formats
from ..models import Alert, Event, IngestionLog, ModelVersion, OddsQuote, Operator, Prediction, User, UserBet
from ..services import auth, calculator, history, ingest, model_store, operators, predictions
from ..services.assistant import answer
from ..services.events import aware, event_dict
from ..services.odds import compare_event, compare_operators, import_manual_quotes, odds_history, parse_csv
from ..services.parlay.optimizer import ParlayRequest
from ..services.parlay.service import search_my_odds

router = APIRouter(prefix="/api")


# ---------------------------------------------------------------------------
# Estado
# ---------------------------------------------------------------------------

@router.get("/health")
def health() -> dict:
    return {"ok": True, "time": datetime.now(timezone.utc).isoformat()}


@router.get("/status")
def status(db: Session = Depends(get_db)) -> dict:
    s = get_settings()
    logs = db.scalars(select(IngestionLog).order_by(IngestionLog.started_at.desc()).limit(20))
    champ = {m.name: {"version": m.version, "created_at": aware(m.created_at).isoformat()}
             for m in db.scalars(select(ModelVersion).where(ModelVersion.status == "champion"))}
    return {
        "providers": {
            "odds_api_net": {"configured": bool(s.odds_api_net_key), "role": "Cuotas de operadores colombianos"},
            "api_football": {"configured": bool(s.api_football_key), "role": "Partidos, directo, estadísticas, Liga BetPlay"},
            "api_basketball": {"configured": bool(s.api_basketball_key or s.api_football_key), "role": "Baloncesto"},
            "football_data_uk": {"configured": True, "role": "Histórico, estadísticas y cuotas de referencia (gratuito)"},
            "statsbomb_open_data": {"configured": True, "role": "Eventos para xT / xA (gratuito)"},
            "anthropic": {"configured": bool(s.anthropic_api_key), "role": "Asistente conversacional (opcional)"},
            "redis": {"configured": bool(s.redis_url), "role": "Caché y pub/sub en directo"},
        },
        "database": "postgresql" if not s.is_sqlite else "sqlite",
        "counts": {
            "events": db.scalar(select(func.count(Event.id))),
            "upcoming": db.scalar(select(func.count(Event.id)).where(Event.status == "scheduled",
                                                                    Event.start_time > datetime.now(timezone.utc))),
            "live": db.scalar(select(func.count(Event.id)).where(Event.status == "live")),
            "quotes": db.scalar(select(func.count()).select_from(OddsQuote)),
            "colombian_quotes": db.scalar(select(func.count()).select_from(OddsQuote).where(
                OddsQuote.operator_key.in_(select(Operator.key).where(Operator.status == "authorized")))),
            "predictions": db.scalar(select(func.count(Prediction.id))),
        },
        "champion_models": champ,
        "ingestion": [{"provider": l.provider, "kind": l.kind, "status": l.status, "count": l.count,
                       "started_at": aware(l.started_at).isoformat(), "detail": l.detail} for l in logs],
    }


# ---------------------------------------------------------------------------
# Operadores
# ---------------------------------------------------------------------------

@router.get("/operators")
def list_operators(db: Session = Depends(get_db)) -> dict:
    reg = operators.load_registry()
    return {"source": reg["source"], "operators": [operators.operator_dict(o) for o in db.scalars(
        select(Operator).order_by(Operator.status, Operator.name))]}


class OperatorIn(BaseModel):
    key: str = Field(pattern=r"^[a-z0-9_]+$")
    name: str
    legal_name: str | None = None
    domains: list[str] = []
    contract: str | None = None
    feed_keys: dict[str, str] = {}
    parlays: bool | None = None
    same_event_parlays: bool | None = None
    live_betting: bool | None = None
    max_parlay_legs: int | None = None


@router.post("/operators")
def create_operator(body: OperatorIn, db: Session = Depends(get_db), _: User = Depends(auth.admin_user)) -> dict:
    try:
        return operators.operator_dict(operators.add_operator(db, body.model_dump()))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/operators/verify")
def verify_operators(db: Session = Depends(get_db), _: User = Depends(auth.admin_user)) -> dict:
    return operators.verify_against_coljuegos(db)


# ---------------------------------------------------------------------------
# Eventos y predicciones
# ---------------------------------------------------------------------------

def _event_query(scope: str, sport: str | None):
    now = datetime.now(timezone.utc)
    q = select(Event).options(joinedload(Event.home), joinedload(Event.away), joinedload(Event.competition))
    if scope == "live":
        q = q.where(Event.status == "live")
    elif scope == "today":
        q = q.where(Event.start_time >= now - timedelta(hours=3), Event.start_time < now + timedelta(hours=24))
    elif scope == "upcoming":
        q = q.where(Event.status == "scheduled", Event.start_time >= now)
    elif scope == "finished":
        q = q.where(Event.status == "finished").order_by(Event.start_time.desc())
    if sport:
        q = q.where(Event.sport == sport)
    if scope != "finished":
        q = q.order_by(Event.start_time)
    return q


@router.get("/events")
def list_events(scope: Literal["today", "live", "upcoming", "finished"] = "upcoming", sport: str | None = None,
                with_model: bool = True, limit: int = Query(100, le=400), db: Session = Depends(get_db)) -> dict:
    evs = list(db.scalars(_event_query(scope, sport).limit(limit)).unique())
    authorized = {o.key for o in db.scalars(select(Operator).where(Operator.status == "authorized"))}
    counts = dict(db.execute(select(OddsQuote.event_id, func.count(func.distinct(OddsQuote.operator_key)))
                             .where(OddsQuote.event_id.in_([e.id for e in evs]),
                                    OddsQuote.operator_key.in_(authorized))
                             .group_by(OddsQuote.event_id)).all()) if evs else {}
    out = []
    for ev in evs:
        d = event_dict(ev)
        d["colombian_operators"] = counts.get(ev.id, 0)
        if with_model:
            em = predictions.model_event(db, ev, n_draws=0)
            d["probs"] = em.summary.get("probs") or _ml_probs(em)
            d["live"] = em.summary.get("live")
            d["expected_goals"] = em.summary.get("expected_goals")
            d["data_sufficient"] = em.sufficient
            d["model_note"] = em.reason
        out.append(d)
    return {"scope": scope, "events": out}


def _ml_probs(em) -> dict | None:
    if em.outcomes is None:
        return None
    from ..engine.markets import Selection, UnsupportedMarket, price

    try:
        ph = price(Selection("moneyline", "home"), em.outcomes).p_win
        return {"home": ph, "away": 1 - ph}
    except UnsupportedMarket:
        return None


def _get_event(db: Session, event_id: int) -> Event:
    ev = db.scalar(select(Event).where(Event.id == event_id)
                   .options(joinedload(Event.home), joinedload(Event.away), joinedload(Event.competition)))
    if ev is None:
        raise HTTPException(404, "Evento no encontrado")
    return ev


@router.get("/events/{event_id}")
def get_event(event_id: int, db: Session = Depends(get_db)) -> dict:
    ev = _get_event(db, event_id)
    em = predictions.model_event(db, ev)
    cmp = compare_event(db, ev)
    from ..engine.markets import UnsupportedMarket, price
    from ..engine.montecarlo import probability_interval

    priced = []
    if em.outcomes is not None:
        for r in cmp["rows"]:
            from ..engine.markets import Selection

            sel = Selection.from_key(r["selection_key"])
            try:
                pr = price(sel, em.outcomes)
            except UnsupportedMarket:
                continue
            best = r["best"]
            interval = probability_interval(sel, em.draws) if em.draws and sel.market in predictions.GOAL_MARKETS else {}
            priced.append({**r, "model": {**pr.as_dict(), "p": pr.p_effective, "fair_odds": pr.fair_odds(),
                                          "interval": interval,
                                          "ev_best": pr.ev(best["odds"]) if best else None}})
    return {"event": event_dict(ev), "model": em.summary, "model_version": em.model_version,
            "data_sufficient": em.sufficient, "model_note": em.reason, "markets": priced or cmp["rows"],
            "margins": cmp["margins"], "operators_with_quotes": cmp["operators_with_quotes"]}


@router.get("/events/{event_id}/simulate")
def simulate(event_id: int, db: Session = Depends(get_db)) -> dict:
    ev = _get_event(db, event_id)
    em = predictions.model_event(db, ev)
    if em.outcomes is None:
        raise HTTPException(409, em.reason or "Sin modelo")
    res = summarize(em.outcomes)
    if em.draws:
        import numpy as np

        from ..engine.football.goals import outcome_probs

        draws = np.array([outcome_probs(o.weights.reshape(int(len(o.weights) ** 0.5), -1)) for o in em.draws])
        res["epistemic"] = {k: {"p10": float(np.percentile(draws[:, i], 10)),
                                "p50": float(np.percentile(draws[:, i], 50)),
                                "p90": float(np.percentile(draws[:, i], 90))}
                            for i, k in enumerate(["home", "draw", "away"])}
    return res


@router.get("/events/{event_id}/odds-history")
def get_odds_history(event_id: int, selection_key: str, db: Session = Depends(get_db)) -> list[dict]:
    return odds_history(db, event_id, selection_key)


@router.post("/predictions/run")
def run_predictions(db: Session = Depends(get_db), _: User = Depends(auth.admin_user)) -> dict:
    return record_upcoming(db)


def record_upcoming(db: Session, hours: int = 72) -> dict:
    now = datetime.now(timezone.utc)
    evs = db.scalars(select(Event).where(Event.status == "scheduled", Event.start_time > now,
                                         Event.start_time < now + timedelta(hours=hours))
                     .options(joinedload(Event.home), joinedload(Event.away), joinedload(Event.competition))).unique().all()
    n = 0
    for ev in evs:
        em = predictions.model_event(db, ev, n_draws=0)
        if predictions.record_prediction(db, em) is not None:
            n += 1
    db.commit()
    return {"recorded": n, "events": len(evs)}


@router.get("/predictions")
def list_predictions(limit: int = 200, db: Session = Depends(get_db)) -> dict:
    return {"predictions": history.prediction_log(db, limit), "chain": predictions.verify_chain(db)}


@router.get("/value")
def value(min_edge: float = 0.02, db: Session = Depends(get_db)) -> dict:
    cands, _, report = predictions.build_candidates(db)
    vb = predictions.value_bets([c for c in cands if c.data_sufficient], min_edge)
    return {"value_bets": vb, "report": report,
            "note": "Valor esperado positivo no equivale a alta probabilidad de acierto."}


# ---------------------------------------------------------------------------
# Cuotas
# ---------------------------------------------------------------------------

@router.get("/odds/compare/{event_id}")
def odds_compare(event_id: int, db: Session = Depends(get_db)) -> dict:
    return compare_event(db, _get_event(db, event_id))


@router.get("/odds/operators-compare")
def operators_compare(a: str, b: str, db: Session = Depends(get_db)) -> dict:
    return compare_operators(db, a, b)


@router.get("/surebets")
def surebets(stake: float = 100000.0, db: Session = Depends(get_db)) -> dict:
    from ..services.arbitrage import surebets_from_db

    return {"surebets": surebets_from_db(db, stake)}


@router.get("/odds/formats")
def odds_formats(odds: float) -> dict:
    return all_formats(odds)


class ManualQuote(BaseModel):
    sport: str = "football"
    competition: str | None = None
    start_time: str
    home: str
    away: str
    operator: str
    market: str
    selection: str
    line: float | None = None
    player: str | None = None
    odds: float
    captured_at: str | None = None


@router.post("/odds/manual")
def odds_manual(rows: list[ManualQuote], db: Session = Depends(get_db), _: User = Depends(auth.current_user)) -> dict:
    return import_manual_quotes(db, [r.model_dump() for r in rows])


@router.post("/odds/import")
async def odds_import(file: UploadFile = File(...), db: Session = Depends(get_db),
                      _: User = Depends(auth.current_user)) -> dict:
    text = (await file.read()).decode("utf-8-sig")
    return import_manual_quotes(db, parse_csv(text), "csv_import")


@router.get("/markets")
def markets() -> dict:
    return {"markets": MARKETS}


# ---------------------------------------------------------------------------
# PARLAY AI
# ---------------------------------------------------------------------------

class ParlayIn(BaseModel):
    target_odds: float = Field(gt=1.01, le=1000)
    min_odds: float | None = None
    max_odds: float | None = None
    min_legs: int = Field(2, ge=1, le=15)
    max_legs: int = Field(6, ge=1, le=15)
    sports: list[str] | None = None
    operators: list[str] | None = None
    markets: list[str] | None = None
    risk: Literal["low", "medium", "high"] = "medium"
    allow_same_event: bool = False
    same_day_only: bool = False
    max_hours_ahead: float | None = 72
    include_live: bool = False


@router.post("/parlay/search")
def parlay_search(body: ParlayIn, request: Request, db: Session = Depends(get_db),
                  user: User | None = Depends(auth.optional_user)) -> dict:
    block = auth.gate(db, user, request)
    if block:
        raise HTTPException(423, block)
    if body.max_legs < body.min_legs:
        raise HTTPException(400, "max_legs debe ser ≥ min_legs")
    try:
        return search_my_odds(db, ParlayRequest(**body.model_dump()), user.id if user else None)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


class InverseIn(BaseModel):
    stake_cop: float = Field(gt=0)
    target_profit_cop: float = Field(gt=0)
    max_legs: int = 6
    risk: Literal["low", "medium", "high"] = "medium"
    sports: list[str] | None = None
    operators: list[str] | None = None
    search: bool = True


@router.post("/parlay/inverse")
def parlay_inverse(body: InverseIn, request: Request, db: Session = Depends(get_db),
                   user: User | None = Depends(auth.optional_user)) -> dict:
    calc = calculator.required_odds(body.stake_cop, body.target_profit_cop)
    out = {"calculation": calc}
    if body.search:
        block = auth.gate(db, user, request)
        if block:
            raise HTTPException(423, block)
        target = calc["required_odds"]
        req = ParlayRequest(target_odds=target, min_odds=target, max_odds=target * 1.12, max_legs=body.max_legs,
                            risk=body.risk, sports=body.sports, operators=body.operators, min_legs=1)
        out["search"] = search_my_odds(db, req, user.id if user else None)
    return out


@router.get("/parlays")
def parlays(db: Session = Depends(get_db), user: User | None = Depends(auth.optional_user)) -> dict:
    return history.parlay_history(db, user.id if user else None)


class CalcIn(BaseModel):
    stake_cop: float | None = None
    odds: float | None = None
    target_profit_cop: float | None = None
    capital_cop: float | None = None
    probability: float | None = Field(None, ge=0, le=1)


@router.post("/calculator")
def calc(body: CalcIn) -> dict:
    out: dict = {}
    try:
        if body.stake_cop and body.odds:
            out["returns"] = calculator.returns(body.stake_cop, body.odds)
            if body.probability is not None:
                out["expected"] = calculator.expected(body.stake_cop, body.odds, body.probability)
        if body.stake_cop and body.target_profit_cop:
            out["required_odds"] = calculator.required_odds(body.stake_cop, body.target_profit_cop)
        if body.odds and body.target_profit_cop:
            out["required_stake"] = calculator.required_stake(body.odds, body.target_profit_cop)
        if body.capital_cop and body.stake_cop:
            out["bankroll"] = calculator.bankroll_check(body.stake_cop, body.capital_cop, body.probability, body.odds)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if not out:
        raise HTTPException(400, "Indique inversión y cuota, o inversión y ganancia deseada")
    return out


# ---------------------------------------------------------------------------
# Modelos, historial y aprendizaje
# ---------------------------------------------------------------------------

@router.get("/models")
def models(db: Session = Depends(get_db)) -> dict:
    return {"versions": history.model_versions(db), "validation_runs": history.validation_runs(db)}


@router.get("/models/performance")
def perf(sport: str = "football", db: Session = Depends(get_db)) -> dict:
    return history.performance(db, sport)


def _train_job(kind: str) -> None:
    with session_scope() as db:
        if kind == "football":
            model_store.train_football(db)
        else:
            model_store.train_other_sports(db)


@router.post("/models/train")
def train(background: BackgroundTasks, kind: Literal["football", "other"] = "football",
          _: User = Depends(auth.admin_user)) -> dict:
    background.add_task(_train_job, kind)
    return {"started": True, "kind": kind}


@router.get("/football/ratings")
def ratings(group: str = "ENG", db: Session = Depends(get_db)) -> dict:
    eng = model_store.football_engine(db)
    if eng is None or group not in eng.dc:
        raise HTTPException(404, "Modelo no entrenado para ese grupo")
    dc = eng.dc[group]
    return {"group": group, "groups": sorted(eng.dc), "home_advantage": dc.home_adv, "rho": dc.rho,
            "n_matches": dc.n_matches, "ratings": dc.ratings_table(), "version": eng.version}


@router.get("/football/team")
def team_stats(team: str, n: int = 10, db: Session = Depends(get_db)) -> dict:
    from ..services.assistant import Toolbox

    return Toolbox(db).ultimos_partidos(team, n)


@router.get("/football/xt")
def xt(competition_id: int = 43, season_id: int = 106, max_matches: int = 20) -> dict:
    """xT y xA desde StatsBomb Open Data (por defecto: Mundial 2022)."""
    import json

    from ..config import DATA_DIR
    from ..engine.football import xt as xtmod

    path = DATA_DIR / "models" / f"xt_{competition_id}_{season_id}.json"
    if path.exists():
        return json.loads(path.read_text())
    res = xtmod.build_from_open_data(competition_id, season_id, max_matches)
    xtmod.save(res)
    return res


@router.post("/settle")
def settle(db: Session = Depends(get_db), _: User = Depends(auth.admin_user)) -> dict:
    return history.settle_parlays(db)


# ---------------------------------------------------------------------------
# Ingesta
# ---------------------------------------------------------------------------

@router.post("/ingest/{kind}")
def run_ingest(kind: Literal["fixtures", "odds", "live", "api_football", "results"], background: BackgroundTasks,
               _: User = Depends(auth.admin_user)) -> dict:
    def job():
        with session_scope() as db:
            if kind == "fixtures":
                ingest.ingest_football_data_fixtures(db)
            elif kind == "odds":
                ingest.ingest_odds_api_net(db)
            elif kind == "live":
                ingest.ingest_odds_api_net(db, live=True)
            elif kind == "api_football":
                ingest.ingest_api_football(db)
            elif kind == "results":
                ingest.update_football_results(db, model_store.football_history(include_colombia=False))

    background.add_task(job)
    return {"started": kind}


@router.get("/alerts")
def alerts(db: Session = Depends(get_db)) -> list[dict]:
    rows = db.scalars(select(Alert).order_by(Alert.created_at.desc()).limit(100))
    return [{"id": a.id, "kind": a.kind, "severity": a.severity, "message": a.message, "acknowledged": a.acknowledged,
             "created_at": aware(a.created_at).isoformat()} for a in rows]


@router.post("/alerts/{alert_id}/ack")
def ack(alert_id: int, db: Session = Depends(get_db), _: User = Depends(auth.current_user)) -> dict:
    a = db.get(Alert, alert_id)
    if a is None:
        raise HTTPException(404)
    a.acknowledged = True
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Asistente
# ---------------------------------------------------------------------------

class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatIn(BaseModel):
    messages: list[ChatMessage]


@router.post("/assistant")
def assistant(body: ChatIn, request: Request, db: Session = Depends(get_db),
              user: User | None = Depends(auth.optional_user)) -> dict:
    block = auth.gate(db, user, request)
    if block:
        raise HTTPException(423, block)
    return answer(db, [m.model_dump() for m in body.messages[-20:]], user.id if user else None)


# ---------------------------------------------------------------------------
# Usuarios y juego responsable
# ---------------------------------------------------------------------------

class RegisterIn(BaseModel):
    email: str
    password: str
    birthdate: date
    accept_terms: bool


class LoginIn(BaseModel):
    email: str
    password: str


@router.post("/auth/register")
def register(body: RegisterIn, db: Session = Depends(get_db)) -> dict:
    try:
        u = auth.register(db, body.email, body.password, body.birthdate, body.accept_terms)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"token": auth.token_for(u), "user": {"id": u.id, "email": u.email, "is_admin": u.is_admin}}


@router.post("/auth/login")
def login(body: LoginIn, db: Session = Depends(get_db)) -> dict:
    try:
        u, token = auth.login(db, body.email, body.password)
    except ValueError as exc:
        raise HTTPException(401, str(exc)) from exc
    return {"token": token, "user": {"id": u.id, "email": u.email, "is_admin": u.is_admin}}


@router.get("/auth/me")
def me(request: Request, db: Session = Depends(get_db), user: User = Depends(auth.current_user)) -> dict:
    return {"id": user.id, "email": user.email, "is_admin": user.is_admin, "limits": auth.limits_dict(db, user),
            "gate": auth.gate(db, user, request)}


class LimitsIn(BaseModel):
    daily_stake_cop: float | None = None
    weekly_stake_cop: float | None = None
    monthly_stake_cop: float | None = None
    session_minutes: int | None = None


@router.put("/limits")
def put_limits(body: LimitsIn, db: Session = Depends(get_db), user: User = Depends(auth.current_user)) -> dict:
    return auth.update_limits(db, user, body.model_dump(exclude_unset=True))


class ExcludeIn(BaseModel):
    days: int = Field(ge=1, le=3650)


@router.post("/limits/self-exclude")
def self_exclude(body: ExcludeIn, db: Session = Depends(get_db), user: User = Depends(auth.current_user)) -> dict:
    return auth.self_exclude(db, user, body.days)


class BetIn(BaseModel):
    operator: str
    description: str
    stake_cop: float = Field(gt=0)
    odds: float = Field(gt=1)
    parlay_id: int | None = None


@router.post("/bets")
def log_bet(body: BetIn, db: Session = Depends(get_db), user: User = Depends(auth.current_user)) -> dict:
    b = UserBet(user_id=user.id, operator_key=body.operator, description=body.description, stake_cop=body.stake_cop,
                odds=body.odds, parlay_id=body.parlay_id)
    db.add(b)
    db.commit()
    return {"id": b.id, "limits": auth.limits_dict(db, user), "gate": auth.gate(db, user)}


@router.get("/bets")
def bets(db: Session = Depends(get_db), user: User = Depends(auth.current_user)) -> list[dict]:
    return [{"id": b.id, "operator": b.operator_key, "description": b.description, "stake_cop": b.stake_cop,
             "odds": b.odds, "placed_at": aware(b.placed_at).isoformat(), "result": b.result}
            for b in db.scalars(select(UserBet).where(UserBet.user_id == user.id).order_by(UserBet.placed_at.desc()))]


@router.get("/responsible-gaming")
def responsible() -> dict:
    return {
        "min_age": get_settings().min_age,
        "principles": [
            "Esta plataforma es una herramienta de análisis: no garantiza ganancias ni coloca apuestas.",
            "Apueste solo dinero que pueda permitirse perder y fije límites antes de empezar.",
            "Una probabilidad estimada alta no significa que una apuesta tenga valor.",
            "Las combinadas multiplican el margen del operador: su valor esperado suele ser negativo.",
            "Si apostar deja de ser entretenimiento, use la autoexclusión y busque ayuda.",
        ],
        "resources": [
            {"name": "Coljuegos — Juego responsable", "url": "https://www.coljuegos.gov.co/"},
            {"name": "Coljuegos — Línea gratuita nacional", "phone": "01 8000 18 28 88"},
            {"name": "Denuncias de juego ilegal", "email": "denunciealilegal@coljuegos.gov.co"},
            {"name": "Línea 106 (salud mental, Bogotá)", "phone": "106"},
            {"name": "Línea 192 opción 4 (Ministerio de Salud)", "phone": "192"},
        ],
    }
