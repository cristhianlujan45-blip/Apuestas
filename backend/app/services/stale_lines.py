"""Cuotas retrasadas: casas colombianas que pagan más que el precio justo del mercado de referencia.

Pinnacle (y en su defecto el consenso internacional) mueve sus líneas en cuanto entra dinero
informado. Las casas locales suelen tardar en ajustarse. Cuando la cuota colombiana supera la
cuota justa de la referencia —y sobre todo cuando la referencia se movió *después* del último
cambio de la casa— esa cuota está retrasada: el valor esperado se calcula contra el mercado,
no contra un modelo propio.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..engine.odds_math import devig
from ..models import Event, OddsQuote, Operator
from .events import aware
from .odds import freshness, latest_quotes, quote_selection

REF_ORDER = ("pinnacle", "intl_consensus")
GROUPS = {"1x2": ("home", "draw", "away"), "total_goals": ("over", "under"), "btts": ("yes", "no"),
          "asian_handicap": ("home", "away"), "dnb": ("home", "away")}
MOVE_PP = 0.02  # movimiento mínimo de la referencia (puntos de probabilidad) para hablar de «retraso»


def _group_line(market: str, selection: str, line: float | None) -> float | None:
    if line is None:
        return None
    # En hándicap el local L se enfrenta al visitante −L
    return line if market != "asian_handicap" or selection == "home" else -line


def reference_fair(db: Session, event_ids: list[int] | None = None, hours: int = 48,
                   now: datetime | None = None) -> dict[int, dict[str, dict]]:
    """Probabilidad justa (sin margen) por evento y selección, con el movimiento reciente de la referencia."""
    now = now or datetime.now(timezone.utc)
    latest = [q for q in latest_quotes(db, event_ids, list(REF_ORDER)) if q.is_available]
    books: dict[tuple, dict[str, dict[str, OddsQuote]]] = defaultdict(lambda: defaultdict(dict))
    for q in latest:
        if q.market_key not in GROUPS or q.period != "ft" or q.player:
            continue
        books[(q.event_id, q.market_key, _group_line(q.market_key, q.selection, q.line))][q.operator_key][q.selection] = q

    # Historial de la referencia en la ventana (una sola consulta)
    hist: dict[tuple, list[tuple[datetime, float]]] = defaultdict(list)
    stmt = (select(OddsQuote).where(OddsQuote.operator_key.in_(REF_ORDER),
                                    OddsQuote.captured_at >= now - timedelta(hours=hours))
            .order_by(OddsQuote.captured_at))
    if event_ids is not None:
        stmt = stmt.where(OddsQuote.event_id.in_(event_ids))
    for r in db.scalars(stmt):
        hist[(r.event_id, r.operator_key, quote_selection(r).key)].append((aware(r.provider_ts or r.captured_at), r.odds))

    out: dict[int, dict[str, dict]] = defaultdict(dict)
    for (eid, market, _), by_op in books.items():
        need = GROUPS[market]
        op = next((o for o in REF_ORDER if all(s in by_op.get(o, {}) for s in need)), None)
        if op is None:
            continue
        qs = [by_op[op][s] for s in need]
        try:
            fair = devig([q.odds for q in qs], "power")
        except ValueError:
            continue
        for q, p in zip(qs, fair):
            key = quote_selection(q).key
            h = hist.get((eid, op, key), [])
            first = h[0][1] if h else q.odds
            changed_at = None
            for (t0, o0), (t1, o1) in zip(h, h[1:]):
                if abs(o1 - o0) > 1e-9:
                    changed_at = t1
            out[eid][key] = {
                "p_fair": float(p), "ref_operator": op, "ref_odds": q.odds, "ref_first_odds": first,
                "ref_moved_pp": float(1 / q.odds - 1 / first), "ref_changed_at": changed_at.isoformat() if changed_at else None,
                "ref_captured_at": aware(q.captured_at).isoformat(),
            }
    return dict(out)


def stale_lines(db: Session, min_edge: float = 0.02, ref: dict | None = None) -> list[dict]:
    authorized = {o.key: o.name for o in db.scalars(select(Operator).where(Operator.status == "authorized"))}
    co = [q for q in latest_quotes(db, None, sorted(authorized)) if q.is_available]
    eids = sorted({q.event_id for q in co})
    if not eids:
        return []
    ref = ref if ref is not None else reference_fair(db, eids)
    events = {e.id: e for e in db.scalars(select(Event).where(Event.id.in_(eids)))}
    rows = []
    for q in co:
        sel = quote_selection(q)
        r = ref.get(q.event_id, {}).get(sel.key)
        ev = events.get(q.event_id)
        if not r or ev is None or ev.status != "scheduled":
            continue
        f = freshness(q)
        if f["stale"]:
            continue
        edge = q.odds * r["p_fair"] - 1
        if edge < min_edge:
            continue
        rows.append(classify({
            "event_id": q.event_id, "event": ev.label, "start_time": aware(ev.start_time).isoformat(),
            "selection_key": sel.key, "selection": sel.describe(ev.home.name, ev.away.name),
            "operator": q.operator_key, "operator_name": authorized[q.operator_key], "odds": q.odds,
            "fair_odds": 1 / r["p_fair"], "edge": edge, "co_changed_at": f["provider_ts"], "captured_at": f["captured_at"], **r,
        }))
    return sorted(rows, key=lambda x: -x["edge"])


def classify(row: dict) -> dict:
    """«retrasada» si la referencia subió la probabilidad de esta selección después del último cambio de la casa."""
    moved = row["ref_moved_pp"] >= MOVE_PP
    later = row.get("ref_changed_at") and row.get("co_changed_at") and row["ref_changed_at"] > row["co_changed_at"]
    row["status"] = "retrasada" if moved and later else "sobre_mercado"
    row["explanation"] = (
        f"{row['ref_operator']} pasó de {row['ref_first_odds']:.2f} a {row['ref_odds']:.2f} y "
        f"{row['operator']} sigue pagando {row['odds']:.2f}" if row["status"] == "retrasada" else
        f"{row['operator']} paga {row['odds']:.2f} y la cuota justa del mercado es {row['fair_odds']:.2f}")
    return row


def round_ref(ref: dict) -> dict:
    return {eid: {k: {kk: (round(vv, 6) if isinstance(vv, float) else vv) for kk, vv in v.items()} for k, v in sels.items()}
            for eid, sels in ref.items()}

