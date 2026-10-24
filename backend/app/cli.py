"""Línea de comandos: ``python -m app.cli <comando>``"""

from __future__ import annotations

import argparse
import json
import sys

from .db import init_db, session_scope
from .services import history, ingest, model_store, operators


def _print(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2, default=str))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="app.cli")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init", help="Crear tablas y sincronizar operadores")
    sub.add_parser("verify-coljuegos", help="Verificar el registro contra la página oficial")
    sub.add_parser("ingest-fixtures", help="Próximos partidos + cuotas de referencia (football-data)")
    sub.add_parser("ingest-odds", help="Cuotas colombianas (odds-api.net)")
    sub.add_parser("ingest-live", help="Directo (API-Football + odds-api.net)")
    sub.add_parser("ingest-results", help="Resultados finales")
    t = sub.add_parser("train-football", help="Entrenar y validar el ensemble de fútbol")
    t.add_argument("--no-validate", action="store_true")
    t.add_argument("--test-days", type=int, default=365)
    t.add_argument("--fast", action="store_true", help="Solo logreg + lightgbm (más rápido)")
    t.add_argument("--promote", choices=["auto", "force", "never"], default="auto")
    sub.add_parser("train-other", help="Entrenar baloncesto/tenis/béisbol/voleibol con datos importados")
    sub.add_parser("record-predictions", help="Registrar predicciones de los próximos 3 días")
    sub.add_parser("settle", help="Liquidar combinadas")
    sub.add_parser("performance", help="Métricas reales de predicciones liquidadas")
    b = sub.add_parser("backtest", help="Validación walk-forward sin registrar modelo")
    b.add_argument("--from", dest="test_from", required=True)
    b.add_argument("--to", dest="test_to")
    b.add_argument("--leagues", default=None)
    e = sub.add_parser("export-static", help="Exportar JSON estáticos para la app móvil")
    e.add_argument("--out", default="../site/data")
    sub.add_parser("pipeline", help="Ingesta + resultados + predicciones + liquidación (ejecución programada)")
    em = sub.add_parser("ensure-model", help="Entrena si no hay modelo campeón disponible o tiene más de N días")
    em.add_argument("--max-age-days", type=int, default=7)
    x = sub.add_parser("xt", help="Construir xT/xA con StatsBomb Open Data")
    x.add_argument("--competition", type=int, default=43)
    x.add_argument("--season", type=int, default=106)
    x.add_argument("--matches", type=int, default=20)
    a = p.parse_args(argv)

    init_db()
    with session_scope() as db:
        if a.cmd == "init":
            _print({"operators": operators.sync_operators(db)})
        elif a.cmd == "verify-coljuegos":
            _print(operators.verify_against_coljuegos(db))
        elif a.cmd == "ingest-fixtures":
            _print(ingest.ingest_football_data_fixtures(db))
        elif a.cmd == "ingest-odds":
            _print(ingest.ingest_odds_api_net(db))
        elif a.cmd == "ingest-live":
            _print({"api_football": ingest.ingest_api_football(db), "odds": ingest.ingest_odds_api_net(db, live=True)})
        elif a.cmd == "ingest-results":
            _print(ingest.update_football_results(db, model_store.football_history(include_colombia=False)))
        elif a.cmd == "train-football":
            models = ("logreg", "lightgbm", "lightgbm_mkt") if a.fast else (
                "logreg", "lightgbm", "xgboost", "catboost", "random_forest", "torch_mlp", "lightgbm_mkt")
            r = model_store.train_football(db, validate=not a.no_validate, test_days=a.test_days, ml_models=models,
                                           promote=a.promote)
            _print({"version": r["version"], "promoted": r["promoted"],
                    "ensemble": (r["metrics"].get("ensemble") or {}), "champion_component": r["metrics"].get("champion_component")})
        elif a.cmd == "train-other":
            _print(model_store.train_other_sports(db))
        elif a.cmd == "record-predictions":
            from .api.routes import record_upcoming

            _print(record_upcoming(db))
        elif a.cmd == "settle":
            _print(history.settle_parlays(db))
        elif a.cmd == "performance":
            res = history.performance(db)
            _print({k: v for k, v in res.items() if not k.startswith("calibration")})
        elif a.cmd == "backtest":
            from .engine.validation import walk_forward_football

            hist = model_store.football_history(include_colombia=False)
            if a.leagues:
                hist = hist[hist["league"].isin(a.leagues.split(","))]
            r = walk_forward_football(hist, a.test_from, a.test_to)
            out = r.to_dict()
            for v in out["per_model"].values():
                v.pop("calibration_home", None)
                v.pop("calibration_away", None)
            _print(out)
        elif a.cmd == "export-static":
            from pathlib import Path

            from .export_static import export

            _print(export(db, Path(a.out)))
        elif a.cmd == "ensure-model":
            from datetime import datetime, timedelta, timezone
            from pathlib import Path

            from .services.events import aware

            mv = model_store.champion(db, "football_ensemble")
            fresh = (mv is not None and mv.artifact_path and Path(mv.artifact_path).exists()
                     and datetime.now(timezone.utc) - aware(mv.created_at) < timedelta(days=a.max_age_days))
            if fresh:
                _print({"model": mv.version, "trained": False})
            else:
                r = model_store.train_football(db, promote="force" if mv is None or not Path(mv.artifact_path or "").exists() else "auto")
                _print({"model": r["version"], "trained": True, "promoted": r["promoted"]})
        elif a.cmd == "pipeline":
            from .api.routes import record_upcoming

            res = {"fixtures": ingest.ingest_football_data_fixtures(db),
                   "odds_co": ingest.ingest_odds_api_net(db),
                   "api_football": ingest.ingest_api_football(db, days=2)}
            res["results"] = ingest.update_football_results(db, model_store.football_history(include_colombia=False))
            res["predictions"] = record_upcoming(db)
            res["settle"] = history.settle_parlays(db)
            _print(res)
        elif a.cmd == "xt":
            from .engine.football import xt

            res = xt.build_from_open_data(a.competition, a.season, a.matches)
            path = xt.save(res)
            _print({"saved": str(path), "events": res["events"], "top_players": res["players"][:10]})
    return 0


if __name__ == "__main__":
    sys.exit(main())
