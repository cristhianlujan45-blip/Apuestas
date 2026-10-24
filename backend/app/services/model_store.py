"""Entrenamiento, versionado y carga de los motores predictivos.

Flujo de reentrenamiento controlado:
1. Se descarga el histórico real.
2. Se ejecuta validación walk-forward → métricas fuera de muestra.
3. El candidato se registra como ``candidate``.
4. Solo se promueve a ``champion`` si mejora la log loss del campeón vigente
   (o si no hay campeón). Si no mejora, el campeón se mantiene.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import joblib
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import DATA_DIR, get_settings
from ..engine.basketball import BasketballModel, PlayerPropsModel
from ..engine.football.engine import FootballEngine
from ..engine.other_sports import BaseballModel, VolleyballModel
from ..engine.tennis import TennisModel
from ..engine.validation import walk_forward_football
from ..models import Alert, ModelVersion, ValidationRun
from ..providers.football_data_uk import FootballDataUK

log = logging.getLogger(__name__)
MODEL_DIR = DATA_DIR / "models"
IMPORT_DIR = DATA_DIR / "import"
_lock = threading.Lock()
_cache: dict[str, object] = {}


def _json_safe(obj):
    return json.loads(json.dumps(obj, default=lambda o: float(o) if hasattr(o, "__float__") else str(o)))


def football_history(include_colombia: bool = True) -> pd.DataFrame:
    s = get_settings()
    leagues = [x for x in s.football_data_leagues.split(",") if x]
    seasons = [x for x in s.football_data_seasons.split(",") if x]
    extra = [x for x in s.football_data_extra_leagues.split(",") if x]
    df = FootballDataUK().history(leagues, seasons, extra)
    if include_colombia and s.api_football_key:
        try:
            from .ingest import colombia_history

            year = datetime.now().year
            col = colombia_history([year - 2, year - 1, year])
            if not col.empty:
                df = pd.concat([df, col], ignore_index=True).sort_values("date", kind="mergesort")
        except Exception as exc:  # noqa: BLE001
            log.warning("Sin histórico de Colombia: %s", exc)
    return df


def _version_hash(meta: dict) -> str:
    return hashlib.sha256(json.dumps(meta, sort_keys=True, default=str).encode()).hexdigest()[:10]


def train_football(db: Session, validate: bool = True, test_days: int = 365,
                   ml_models: tuple[str, ...] = ("logreg", "lightgbm", "xgboost", "catboost", "random_forest",
                                                  "torch_mlp", "lightgbm_mkt"),
                   history: pd.DataFrame | None = None, promote: str = "auto") -> dict:
    hist = history if history is not None else football_history()
    if hist.empty:
        raise RuntimeError("No se pudo descargar histórico de fútbol")
    now = datetime.now(timezone.utc)
    weights = weights_nm = None
    val = None
    if validate:
        test_from = (now - timedelta(days=test_days)).strftime("%Y-%m-%d")
        val = walk_forward_football(hist, test_from, ml_models=ml_models)
        weights = val.weights or None
        weights_nm = val.ensemble.get("weights_no_market")
    active_ml = [m for m in ml_models if not weights or weights.get(m, 0) > 1e-3
                 or (weights_nm or {}).get(m, 0) > 1e-3] or ["logreg"]
    engine = FootballEngine(ml_models=active_ml, weights=weights, weights_no_market=weights_nm).fit(hist, now)
    meta = {"rows": len(hist), "leagues": sorted(hist["league"].unique().tolist()),
            "from": str(hist["date"].min()), "to": str(hist["date"].max()), "weights": weights,
            "weights_no_market": weights_nm, "ml": active_ml}
    version = f"{now:%Y%m%d%H%M}-{_version_hash(meta)}"
    engine.version = f"football-{version}"
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    path = MODEL_DIR / f"football_{version}.joblib"
    joblib.dump(engine, path)
    metrics = {}
    if val is not None:
        metrics = _json_safe({"champion_component": val.champion, "ensemble": {k: v for k, v in val.ensemble.items()
                                                                               if not k.startswith("calibration")},
                              "per_model": {k: {kk: vv for kk, vv in v.items() if not kk.startswith("calibration")}
                                            for k, v in val.per_model.items()},
                              "totals": {k: v for k, v in val.totals.items() if k != "calibration_over_2_5"},
                              "roi": val.roi})
        db.add(ValidationRun(model_name="football_ensemble", model_version=engine.version, sport="football",
                             scope=",".join(meta["leagues"]), period_from=pd.Timestamp(val.predictions["date"].min()).to_pydatetime(),
                             period_to=pd.Timestamp(val.predictions["date"].max()).to_pydatetime(),
                             n=int(len(val.predictions)), metrics=_json_safe(val.to_dict()), folds=val.folds))
    mv = ModelVersion(name="football_ensemble", sport="football", version=engine.version, params=_json_safe(meta),
                      metrics=metrics, trained_from=pd.Timestamp(hist["date"].min()).to_pydatetime(),
                      trained_to=now, status="candidate", artifact_path=str(path))
    db.add(mv)
    db.flush()
    promoted = _maybe_promote(db, mv, promote)
    db.commit()
    if promoted:
        with _lock:
            _cache["football"] = engine
    return {"version": engine.version, "promoted": promoted, "metrics": metrics, "meta": _json_safe(meta)}


def _score(mv: ModelVersion) -> float | None:
    ens = (mv.metrics or {}).get("ensemble") or {}
    return ens.get("log_loss")


def _maybe_promote(db: Session, mv: ModelVersion, promote: str) -> bool:
    champ = db.scalar(select(ModelVersion).where(ModelVersion.name == mv.name, ModelVersion.status == "champion"))
    if promote == "never":
        return False
    new, old = _score(mv), (_score(champ) if champ else None)
    better = champ is None or promote == "force" or old is None or (new is not None and new <= old + 0.002)
    # Tolerancia de 0.002: los datos más recientes cambian el conjunto de validación
    if better:
        if champ:
            champ.status = "retired"
        mv.status = "champion"
        return True
    db.add(Alert(kind="model_not_promoted", severity="info",
                 message=f"{mv.version} no mejora al campeón ({new:.4f} vs {old:.4f}); se mantiene el campeón",
                 payload={"candidate": mv.version, "champion": champ.version}))
    return False


def champion(db: Session, name: str) -> ModelVersion | None:
    return db.scalar(select(ModelVersion).where(ModelVersion.name == name, ModelVersion.status == "champion"))


def football_engine(db: Session) -> FootballEngine | None:
    with _lock:
        if "football" in _cache:
            return _cache["football"]  # type: ignore[return-value]
    mv = champion(db, "football_ensemble")
    if mv is None or not mv.artifact_path or not Path(mv.artifact_path).exists():
        return None
    eng = joblib.load(mv.artifact_path)
    with _lock:
        _cache["football"] = eng
    return eng


# ---------------------------------------------------------------------------
# Otros deportes: entrenados con histórico importado (CSV) o API-Sports
# ---------------------------------------------------------------------------

SPORT_FILES = {
    "basketball": "basketball_games.csv", "basketball_players": "basketball_players.csv",
    "tennis": "tennis_matches.csv", "baseball": "baseball_games.csv", "volleyball": "volleyball_games.csv",
}


def _read_import(key: str) -> pd.DataFrame | None:
    p = IMPORT_DIR / SPORT_FILES[key]
    if not p.exists():
        return None
    df = pd.read_csv(p)
    df["date"] = pd.to_datetime(df["date"], utc=True)
    return df


def train_other_sports(db: Session) -> dict:
    now = datetime.now(timezone.utc)
    report = {}
    builders = {
        "basketball": lambda df: BasketballModel().fit(df, now),
        "tennis": lambda df: TennisModel().fit(df, now),
        "baseball": lambda df: BaseballModel().fit(df, now),
        "volleyball": lambda df: VolleyballModel().fit(df, now),
    }
    for sport, build in builders.items():
        df = _read_import(sport)
        if df is None or df.empty:
            report[sport] = {"status": "sin datos", "hint": f"Importe {IMPORT_DIR / SPORT_FILES[sport]}"}
            continue
        try:
            model = build(df)
        except ValueError as exc:
            report[sport] = {"status": "error", "error": str(exc)}
            continue
        extra = {}
        if sport == "basketball":
            pdf = _read_import("basketball_players")
            if pdf is not None and not pdf.empty:
                extra["props"] = PlayerPropsModel().fit(pdf, now)
        version = f"{sport}-{now:%Y%m%d%H%M}-{len(df)}"
        path = MODEL_DIR / f"{version}.joblib"
        MODEL_DIR.mkdir(parents=True, exist_ok=True)
        joblib.dump({"model": model, **extra}, path)
        prev = champion(db, f"{sport}_model")
        if prev:
            prev.status = "retired"
        db.add(ModelVersion(name=f"{sport}_model", sport=sport, version=version, params={"rows": len(df)},
                            metrics={}, trained_from=df["date"].min().to_pydatetime(), trained_to=now,
                            status="champion", artifact_path=str(path)))
        with _lock:
            _cache[sport] = {"model": model, **extra, "version": version}
        report[sport] = {"status": "ok", "version": version, "rows": len(df)}
    db.commit()
    return report


def sport_model(db: Session, sport: str) -> dict | None:
    with _lock:
        if sport in _cache:
            return _cache[sport]  # type: ignore[return-value]
    mv = champion(db, f"{sport}_model")
    if mv is None or not mv.artifact_path or not Path(mv.artifact_path).exists():
        return None
    obj = joblib.load(mv.artifact_path)
    obj["version"] = mv.version
    with _lock:
        _cache[sport] = obj
    return obj


def clear_cache() -> None:
    with _lock:
        _cache.clear()
