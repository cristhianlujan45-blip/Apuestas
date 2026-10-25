"""Alertas de oportunidades: feed para la app y notificaciones push con ntfy.

ntfy (https://ntfy.sh) es un servicio gratuito de notificaciones: el usuario
instala la app ntfy y se suscribe a un tema privado (secreto NTFY_TOPIC).
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Alert
from .arbitrage import surebets_from_db
from .predictions import build_candidates, value_bets
from .stale_lines import stale_lines

log = logging.getLogger(__name__)
WEB_URL = "https://cristhianlujan45-blip.github.io/Apuestas"


def _id(*parts) -> str:
    return hashlib.sha1("|".join(map(str, parts)).encode()).hexdigest()[:16]


def current_alerts(db: Session, min_ev: float = 0.03) -> list[dict]:
    out = []
    for s in surebets_from_db(db):
        legs = " · ".join(f"{l['selection_label']} {l['odds']:.2f} ({l['operator']})" for l in s["legs"])
        out.append({"id": _id("sb", s["event_id"], s["market"], s["line"], *[(l["operator"], l["odds"]) for l in s["legs"]]),
                    "kind": "surebet", "event_id": s["event_id"], "priority": 5,
                    "title": f"Surebet {s['profit_pct']:.2f} % · {s['event']}", "body": legs, "value": s["profit_pct"]})
    from ..models import AgentBet, Event

    since = datetime.now(timezone.utc) - timedelta(hours=12)
    for b, ev in db.execute(select(AgentBet, Event).join(Event, AgentBet.event_id == Event.id)
                            .where(AgentBet.result.is_(None), AgentBet.created_at >= since)):
        out.append({"id": _id("ag", b.id), "kind": "agent", "event_id": b.event_id, "priority": 4,
                    "title": f"IA recomienda · {ev.label}",
                    "body": f"{b.selection_label} @ {b.odds:.2f} en {b.operator_key} · ventaja {b.edge * 100:+.1f} % "
                            f"(simulado: {b.stake_cop:,.0f} COP de banca virtual)",
                    "value": b.edge * 100})
    for r in stale_lines(db, min_edge=min_ev)[:10]:
        out.append({"id": _id("sl", r["event_id"], r["selection_key"], r["operator"], r["odds"]), "kind": "stale_line",
                    "event_id": r["event_id"], "priority": 4 if r["status"] == "retrasada" else 3,
                    "title": f"Cuota {'retrasada' if r['status'] == 'retrasada' else 'sobre el mercado'} {r['edge'] * 100:+.1f} % · {r['event']}",
                    "body": f"{r['selection']} @ {r['odds']:.2f} en {r['operator_name']}: {r['explanation']}",
                    "value": r["edge"] * 100})
    cands, _, _ = build_candidates(db)
    for v in value_bets([c for c in cands if c.data_sufficient], min_ev)[:15]:
        out.append({"id": _id("ev", v["event_id"], v["selection_key"], v["operator"], v["odds"]), "kind": "value",
                    "event_id": v["event_id"], "priority": 3,
                    "title": f"Valor {v['ev'] * 100:+.1f} % · {v['event']}",
                    "body": f"{v['selection']} @ {v['odds']:.2f} en {v['operator']} (prob. {v['probability']:.0%}, justa {v['fair_odds']:.2f})",
                    "value": v["ev"] * 100})
    return out


def push_ntfy(db: Session, topic: str | None, max_per_run: int = 5) -> dict:
    if not topic:
        return {"skipped": "NTFY_TOPIC no configurado"}
    sent = {a.payload.get("id") for a in db.scalars(select(Alert).where(Alert.kind == "push_sent"))}
    new = [a for a in sorted(current_alerts(db), key=lambda a: (-a["priority"], -a["value"])) if a["id"] not in sent]
    n = 0
    with httpx.Client(timeout=20) as c:
        for a in new[:max_per_run]:
            r = c.post(f"https://ntfy.sh/{topic}", content=a["body"].encode(),
                       headers={"Title": a["title"].encode("utf-8").decode("latin-1", "ignore"),
                                "Priority": str(a["priority"]), "Tags": {"surebet": "moneybag", "stale_line": "hourglass", "agent": "robot"}.get(a["kind"], "chart_with_upwards_trend"),
                                "Click": f"{WEB_URL}/partido/?id={a['event_id']}"})
            if r.status_code < 300:
                db.add(Alert(kind="push_sent", severity="info", message=a["title"], payload={"id": a["id"]}))
                n += 1
    db.commit()
    return {"sent": n, "pending": max(0, len(new) - n)}
