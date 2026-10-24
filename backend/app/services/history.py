"""Historial, liquidación y aprendizaje: compara predicciones con resultados reales.

Las predicciones nunca se modifican. Los resultados se leen de la tabla de
eventos; las métricas se recalculan siempre desde cero.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from ..engine import metrics as M
from ..engine.markets import Outcomes, Selection, UnsupportedMarket, grade
from ..models import Alert, Event, EventStats, ModelVersion, Parlay, Prediction, ValidationRun
from .events import aware

FINAL_STAT_MAP = {"hc": "corners_home", "ac": "corners_away", "hs": "shots_home", "as": "shots_away",
                  "hst": "sot_home", "ast": "sot_away", "home_corners": "corners_home", "away_corners": "corners_away",
                  "home_shots": "shots_home", "away_shots": "shots_away", "home_sot": "sot_home", "away_sot": "sot_away"}


def final_outcome(db: Session, ev: Event) -> Outcomes | None:
    if ev.status != "finished" or ev.home_score is None:
        return None
    vals = {"home": np.array([ev.home_score]), "away": np.array([ev.away_score])}
    st = db.scalars(select(EventStats).where(EventStats.event_id == ev.id, EventStats.is_final.is_(True))
                    .order_by(EventStats.captured_at.desc())).first()
    if st:
        s = st.stats
        for k, target in FINAL_STAT_MAP.items():
            if s.get(k) is not None:
                vals[target] = np.array([s[k]])
        y = (s.get("hy") or 0) + (s.get("hr") or 0) if s.get("hy") is not None else None
        ya = (s.get("ay") or 0) + (s.get("ar") or 0) if s.get("ay") is not None else None
        if y is not None and ya is not None:
            vals["cards_home"], vals["cards_away"] = np.array([y]), np.array([ya])
    detail = ev.result_detail or {}
    for k in ("home_sets", "away_sets", "home_games", "away_games", "home_points", "away_points"):
        if k in detail:
            vals[k] = np.array([detail[k]])
    return Outcomes(ev.sport, vals, np.ones(1), exact=True)


def leg_result(sel: Selection, out: Outcomes) -> str:
    a, b = grade(sel, out)
    a, b = float(a[0]), float(b[0])
    if a == 1:
        return "won"
    if a == 0.5:
        return "half_won"
    if b == 1:
        return "void"
    if b == 0.5:
        return "half_lost"
    return "lost"


def settle_parlays(db: Session) -> dict:
    n = 0
    for p in db.scalars(select(Parlay).where(Parlay.status == "open")):
        results = []
        pending = False
        for leg in p.legs:
            comps = leg.get("components") or [leg]
            for c in comps:
                ev = db.get(Event, c["event_id"])
                out = final_outcome(db, ev) if ev else None
                if out is None:
                    pending = True
                    break
                try:
                    results.append(leg_result(Selection.from_key(c["selection_key"]), out))
                except UnsupportedMarket:
                    results.append("unknown")
            if pending:
                break
        if pending:
            continue
        if "unknown" in results:
            continue
        if any(r == "lost" for r in results):
            p.status = "lost"
        elif all(r == "void" for r in results):
            p.status = "void"
        elif any(r in ("void", "half_won", "half_lost") for r in results):
            p.status = "partial_void" if "half_lost" not in results else "won_partial"
        else:
            p.status = "won"
        p.settled_at = datetime.now(timezone.utc)
        n += 1
    db.commit()
    return {"settled": n}


def _latest_prematch(db: Session, sport: str | None = None) -> list[tuple[Prediction, Event]]:
    q = (select(Prediction, Event).join(Event, Prediction.event_id == Event.id)
         .where(Prediction.kind == "prematch", Event.status == "finished"))
    if sport:
        q = q.where(Event.sport == sport)
    rows = db.execute(q.order_by(Prediction.created_at)).all()
    latest: dict[int, tuple[Prediction, Event]] = {}
    for p, ev in rows:
        # Solo cuentan predicciones emitidas ANTES del inicio del evento
        if aware(p.created_at) < aware(ev.start_time):
            latest[ev.id] = (p, ev)
    return sorted(latest.values(), key=lambda pe: pe[1].start_time)


def performance(db: Session, sport: str = "football") -> dict:
    pairs = _latest_prematch(db, sport)
    probs, ys, exp_tot, act_tot, by_model = [], [], [], [], defaultdict(list)
    roi_rows = []
    for p, ev in pairs:
        pl = p.payload
        pr = pl.get("probs_1x2") or pl.get("probs_moneyline")
        if not pr:
            continue
        if "draw" in pr:
            vec = [pr["home"], pr["draw"], pr["away"]]
            y = 0 if ev.home_score > ev.away_score else (1 if ev.home_score == ev.away_score else 2)
        else:
            vec = [pr["home"], 0.0, pr["away"]]
            y = 0 if ev.home_score > ev.away_score else 2
        probs.append(vec)
        ys.append(y)
        by_model[p.model_version].append((vec, y))
        eg = (pl.get("summary") or {}).get("expected_goals")
        if eg and eg.get("home") is not None:
            exp_tot.append(eg["home"] + eg["away"])
            act_tot.append(ev.home_score + ev.away_score)
        snap = pl.get("market_snapshot") or {}
        for sel, info in snap.items():
            if info and info.get("ev", -1) >= 0.02:
                won = {"home": y == 0, "draw": y == 1, "away": y == 2}[sel]
                roi_rows.append((info["odds"], won, info.get("operator")))
    if not probs:
        return {"n": 0, "message": "Aún no hay predicciones pre-partido liquidadas. Las métricas aparecerán cuando "
                                    "los eventos predichos terminen."}
    P, Y = np.array(probs), np.array(ys)
    out = {"n": len(Y), **M.multiclass_summary(P, Y)}
    if exp_tot:
        out["mae_total_goals"] = M.mae(exp_tot, act_tot)
        out["rmse_total_goals"] = M.rmse(exp_tot, act_tot)
    if roi_rows:
        profit = sum((o - 1) if w else -1 for o, w, _ in roi_rows)
        out["value_bets"] = {"bets": len(roi_rows), "profit_units": profit, "roi": profit / len(roi_rows),
                             "hit_rate": sum(w for _, w, _ in roi_rows) / len(roi_rows)}
    losses = -np.log(np.clip(P[np.arange(len(Y)), Y], 1e-12, None))
    out["rolling_log_loss"] = M.rolling_metric(losses, min(50, max(10, len(Y) // 4)))
    out["by_version"] = {v: {"n": len(rows), "log_loss": M.log_loss(np.array([r[0] for r in rows]),
                                                                    np.array([r[1] for r in rows]))}
                         for v, rows in by_model.items()}
    out["degradation"] = check_degradation(db, losses)
    return out


def check_degradation(db: Session, losses: np.ndarray) -> dict:
    """Compara la log loss real reciente con la esperada según la validación."""
    champ = db.scalar(select(ModelVersion).where(ModelVersion.name == "football_ensemble",
                                                 ModelVersion.status == "champion"))
    expected = ((champ.metrics or {}).get("ensemble") or {}).get("log_loss") if champ else None
    res = {"expected_log_loss": expected, "n": int(len(losses))}
    if expected is None or len(losses) < 60:
        res["status"] = "insuficiente"
        return res
    recent = losses[-60:]
    se = losses.std(ddof=1) / np.sqrt(len(recent))
    z = float((recent.mean() - expected) / se) if se > 0 else 0.0
    res.update({"recent_log_loss": float(recent.mean()), "z": z, "status": "alerta" if z > 3 else "ok"})
    if z > 3:
        recent_alert = db.scalars(select(Alert).where(Alert.kind == "model_degradation",
                                                      Alert.created_at > datetime.now(timezone.utc) - timedelta(days=1))).first()
        if not recent_alert:
            db.add(Alert(kind="model_degradation", severity="warning",
                         message=f"Log loss reciente {recent.mean():.3f} supera la esperada {expected:.3f} (z={z:.1f})",
                         payload=res))
            db.commit()
    return res


def parlay_history(db: Session, user_id: int | None = None, limit: int = 100) -> dict:
    q = select(Parlay).order_by(Parlay.created_at.desc()).limit(limit)
    if user_id is not None:
        q = q.where(Parlay.user_id == user_id)
    rows = list(db.scalars(q))
    settled = [p for p in rows if p.status in ("won", "lost")]
    stats = {}
    if settled:
        won = [p for p in settled if p.status == "won"]
        profit = sum(p.total_odds - 1 for p in won) - (len(settled) - len(won))
        stats = {"settled": len(settled), "won": len(won), "hit_rate": len(won) / len(settled),
                 "expected_hits": float(sum(p.joint_probability for p in settled)),
                 "roi_flat": profit / len(settled)}
    return {"parlays": [{"id": p.id, "created_at": aware(p.created_at).isoformat(), "label": p.label, "mode": p.mode,
                         "operator": p.operator_key, "total_odds": p.total_odds,
                         "joint_probability": p.joint_probability, "ev": p.expected_value, "status": p.status,
                         "legs": p.legs, "settled_at": aware(p.settled_at).isoformat() if p.settled_at else None}
                        for p in rows], "stats": stats}


def validation_runs(db: Session, limit: int = 20) -> list[dict]:
    rows = db.scalars(select(ValidationRun).order_by(ValidationRun.created_at.desc()).limit(limit))
    return [{"id": r.id, "model": r.model_name, "version": r.model_version, "sport": r.sport, "scope": r.scope,
             "from": aware(r.period_from).isoformat() if r.period_from else None,
             "to": aware(r.period_to).isoformat() if r.period_to else None, "n": r.n, "metrics": r.metrics,
             "created_at": aware(r.created_at).isoformat()} for r in rows]


def model_versions(db: Session) -> list[dict]:
    rows = db.scalars(select(ModelVersion).order_by(ModelVersion.created_at.desc()))
    return [{"id": m.id, "name": m.name, "sport": m.sport, "version": m.version, "status": m.status,
             "metrics": m.metrics, "params": m.params, "created_at": aware(m.created_at).isoformat(),
             "trained_to": aware(m.trained_to).isoformat() if m.trained_to else None} for m in rows]


def prediction_log(db: Session, limit: int = 200) -> list[dict]:
    rows = db.execute(select(Prediction, Event).join(Event, Prediction.event_id == Event.id)
                      .options(joinedload(Event.home), joinedload(Event.away))
                      .order_by(Prediction.created_at.desc()).limit(limit)).unique().all()
    out = []
    for p, ev in rows:
        out.append({"id": p.id, "event_id": ev.id, "event": ev.label, "sport": ev.sport,
                    "start_time": aware(ev.start_time).isoformat(), "created_at": aware(p.created_at).isoformat(),
                    "kind": p.kind, "model_version": p.model_version, "probs": p.payload.get("probs_1x2")
                    or p.payload.get("probs_moneyline"), "status": ev.status, "score": None if ev.home_score is None
                    else f"{ev.home_score}-{ev.away_score}", "hash": p.hash[:16]})
    return out
