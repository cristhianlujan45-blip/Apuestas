"""Exporta el estado de la plataforma a archivos JSON estáticos.

Lo usan la app móvil y la versión web sin servidor: el pipeline programado
(GitHub Actions) ingiere datos, ejecuta los modelos y publica estos archivos;
la app los descarga y calcula en el dispositivo las combinadas, el valor
esperado y el arbitraje (incluidas las cuotas que el usuario introduzca).
"""

from __future__ import annotations

import json
import math
import shutil
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from .api import routes as R
from .config import DATA_DIR
from .models import Event
from .services import predictions as P
from .services.arbitrage import surebets_from_db
from .services.events import event_dict
from .services.odds import freshness, latest_quotes, odds_history, quote_selection
from .services.stale_lines import reference_fair, round_ref, stale_lines

SCHEMA_VERSION = 1


def _clean(obj):
    if isinstance(obj, dict):
        return {str(k): _clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return _clean(obj.tolist())
    if isinstance(obj, (np.floating, float)):
        f = float(obj)
        return None if math.isnan(f) or math.isinf(f) else round(f, 6)
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, datetime):
        return obj.isoformat()
    return obj


def _write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_clean(data), ensure_ascii=False, separators=(",", ":"), allow_nan=False),
                    encoding="utf-8")


def export(db: Session, out: Path) -> dict:
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    now = datetime.now(timezone.utc)

    # Eventos: hoy, directo y próximos (sin duplicados)
    seen: dict[int, dict] = {}
    for scope in ("live", "today", "upcoming"):
        for e in R.list_events(scope=scope, sport=None, with_model=True, limit=400, db=db)["events"]:
            seen.setdefault(e["id"], e)
    events = sorted(seen.values(), key=lambda e: e["start_time"])

    # Detalle por evento (mercados valorados, simulación, matriz, historial)
    evs = {e.id: e for e in db.scalars(select(Event).where(Event.id.in_(list(seen)))
                                        .options(joinedload(Event.home), joinedload(Event.away),
                                                 joinedload(Event.competition))).unique()}
    cache: dict[int, P.EventModel] = {}
    matrices: dict[int, np.ndarray] = {}
    counts: dict[int, dict] = {}
    for eid, ev in evs.items():
        detail = R.get_event(eid, db)
        em = P.model_event(db, ev)
        cache[eid] = em
        if em.outcomes is not None:
            try:
                detail["simulation"] = R.simulate(eid, db)
            except Exception:  # noqa: BLE001
                detail["simulation"] = None
        if em.matrix is not None:
            detail["matrix"] = np.round(em.matrix, 7)
            matrices[eid] = np.round(em.matrix, 7)
        if (detail.get("model") or {}).get("counts"):
            counts[eid] = detail["model"]["counts"]
        hist = {}
        for row in detail.get("markets", []):
            if row.get("offers"):
                h = odds_history(db, eid, row["selection_key"])
                if len(h) > 1:
                    hist[row["selection_key"]] = h[-200:]
        detail["histories"] = hist
        _write(out / "events" / f"{eid}.json", detail)
        seen[eid]["has_matrix"] = em.matrix is not None

    # Candidatos valorados (cuotas de operadores autorizados) y cotizaciones
    cands, _, report = P.build_candidates(db, events=list(evs.values()), include_live=True, cache=cache)
    quotes = []
    for q in latest_quotes(db, list(evs), None):
        if not q.is_available:
            continue
        ev = evs.get(q.event_id)
        sel = quote_selection(q)
        quotes.append({"event_id": q.event_id, "event": ev.label if ev else str(q.event_id),
                       "operator": q.operator_key, "market": q.market_key, "selection": q.selection,
                       "selection_key": sel.key, "selection_label": sel.describe(ev.home.name, ev.away.name) if ev else sel.key,
                       "line": q.line, "player": q.player, "odds": q.odds, "source": q.source, **freshness(q)})

    _write(out / "events.json", {"generated_at": now, "events": events})
    _write(out / "matrices.json", matrices)
    _write(out / "counts.json", counts)
    _write(out / "candidates.json", {"generated_at": now, "candidates": [c.as_dict() for c in cands],
                                     "report": report})
    _write(out / "quotes.json", {"generated_at": now, "quotes": quotes})
    _write(out / "surebets.json", {"generated_at": now, "surebets": surebets_from_db(db)})
    _write(out / "value.json", R.value(min_edge=0.0, db=db))
    _write(out / "operators.json", R.list_operators(db))
    _write(out / "markets.json", R.markets())
    _write(out / "models.json", R.models(db))
    _write(out / "performance.json", R.perf(sport="football", db=db))
    _write(out / "predictions.json", R.list_predictions(limit=300, db=db))
    _write(out / "alerts.json", R.alerts(db))
    _write(out / "responsible.json", R.responsible())
    status = R.status(db)
    status["generated_at"] = now
    status["mode"] = "static"
    _write(out / "status.json", status)

    # Fuerzas por grupo de ligas y xT
    groups = []
    from .services import model_store

    eng = model_store.football_engine(db)
    if eng is not None:
        for g in sorted(eng.dc):
            _write(out / "ratings" / f"{g}.json", R.ratings(group=g, db=db))
            groups.append(g)
    xt_file = DATA_DIR / "models" / "xt_43_106.json"
    if xt_file.exists():
        shutil.copy(xt_file, out / "xt.json")

    # Últimos partidos de los equipos con partidos próximos (fútbol)
    try:
        from .services.assistant import Toolbox

        box = Toolbox(db)
        teams = sorted({n for e in events if e["sport"] == "football" for n in (e["home"], e["away"])})
        recent = {}
        for t in teams:
            r = box.ultimos_partidos(t, 10)
            if "error" not in r:
                recent[t] = r
        _write(out / "teams.json", recent)
    except Exception:  # noqa: BLE001
        _write(out / "teams.json", {})

    # Feed de alertas (la app notifica las nuevas) y resultados con cuota de cierre (CLV)
    from .services.alerts import current_alerts

    ref = reference_fair(db, list(evs))
    _write(out / "reference_fair.json", round_ref(ref))
    _write(out / "stale_lines.json", {"generated_at": now, "lines": stale_lines(db, ref=ref)})
    _write(out / "alerts_feed.json", {"generated_at": now, "alerts": current_alerts(db)})
    results = _results_with_closing(db)
    _write(out / "results.json", {"generated_at": now, "results": results})
    from .services import agent

    _write(out / "agent.json", {"generated_at": now, **agent.export_payload(db, results)})

    manifest = {"schema": SCHEMA_VERSION, "generated_at": now, "events": len(events), "candidates": len(cands),
                "quotes": len(quotes), "rating_groups": groups}
    _write(out / "manifest.json", manifest)
    return manifest


def _results_with_closing(db: Session, days: int = 60) -> list[dict]:
    """Partidos terminados con marcador y cuota de cierre de referencia (Pinnacle si existe).

    Permite liquidar en el dispositivo las apuestas registradas y medir el CLV
    (closing line value): si se apostó a mejor cuota que la de cierre justa.
    """
    from datetime import timedelta

    import pandas as pd

    from .engine.odds_math import devig
    from .services import model_store

    since = datetime.now(timezone.utc) - timedelta(days=days)
    evs = db.scalars(select(Event).where(Event.status == "finished", Event.start_time >= since)
                     .options(joinedload(Event.home), joinedload(Event.away))).unique().all()
    if not evs:
        return []
    try:
        hist = model_store.football_history(include_colombia=False)
        by_id = {r["match_id"]: r for r in hist.to_dict("records")}
    except Exception:  # noqa: BLE001
        by_id = {}
    out = []
    for ev in evs:
        row = by_id.get((ev.external_ids or {}).get("football_data_uk"))
        closing = None
        if row is not None:
            for src, cols in (("pinnacle_cierre", ("psc_h", "psc_d", "psc_a")), ("promedio_cierre", ("close_h", "close_d", "close_a"))):
                o = [row.get(c) for c in cols]
                if all(x is not None and not pd.isna(x) and x > 1 for x in o):
                    fair = devig(o, "power")
                    closing = {"source": src, "1x2": {"home": o[0], "draw": o[1], "away": o[2]},
                               "fair_1x2": {"home": fair[0], "draw": fair[1], "away": fair[2]}}
                    break
            ou = [row.get("close_o25"), row.get("close_u25")]
            if closing is not None and all(x is not None and not pd.isna(x) and x > 1 for x in ou):
                f = devig(ou, "power")
                closing["total_2_5"] = {"over": ou[0], "under": ou[1]}
                closing["fair_total_2_5"] = {"over": f[0], "under": f[1]}
        out.append({"event_id": ev.id, "event": ev.label, "home": ev.home.name, "away": ev.away.name,
                    "start_time": ev.start_time, "home_score": ev.home_score, "away_score": ev.away_score,
                    "closing": closing})
    return out
