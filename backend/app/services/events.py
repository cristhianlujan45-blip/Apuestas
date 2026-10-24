"""Alta/actualización de eventos, participantes y cotizaciones con emparejamiento entre proveedores."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, select
from sqlalchemy.orm import Session, joinedload

from ..models import Competition, Event, EventStats, OddsQuote, Participant
from ..names import best_match, canonical, normalize
from ..providers.base import ProviderEvent, ProviderQuote


def get_or_create_participant(db: Session, sport: str, name: str) -> Participant:
    canon = canonical(name)
    norm = normalize(canon)
    p = db.scalar(select(Participant).where(Participant.sport == sport, Participant.normalized_name == norm))
    if p is None:
        p = Participant(sport=sport, name=canon, normalized_name=norm, aliases=[name] if name != canon else [])
        db.add(p)
        db.flush()
    elif name != p.name and name not in (p.aliases or []):
        p.aliases = [*(p.aliases or []), name]
    return p


def get_or_create_competition(db: Session, sport: str, name: str | None, country: str | None,
                              code: str | None = None) -> Competition | None:
    if not name:
        return None
    c = db.scalar(select(Competition).where(Competition.sport == sport, Competition.name == name,
                                            Competition.country == country))
    if c is None:
        c = Competition(sport=sport, name=name, country=country, external_ids={"code": code} if code else {})
        db.add(c)
        db.flush()
    elif code and (c.external_ids or {}).get("code") != code:
        c.external_ids = {**(c.external_ids or {}), "code": code}
    return c


def find_matching_event(db: Session, pe: ProviderEvent, window_hours: float = 3.0) -> Event | None:
    """Busca un evento existente por proveedor o por nombres + hora (±window)."""
    for ev in db.scalars(select(Event).where(Event.sport == pe.sport)
                         .where(Event.start_time.between(pe.start_time - timedelta(hours=window_hours),
                                                         pe.start_time + timedelta(hours=window_hours)))
                         .options(joinedload(Event.home), joinedload(Event.away))):
        if (ev.external_ids or {}).get(pe.provider) == pe.external_id:
            return ev
    best, best_score = None, 0.0
    for ev in db.scalars(select(Event).where(Event.sport == pe.sport)
                         .where(Event.start_time.between(pe.start_time - timedelta(hours=window_hours),
                                                         pe.start_time + timedelta(hours=window_hours)))
                         .options(joinedload(Event.home), joinedload(Event.away))):
        names_h = [ev.home.name, *(ev.home.aliases or [])]
        names_a = [ev.away.name, *(ev.away.aliases or [])]
        _, sh = best_match(pe.home, names_h, 0.0)
        _, sa = best_match(pe.away, names_a, 0.0)
        score = min(sh, sa)
        if score > best_score:
            best, best_score = ev, score
    return best if best_score >= 0.75 else None


def upsert_event(db: Session, pe: ProviderEvent, competition_code: str | None = None) -> Event:
    ev = find_matching_event(db, pe)
    if ev is None:
        home = get_or_create_participant(db, pe.sport, pe.home)
        away = get_or_create_participant(db, pe.sport, pe.away)
        comp = get_or_create_competition(db, pe.sport, pe.competition, pe.country, competition_code)
        ev = db.scalar(select(Event).where(and_(Event.sport == pe.sport, Event.home_id == home.id,
                                                Event.away_id == away.id, Event.start_time == pe.start_time)))
        if ev is None:
            ev = Event(sport=pe.sport, home_id=home.id, away_id=away.id, start_time=pe.start_time,
                       competition_id=comp.id if comp else None, status=pe.status, external_ids={})
            db.add(ev)
            db.flush()
    else:
        # Registrar alias del proveedor para futuros emparejamientos
        for part, name in ((ev.home, pe.home), (ev.away, pe.away)):
            if name != part.name and name not in (part.aliases or []):
                part.aliases = [*(part.aliases or []), name]
    ev.external_ids = {**(ev.external_ids or {}), pe.provider: pe.external_id}
    if competition_code and ev.competition is not None and not (ev.competition.external_ids or {}).get("code"):
        ev.competition.external_ids = {**(ev.competition.external_ids or {}), "code": competition_code}
    if pe.status in ("live", "finished", "postponed", "cancelled") or ev.status == "scheduled":
        ev.status = pe.status
    if pe.home_score is not None:
        ev.home_score, ev.away_score = pe.home_score, pe.away_score
    if pe.minute is not None:
        ev.minute = pe.minute
    if pe.extra:
        ev.result_detail = {**(ev.result_detail or {}), **{k: v for k, v in pe.extra.items() if v is not None}}
    return ev


def add_quotes(db: Session, event: Event, quotes: list[ProviderQuote], operator_map: dict[str, str],
               source: str, captured_at: datetime | None = None) -> int:
    captured_at = captured_at or datetime.now(timezone.utc)
    n = 0
    for q in quotes:
        op = operator_map.get(q.operator_key, q.operator_key)
        db.merge(OddsQuote(
            event_id=event.id, operator_key=op, market_key=q.market, selection=q.selection,
            line_key="" if q.line is None else f"{q.line:g}", period=q.period, captured_at=captured_at,
            line=q.line, odds=q.odds, is_available=q.available, is_live=q.is_live, player=q.player,
            source=source, provider_ts=q.provider_ts,
        ))
        n += 1
    return n


def add_stats(db: Session, event: Event, provider: str, stats: dict, minute: int | None, final: bool) -> None:
    db.add(EventStats(event_id=event.id, provider=provider, stats=stats, minute=minute, is_final=final))


def event_dict(ev: Event) -> dict:
    return {
        "id": ev.id, "sport": ev.sport, "home": ev.home.name, "away": ev.away.name, "label": ev.label,
        "start_time": ev.start_time.replace(tzinfo=ev.start_time.tzinfo or timezone.utc).isoformat(),
        "status": ev.status, "home_score": ev.home_score, "away_score": ev.away_score, "minute": ev.minute,
        "competition": ev.competition.name if ev.competition else None,
        "country": ev.competition.country if ev.competition else None,
        "competition_code": (ev.competition.external_ids or {}).get("code") if ev.competition else None,
        "external_ids": ev.external_ids, "surface": ev.surface,
    }


def aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
