"""Detección de arbitraje (surebets) entre operadores colombianos autorizados.

Si para un mercado completo la suma de 1/mejor_cuota de cada selección (cada
una en el operador que mejor paga) es menor que 1, repartir la inversión en
proporción a 1/cuota garantiza el mismo retorno gane quien gane.

Advertencias que se muestran siempre: las casas pueden anular cuotas
erróneas («palpables»), limitar cuentas ganadoras o cambiar la cuota antes de
colocar todas las apuestas.
"""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Operator
from .odds import freshness, latest_quotes

THREE_WAY = {"1x2": ("home", "draw", "away")}
TWO_WAY_SAME_LINE = {
    "total_goals": ("over", "under"), "total_points": ("over", "under"), "total_games": ("over", "under"),
    "total_runs": ("over", "under"), "corners_total": ("over", "under"), "cards_total": ("over", "under"),
    "team_total_home": ("over", "under"), "team_total_away": ("over", "under"), "btts": ("yes", "no"),
    "moneyline": ("home", "away"), "dnb": ("home", "away"), "total_sets": ("over", "under"),
}
OPPOSITE_LINE = {"asian_handicap", "spread", "games_handicap", "set_handicap"}


def find_surebets(quotes: list[dict], stake: float = 100000.0) -> list[dict]:
    """``quotes``: dicts con event_id, event, operator, market, selection, line, player, odds, captured_at, stale."""
    books: dict[tuple, dict[str, dict]] = defaultdict(dict)
    for q in quotes:
        if q.get("stale"):
            continue
        m, sel, line = q["market"], q["selection"], q.get("line")
        if m in THREE_WAY:
            key = (q["event_id"], m, None, q.get("player"))
        elif m in TWO_WAY_SAME_LINE:
            key = (q["event_id"], m, line, q.get("player"))
        elif m in OPPOSITE_LINE and line is not None:
            # Hándicap local L se cubre con visitante −L: se agrupa por la línea del local
            key = (q["event_id"], m, line if sel == "home" else -line, q.get("player"))
        else:
            continue
        cur = books[key].get(sel)
        if cur is None or q["odds"] > cur["odds"]:
            books[key][sel] = q
    out = []
    for key, sels in books.items():
        market = key[1]
        need = THREE_WAY.get(market) or TWO_WAY_SAME_LINE.get(market) or ("home", "away")
        if not all(s in sels for s in need):
            continue
        legs = [sels[s] for s in need]
        inv = sum(1 / leg["odds"] for leg in legs)
        if inv >= 1:
            continue
        profit = 1 / inv - 1
        stakes = [stake * (1 / leg["odds"]) / inv for leg in legs]
        out.append({
            "event_id": key[0], "event": legs[0]["event"], "market": market, "line": legs[0].get("line"),
            "profit_pct": profit * 100, "sum_inverse": inv,
            "legs": [{"selection": leg["selection"], "selection_label": leg.get("selection_label", leg["selection"]),
                      "operator": leg["operator"], "odds": leg["odds"], "stake_cop": round(st),
                      "return_cop": round(st * leg["odds"]), "captured_at": leg["captured_at"]}
                     for leg, st in zip(legs, stakes)],
            "total_stake_cop": stake, "guaranteed_return_cop": round(stake / inv),
            "warning": ("Verifique cada cuota en la casa antes de apostar: las cuotas cambian, las casas pueden "
                        "anular cuotas erróneas y limitar cuentas que hacen arbitraje."),
        })
    return sorted(out, key=lambda x: -x["profit_pct"])


def surebets_from_db(db: Session, stake: float = 100000.0) -> list[dict]:
    authorized = {o.key for o in db.scalars(select(Operator).where(Operator.status == "authorized"))}
    from ..models import Event

    rows = []
    events: dict[int, str] = {}
    for q in latest_quotes(db, None, sorted(authorized)):
        if not q.is_available:
            continue
        if q.event_id not in events:
            ev = db.get(Event, q.event_id)
            events[q.event_id] = ev.label if ev else str(q.event_id)
        rows.append({"event_id": q.event_id, "event": events[q.event_id], "operator": q.operator_key,
                     "market": q.market_key, "selection": q.selection, "line": q.line, "player": q.player,
                     "odds": q.odds, "captured_at": freshness(q)["captured_at"], "stale": freshness(q)["stale"]})
    return find_surebets(rows, stake)
