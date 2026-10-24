"""Consulta de cotizaciones, comparador entre operadores y carga manual."""

from __future__ import annotations

import csv
import io
from collections import defaultdict
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..engine.markets import MARKETS, Selection
from ..engine.odds_math import margin_pct
from ..models import Event, OddsQuote, Operator
from ..providers.base import ProviderEvent, ProviderQuote
from .events import add_quotes, aware, upsert_event

BOGOTA = ZoneInfo("America/Bogota")

# Mercados con todas sus selecciones (para calcular margen del operador)
COMPLETE = {"1x2": {"home", "draw", "away"}, "moneyline": {"home", "away"}, "btts": {"yes", "no"},
            "total_goals": {"over", "under"}, "total_points": {"over", "under"}, "dnb": {"home", "away"},
            "asian_handicap": {"home", "away"}, "spread": {"home", "away"}, "total_games": {"over", "under"},
            "total_runs": {"over", "under"}, "corners_total": {"over", "under"}, "cards_total": {"over", "under"}}


def latest_quotes(db: Session, event_ids: list[int] | None = None, operators: list[str] | None = None) -> list[OddsQuote]:
    """Última cotización por (evento, operador, mercado, selección, línea, periodo)."""
    sub = (select(OddsQuote.event_id, OddsQuote.operator_key, OddsQuote.market_key, OddsQuote.selection,
                  OddsQuote.line_key, OddsQuote.period, func.max(OddsQuote.captured_at).label("ts"))
           .group_by(OddsQuote.event_id, OddsQuote.operator_key, OddsQuote.market_key, OddsQuote.selection,
                     OddsQuote.line_key, OddsQuote.period))
    if event_ids is not None:
        sub = sub.where(OddsQuote.event_id.in_(event_ids))
    if operators:
        sub = sub.where(OddsQuote.operator_key.in_(operators))
    sub = sub.subquery()
    q = select(OddsQuote).join(sub, (OddsQuote.event_id == sub.c.event_id) & (OddsQuote.operator_key == sub.c.operator_key)
                               & (OddsQuote.market_key == sub.c.market_key) & (OddsQuote.selection == sub.c.selection)
                               & (OddsQuote.line_key == sub.c.line_key) & (OddsQuote.period == sub.c.period)
                               & (OddsQuote.captured_at == sub.c.ts))
    return list(db.scalars(q))


def quote_selection(q: OddsQuote) -> Selection:
    return Selection(q.market_key, q.selection, q.line, q.player, q.period)


def freshness(q: OddsQuote, now: datetime | None = None) -> dict:
    s = get_settings()
    now = now or datetime.now(timezone.utc)
    ts = aware(q.provider_ts or q.captured_at)
    age = (now - aware(q.captured_at)).total_seconds()
    limit = s.live_odds_stale_after_seconds if q.is_live else s.odds_stale_after_seconds
    return {"captured_at": aware(q.captured_at).isoformat(), "provider_ts": ts.isoformat(), "age_seconds": age,
            "stale": age > limit, "live": q.is_live}


def compare_event(db: Session, event: Event) -> dict:
    ops = {o.key: o for o in db.scalars(select(Operator))}
    quotes = latest_quotes(db, [event.id])
    by_sel: dict[str, list[OddsQuote]] = defaultdict(list)
    for q in quotes:
        if not q.is_available:
            continue
        by_sel[quote_selection(q).key].append(q)
    rows = []
    for key, qs in by_sel.items():
        sel = Selection.from_key(key)
        auth = [q for q in qs if ops.get(q.operator_key) and ops[q.operator_key].status == "authorized"]
        ref = [q for q in qs if ops.get(q.operator_key) and ops[q.operator_key].status == "reference_only"]
        offers = sorted(auth, key=lambda q: q.odds, reverse=True)
        best = offers[0] if offers else None
        worst = offers[-1] if offers else None
        rows.append({
            "selection_key": key, "market": sel.market, "market_label": MARKETS.get(sel.market, {}).get("label", sel.market),
            "selection": sel.selection, "line": sel.line, "player": sel.player,
            "label": sel.describe(event.home.name, event.away.name),
            "best": None if best is None else {"operator": best.operator_key, "odds": best.odds, **freshness(best)},
            "spread_pct": ((best.odds / worst.odds - 1) * 100) if best and worst and len(offers) > 1 else None,
            "offers": [{"operator": q.operator_key, "operator_name": ops[q.operator_key].name, "odds": q.odds,
                        "source": q.source, **freshness(q)} for q in offers],
            "reference": [{"operator": q.operator_key, "odds": q.odds, "source": q.source, **freshness(q)} for q in ref],
            "missing_operators": sorted({q.operator_key for q in quotes if ops.get(q.operator_key)
                                         and ops[q.operator_key].status == "authorized"} - {q.operator_key for q in auth}),
        })
    # Margen de cada operador por mercado completo
    margins = []
    grouped: dict[tuple, dict[str, float]] = defaultdict(dict)
    for q in quotes:
        if q.is_available:
            grouped[(q.operator_key, q.market_key, q.line_key if q.market_key not in ("asian_handicap", "spread") else
                     f"{abs(q.line or 0):g}", q.player or "")][q.selection] = q.odds
    for (op, market, line, player), sels in grouped.items():
        need = COMPLETE.get(market)
        if need and need <= set(sels):
            margins.append({"operator": op, "market": market, "line": line, "player": player or None,
                            "margin_pct": margin_pct([sels[s] for s in need])})
    rows.sort(key=lambda r: (r["market"], r["line"] or 0, r["selection"]))
    return {"event_id": event.id, "rows": rows, "margins": sorted(margins, key=lambda m: m["margin_pct"]),
            "operators_with_quotes": sorted({q.operator_key for q in quotes})}


def odds_history(db: Session, event_id: int, selection_key: str) -> list[dict]:
    sel = Selection.from_key(selection_key)
    line_key = "" if sel.line is None else f"{sel.line:g}"
    q = (select(OddsQuote).where(OddsQuote.event_id == event_id, OddsQuote.market_key == sel.market,
                                 OddsQuote.selection == sel.selection, OddsQuote.line_key == line_key,
                                 OddsQuote.period == sel.period).order_by(OddsQuote.captured_at))
    return [{"operator": r.operator_key, "odds": r.odds, "captured_at": aware(r.captured_at).isoformat(),
             "source": r.source, "available": r.is_available} for r in db.scalars(q)]


def compare_operators(db: Session, a: str, b: str, event_ids: list[int] | None = None) -> dict:
    """Compara dos operadores en todas las selecciones que ambos ofrecen."""
    quotes = latest_quotes(db, event_ids, [a, b])
    by: dict[tuple, dict[str, float]] = defaultdict(dict)
    for q in quotes:
        if q.is_available:
            by[(q.event_id, quote_selection(q).key)][q.operator_key] = q.odds
    common = {k: v for k, v in by.items() if a in v and b in v}
    better_a = sum(1 for v in common.values() if v[a] > v[b])
    better_b = sum(1 for v in common.values() if v[b] > v[a])
    diffs = [v[a] / v[b] - 1 for v in common.values()]
    only_a = sum(1 for v in by.values() if a in v and b not in v)
    only_b = sum(1 for v in by.values() if b in v and a not in v)
    return {"operator_a": a, "operator_b": b, "common_selections": len(common), "a_better": better_a,
            "b_better": better_b, "equal": len(common) - better_a - better_b,
            "avg_pct_difference_a_vs_b": (sum(diffs) / len(diffs) * 100) if diffs else None,
            "only_in_a": only_a, "only_in_b": only_b}


# ---------------------------------------------------------------------------
# Carga manual / CSV (cuando no hay integración autorizada)
# ---------------------------------------------------------------------------

CSV_COLUMNS = ["sport", "competition", "start_time", "home", "away", "operator", "market", "selection",
               "line", "player", "odds", "captured_at"]


def _parse_dt(v: str | None) -> datetime | None:
    if not v:
        return None
    dt = datetime.fromisoformat(v.strip().replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=BOGOTA)  # hora local de Colombia por defecto
    return dt.astimezone(timezone.utc)


def import_manual_quotes(db: Session, rows: list[dict], user_label: str = "manual") -> dict:
    authorized = {o.key for o in db.scalars(select(Operator).where(Operator.status == "authorized"))}
    errors, n = [], 0
    for i, r in enumerate(rows, 1):
        try:
            op = r["operator"].strip().lower()
            if op not in authorized:
                raise ValueError(f"Operador '{op}' no está autorizado por Coljuegos en el registro vigente")
            market = r["market"].strip()
            if market not in MARKETS:
                raise ValueError(f"Mercado desconocido: {market}")
            odds = float(r["odds"])
            if odds <= 1.0:
                raise ValueError("La cuota decimal debe ser > 1.00")
            start = _parse_dt(r["start_time"])
            pe = ProviderEvent(provider="manual", external_id=f"{r['home']}|{r['away']}|{start.isoformat()}",
                               sport=r["sport"].strip(), home=r["home"].strip(), away=r["away"].strip(),
                               start_time=start, competition=(r.get("competition") or None))
            ev = upsert_event(db, pe)
            line = float(r["line"]) if r.get("line") not in (None, "") else None
            q = ProviderQuote("manual", pe.external_id, op, market, r["selection"].strip(), odds, line=line,
                              player=(r.get("player") or None))
            captured = _parse_dt(r.get("captured_at")) or datetime.now(timezone.utc)
            n += add_quotes(db, ev, [q], {}, user_label, captured)
        except (KeyError, ValueError, TypeError) as exc:
            errors.append({"row": i, "error": str(exc)})
    db.commit()
    return {"imported": n, "errors": errors}


def parse_csv(text: str) -> list[dict]:
    return list(csv.DictReader(io.StringIO(text)))
