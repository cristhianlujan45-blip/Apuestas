"""Ingesta de datos reales desde los proveedores configurados."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from ..config import get_settings
from ..models import Event, IngestionLog, Operator
from ..providers.api_sports import ApiFootball
from ..providers.base import ProviderEvent, ProviderNotConfigured, ProviderQuote
from ..providers.football_data_uk import LEAGUE_NAMES, FootballDataUK
from ..providers.odds_api_net import OddsApiNet
from .events import add_quotes, add_stats, upsert_event
from .operators import feed_to_operator

log = logging.getLogger(__name__)


class _Log:
    def __init__(self, db: Session, provider: str, kind: str):
        self.db = db
        self.row = IngestionLog(provider=provider, kind=kind)
        db.add(self.row)
        db.flush()

    def done(self, count: int, **detail) -> dict:
        self.row.finished_at = datetime.now(timezone.utc)
        self.row.status = "ok"
        self.row.count = count
        self.row.detail = detail
        self.db.commit()
        return {"provider": self.row.provider, "kind": self.row.kind, "count": count, **detail}

    def fail(self, err: Exception) -> dict:
        self.row.finished_at = datetime.now(timezone.utc)
        self.row.status = "error"
        self.row.detail = {"error": str(err)[:500]}
        self.db.commit()
        return {"provider": self.row.provider, "kind": self.row.kind, "error": str(err)}


def _fd_event(row: dict) -> ProviderEvent:
    league = row["league"]
    name, country = LEAGUE_NAMES.get(league, (league, None))
    finished = not pd.isna(row.get("hg")) if "hg" in row else False
    return ProviderEvent(
        provider="football_data_uk", external_id=row["match_id"], sport="football",
        home=row["home"], away=row["away"], start_time=pd.Timestamp(row["date"]).to_pydatetime(),
        competition=name, country=country, status="finished" if finished else "scheduled",
        home_score=int(row["hg"]) if finished else None, away_score=int(row["ag"]) if finished else None,
        extra={"referee": row.get("referee") if isinstance(row.get("referee"), str) else None},
    )


def _fd_reference_quotes(row: dict, ext_id: str) -> list[ProviderQuote]:
    """Cuotas de referencia internacional (no colombianas) publicadas por football-data."""
    out = []
    pairs = [
        ("intl_consensus", "1x2", "home", None, row.get("odds_h")),
        ("intl_consensus", "1x2", "draw", None, row.get("odds_d")),
        ("intl_consensus", "1x2", "away", None, row.get("odds_a")),
        ("pinnacle", "1x2", "home", None, row.get("ps_h")),
        ("pinnacle", "1x2", "draw", None, row.get("ps_d")),
        ("pinnacle", "1x2", "away", None, row.get("ps_a")),
        ("intl_consensus", "total_goals", "over", 2.5, row.get("o25")),
        ("intl_consensus", "total_goals", "under", 2.5, row.get("u25")),
    ]
    ah = row.get("ah_line")
    if ah is not None and not pd.isna(ah):
        pairs += [("intl_consensus", "asian_handicap", "home", float(ah), row.get("ah_h")),
                  ("intl_consensus", "asian_handicap", "away", -float(ah), row.get("ah_a"))]
    for op, m, s, line, odds in pairs:
        if odds is None or pd.isna(odds) or odds <= 1:
            continue
        out.append(ProviderQuote("football_data_uk", ext_id, op, m, s, float(odds), line=line))
    return out


def ingest_football_data_fixtures(db: Session) -> dict:
    lg = _Log(db, "football_data_uk", "fixtures")
    try:
        fx = FootballDataUK().fixtures()
        now = datetime.now(timezone.utc)
        n_ev = n_q = 0
        for row in fx.to_dict("records"):
            pe = _fd_event(row)
            if pe.start_time < now - timedelta(hours=3):
                continue
            ev = upsert_event(db, pe, competition_code=row["league"])
            n_ev += 1
            n_q += add_quotes(db, ev, _fd_reference_quotes(row, pe.external_id), {}, "football_data_uk", now)
        return lg.done(n_ev, quotes=n_q)
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        return lg.fail(exc)


def update_football_results(db: Session, history: pd.DataFrame) -> dict:
    """Actualiza resultados de eventos no finalizados usando el histórico descargado."""
    lg = _Log(db, "football_data_uk", "results")
    pending = db.scalars(select(Event).where(Event.sport == "football", Event.status.in_(["scheduled", "live"]),
                                             Event.start_time < datetime.now(timezone.utc))
                         .options(joinedload(Event.home), joinedload(Event.away))).unique().all()
    if not pending or history.empty:
        return lg.done(0)
    h = history.dropna(subset=["hg", "ag"])
    by_id = {r["match_id"]: r for r in h.to_dict("records")}
    n = 0
    for ev in pending:
        mid = (ev.external_ids or {}).get("football_data_uk")
        row = by_id.get(mid) if mid else None
        if row is None:
            # emparejar por nombres y fecha
            day = h[(pd.to_datetime(h["date"]) - pd.Timestamp(ev.start_time).tz_localize(None if ev.start_time.tzinfo else "UTC")).abs() < pd.Timedelta(hours=6)]
            cand = day[(day["home"] == ev.home.name) & (day["away"] == ev.away.name)]
            row = cand.iloc[0].to_dict() if len(cand) else None
        if row is None:
            continue
        ev.status = "finished"
        ev.home_score, ev.away_score = int(row["hg"]), int(row["ag"])
        stats = {k: (None if pd.isna(row.get(k)) else float(row[k])) for k in
                 ("hs", "as", "hst", "ast", "hc", "ac", "hy", "ay", "hr", "ar", "hthg", "htag") if k in row}
        add_stats(db, ev, "football_data_uk", stats, 90, True)
        n += 1
    return lg.done(n)


def ingest_odds_api_net(db: Session, sports: list[str] | None = None, hours_ahead: int = 72,
                        live: bool = False, max_events: int = 150) -> dict:
    s = get_settings()
    provider = OddsApiNet()
    lg = _Log(db, "odds_api_net", "live" if live else "prematch")
    if not provider.configured:
        return lg.fail(ProviderNotConfigured("ODDS_API_NET_KEY no configurada: sin cuotas colombianas en vivo. "
                                             "Use la carga manual o CSV de cuotas."))
    try:
        fmap = feed_to_operator(db, "odds_api_net")
        books = [k for k, v in fmap.items()
                 if v == "pinnacle" or db.scalar(select(Operator.status).where(Operator.key == v)) == "authorized"]
        total_ev = total_q = 0
        unmapped: dict[str, int] = {}
        for sport in sports or ["football", "basketball", "tennis", "baseball", "volleyball"]:
            events = provider.events(sport, hours_ahead=hours_ahead, live=live)[:max_events]
            for pe in events:
                ev = upsert_event(db, pe)
                quotes, meta = provider.odds(pe, books)
                captured = datetime.now(timezone.utc)
                total_q += add_quotes(db, ev, quotes, fmap, "odds_api_net", captured)
                for k, v in meta["unmapped"].items():
                    unmapped[k] = unmapped.get(k, 0) + v
                total_ev += 1
                db.commit()
        _ = s
        return lg.done(total_ev, quotes=total_q, unmapped_markets=dict(sorted(unmapped.items(), key=lambda kv: -kv[1])[:30]))
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        return lg.fail(exc)


def ingest_oddspapi(db: Session, force: bool = False) -> dict:
    """Cuotas de BetPlay y Rushbet (OddsPapi, plan gratuito) respetando el cupo mensual."""
    from ..providers import oddspapi

    provider = oddspapi.OddsPapi()
    if not provider.configured:
        lg = _Log(db, "oddspapi", "odds")
        return lg.fail(ProviderNotConfigured("ODDSPAPI_KEY no configurada (plan gratuito en oddspapi.io)"))
    last = db.scalars(select(IngestionLog).where(IngestionLog.provider == "oddspapi", IngestionLog.kind == "odds",
                                                 IngestionLog.status == "ok").order_by(IngestionLog.started_at.desc())).first()
    from .events import aware

    if not force and not oddspapi.due(aware(last.started_at) if last else None):
        return {"provider": "oddspapi", "skipped": "cupo: se consulta cada ODDSPAPI_MIN_HOURS horas"}
    lg = _Log(db, "oddspapi", "odds")
    try:
        events, quotes, meta = provider.odds()
        by_ext = {}
        for pe in events:
            by_ext[pe.external_id] = upsert_event(db, pe)
        captured = datetime.now(timezone.utc)
        n = 0
        groups: dict[str, list] = {}
        for q in quotes:
            groups.setdefault(q.external_event_id, []).append(q)
        for ext, qs in groups.items():
            ev = by_ext.get(ext)
            if ev is not None:
                n += add_quotes(db, ev, qs, {}, "oddspapi", captured)
        return lg.done(len(events), quotes=n, **meta)
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        return lg.fail(exc)


def ingest_api_football(db: Session, days: int = 2, include_live: bool = True,
                        stats_for_live: bool = True) -> dict:
    api = ApiFootball()
    lg = _Log(db, "api_football", "fixtures")
    if not api.configured:
        return lg.fail(ProviderNotConfigured("API_FOOTBALL_KEY no configurada: sin datos en directo ni Liga BetPlay"))
    try:
        n = 0
        today = date.today()
        for d in range(days):
            for pe in api.fixtures_by_date(today + timedelta(days=d)):
                upsert_event(db, pe)
                n += 1
        live_n = 0
        if include_live:
            for pe in api.live():
                ev = upsert_event(db, pe)
                live_n += 1
                if stats_for_live:
                    st = api.statistics(pe.external_id, minute=pe.minute)
                    add_stats(db, ev, "api_football", st.stats, pe.minute, False)
        return lg.done(n, live=live_n)
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        return lg.fail(exc)


def colombia_history(seasons: list[int]) -> pd.DataFrame:
    """Histórico de la Liga BetPlay desde API-Football (para el modelo de goles)."""
    api = ApiFootball()
    rows = []
    for season in seasons:
        for pe in api.league_season(239, season):
            if pe.status != "finished" or pe.home_score is None:
                continue
            rows.append({"date": pe.start_time, "league": "COL", "season": str(season), "home": pe.home,
                         "away": pe.away, "hg": pe.home_score, "ag": pe.away_score,
                         "match_id": f"COL:{pe.external_id}"})
    return pd.DataFrame(rows)


def ingest_injuries(db: Session, max_fixtures: int = 10, hours_ahead: int = 30) -> dict:
    """Bajas confirmadas (API-Football) para los próximos partidos con cuotas colombianas.

    Calcula para cada equipo un factor de ataque: 1 − 0.6·Σ participación en goles
    de los jugadores ausentes (goles+asistencias por partido / goles del equipo por
    partido), con un máximo de −25 %. Es una heurística documentada; las bajas
    defensivas no se modelan todavía.
    """
    from ..models import OddsQuote, Operator

    api = ApiFootball()
    lg = _Log(db, "api_football", "injuries")
    if not api.configured:
        return lg.fail(ProviderNotConfigured("API_FOOTBALL_KEY no configurada: sin bajas ni alineaciones"))
    now = datetime.now(timezone.utc)
    auth = select(Operator.key).where(Operator.status == "authorized")
    with_quotes = select(OddsQuote.event_id).where(OddsQuote.operator_key.in_(auth)).distinct()
    evs = db.scalars(select(Event).where(Event.sport == "football", Event.status == "scheduled",
                                         Event.start_time > now, Event.start_time < now + timedelta(hours=hours_ahead))
                     .options(joinedload(Event.home), joinedload(Event.away))
                     .order_by(Event.id.in_(with_quotes).desc(), Event.start_time)).unique().all()
    done = 0
    try:
        for ev in evs:
            fid = (ev.external_ids or {}).get("api_football")
            if not fid:
                continue
            avail = (ev.result_detail or {}).get("availability") or {}
            if avail.get("checked_at") and (now - datetime.fromisoformat(avail["checked_at"])).total_seconds() < 6 * 3600:
                continue
            inj = api.injuries(fid)
            season = (ev.result_detail or {}).get("season") or now.year
            rd = ev.result_detail or {}
            teams = {"home": rd.get("home_id"), "away": rd.get("away_id")}
            res = {"checked_at": now.isoformat(), "home": {"missing": []}, "away": {"missing": []}}
            for side, tid in teams.items():
                share = 0.0
                for p in [x for x in inj if x["team_id"] == tid and (x.get("type") or "").lower().startswith("missing")]:
                    st = api.player_season(p["player_id"], season) if p.get("player_id") else {}
                    apps = max(st.get("appearances") or 0, 1)
                    involvement = ((st.get("goals") or 0) + 0.7 * (st.get("assists") or 0)) / apps
                    p.update(st)
                    p["involvement_per_game"] = involvement
                    res[side]["missing"].append(p)
                    share += involvement
                # goles por partido de referencia del equipo ≈ 1.35
                res[side]["attack_factor"] = max(0.75, 1 - 0.6 * min(share / 1.35, 0.42))
            ev.result_detail = {**(ev.result_detail or {}), "availability": res}
            done += 1
            if done >= max_fixtures:
                break
        return lg.done(done)
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        return lg.fail(exc)
