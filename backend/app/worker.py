"""Procesos programados (servicio independiente del API).

Ejecutar: ``python -m app.worker``
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from .config import get_settings
from .db import init_db, session_scope
from .models import Event, Prediction
from .services import history, ingest, model_store, operators, predictions
from .services.events import aware
from .services.live import notify_live_update

log = logging.getLogger("worker")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def _safe(fn):
    def wrapper(*a, **k):
        try:
            res = fn(*a, **k)
            log.info("%s → %s", fn.__name__, res)
        except Exception:  # noqa: BLE001
            log.exception("Fallo en %s", fn.__name__)
    wrapper.__name__ = fn.__name__
    return wrapper


@_safe
def job_fixtures():
    with session_scope() as db:
        return ingest.ingest_football_data_fixtures(db)


@_safe
def job_prematch_odds():
    with session_scope() as db:
        return ingest.ingest_odds_api_net(db)


@_safe
def job_live():
    with session_scope() as db:
        a = ingest.ingest_api_football(db, days=1)
        b = ingest.ingest_odds_api_net(db, live=True)
    notify_live_update()
    return {"api_football": a, "odds": b}


@_safe
def job_record_predictions():
    """Registra predicciones pre-partido sin duplicar innecesariamente.

    Se registra si no existe una predicción con la versión vigente del modelo,
    si la última tiene más de 12 h, o al entrar en las 3 h previas al inicio.
    """
    now = datetime.now(timezone.utc)
    n = 0
    with session_scope() as db:
        evs = db.scalars(select(Event).where(Event.status == "scheduled", Event.start_time > now,
                                             Event.start_time < now + timedelta(hours=72))
                         .options(joinedload(Event.home), joinedload(Event.away), joinedload(Event.competition))).unique().all()
        for ev in evs:
            last = db.scalars(select(Prediction).where(Prediction.event_id == ev.id, Prediction.kind == "prematch")
                              .order_by(Prediction.created_at.desc())).first()
            em = predictions.model_event(db, ev, n_draws=0)
            if em.outcomes is None:
                continue
            start = aware(ev.start_time)
            need = (last is None or last.model_version != em.model_version
                    or now - aware(last.created_at) > timedelta(hours=12)
                    or (start - now < timedelta(hours=3) and start - aware(last.created_at) >= timedelta(hours=3)))
            if need and predictions.record_prediction(db, em):
                n += 1
    return {"recorded": n}


@_safe
def job_results_and_settle():
    with session_scope() as db:
        r = ingest.update_football_results(db, model_store.football_history(include_colombia=False))
        s = history.settle_parlays(db)
        p = history.performance(db, "football")
    return {"results": r, "settle": s, "n_evaluated": p.get("n")}


@_safe
def job_verify_coljuegos():
    with session_scope() as db:
        return operators.verify_against_coljuegos(db)


@_safe
def job_retrain():
    with session_scope() as db:
        r = model_store.train_football(db)
        o = model_store.train_other_sports(db)
    model_store.clear_cache()
    return {"football": {k: r[k] for k in ("version", "promoted")}, "other": o}


def main() -> None:
    s = get_settings()
    init_db()
    with session_scope() as db:
        operators.sync_operators(db)
        if model_store.champion(db, "football_ensemble") is None:
            log.info("Sin modelo campeón de fútbol: entrenamiento inicial")
    sched = BlockingScheduler(timezone=s.timezone)
    sched.add_job(job_fixtures, "interval", minutes=30, next_run_time=datetime.now())
    sched.add_job(job_prematch_odds, "interval", seconds=s.prematch_poll_seconds)
    sched.add_job(job_live, "interval", seconds=s.live_poll_seconds)
    sched.add_job(job_record_predictions, "interval", minutes=60, next_run_time=datetime.now() + timedelta(minutes=2))
    sched.add_job(job_results_and_settle, CronTrigger(hour="6,14,23", minute=15))
    sched.add_job(job_verify_coljuegos, CronTrigger(day_of_week="mon", hour=7, minute=5))
    sched.add_job(job_retrain, CronTrigger(day_of_week="mon", hour=4, minute=40))
    with session_scope() as db:
        if model_store.champion(db, "football_ensemble") is None:
            sched.add_job(job_retrain, next_run_time=datetime.now())
    log.info("Worker iniciado")
    sched.start()


if __name__ == "__main__":
    main()
