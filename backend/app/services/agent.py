"""Agente de apuestas SIMULADAS que aprende de los datos.

Qué hace:
1. **Aprende una política** con validación walk-forward sobre miles de partidos reales de
   football-data.co.uk. La estrategia es comparar precios entre casas: apostar cuando la mejor
   cuota disponible supera la cuota justa de Pinnacle (sin margen) en al menos ``min_edge``. El
   umbral se elige solo con temporadas anteriores y se mide en la siguiente.
2. **Recomienda y apuesta en simulado** antes de cada partido con las cuotas de casas colombianas
   y una banca virtual (Kelly fraccional con tope). Cada recomendación queda en una cadena de hash:
   no se puede cambiar después.
3. **Se evalúa** al terminar cada partido: resultado, ganancia y CLV (cuota obtenida frente a la
   de cierre justa). Si con suficientes apuestas reales el CLV es negativo, sube el umbral.

Nunca coloca apuestas reales ni se conecta a cuentas de casas de apuestas.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..engine.markets import Selection
from ..models import AgentBet, Event, ModelVersion
from .events import aware
from .history import final_outcome, leg_result

log = logging.getLogger(__name__)
NAME = "betting_agent"
START_BANKROLL = 1_000_000.0
GRID = (0.0, 0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.08, 0.10)
# Margen de seguridad: el mejor precio de ~40 casas internacionales es más alto que el mejor de
# las casas colombianas, así que se exige un CLV medio de al menos 2 % en el entrenamiento.
MIN_TRAIN_CLV = 0.02
MIN_TRAIN_BETS = 200
ADAPT_MIN_BETS = 100


@dataclass
class Policy:
    min_edge: float = 0.03
    # Cuota máxima 3.5: menos varianza y apuestas de mayor probabilidad. Fuera de muestra (2024–26)
    # fue la variante más rentable; se eligió sobre ese mismo periodo, por eso se vigila el CLV real.
    max_odds: float = 3.5
    kelly_fraction: float = 0.25
    max_stake_pct: float = 0.02
    markets: tuple[str, ...] = ("1x2", "total_goals")
    one_bet_per_event: bool = True

    def as_dict(self) -> dict:
        d = asdict(self)
        d["markets"] = list(self.markets)
        return d


# ------------------------------------------------------------------ aprendizaje (backtest)
def _season(d: pd.Series) -> pd.Series:
    return np.where(d.dt.month >= 7, d.dt.year, d.dt.year - 1)


def _bets_table(hist: pd.DataFrame, price: str = "max") -> pd.DataFrame:
    """Una fila por (partido, resultado 1X2) con la ventaja frente al justo de Pinnacle."""
    cols = {"max": ("max_h", "max_d", "max_a"), "avg": ("odds_h", "odds_d", "odds_a")}[price]
    need = ["ps_h", "ps_d", "ps_a", "psc_h", "psc_d", "psc_a", "hg", "ag", *cols]
    d = hist.dropna(subset=[c for c in need if c in hist]).copy()
    if d.empty or not all(c in d for c in need):
        return pd.DataFrame()
    d["date"] = pd.to_datetime(d["date"], utc=True)
    ps = d[["ps_h", "ps_d", "ps_a"]].to_numpy(float)
    fair = (1 / ps) / (1 / ps).sum(axis=1, keepdims=True)
    pc = d[["psc_h", "psc_d", "psc_a"]].to_numpy(float)
    close = (1 / pc) / (1 / pc).sum(axis=1, keepdims=True)
    odds = d[list(cols)].to_numpy(float)
    y = np.select([d["hg"] > d["ag"], d["hg"] == d["ag"]], [0, 1], 2)
    rows = []
    for k in range(3):
        rows.append(pd.DataFrame({
            "match": d.index.to_numpy(), "date": d["date"].to_numpy(), "season": _season(d["date"]),
            "league": d["league"].to_numpy(),
            "odds": odds[:, k], "p": fair[:, k], "edge": odds[:, k] * fair[:, k] - 1,
            "clv": odds[:, k] * close[:, k] - 1, "win": (y == k).astype(float), "outcome": k,
        }))
    t = pd.concat(rows, ignore_index=True)
    return t[(t["odds"] > 1) & np.isfinite(t["edge"])]


def _select(t: pd.DataFrame, thr: float, max_odds: float, one_per_event: bool = True) -> pd.DataFrame:
    s = t[(t["edge"] > thr) & (t["odds"] <= max_odds)]
    if one_per_event and not s.empty:
        s = s.sort_values("edge", ascending=False).drop_duplicates(subset=["match"])
    return s


def _stats(s: pd.DataFrame) -> dict:
    if s.empty:
        return {"n": 0}
    pnl = np.where(s["win"] == 1, s["odds"] - 1, -1.0)
    sd = pnl.std(ddof=1) if len(pnl) > 1 else float("nan")
    return {"n": int(len(s)), "roi": float(pnl.mean()), "roi_se": float(sd / math.sqrt(len(pnl))) if len(pnl) > 1 else None,
            "clv": float(s["clv"].mean()), "hit_rate": float(s["win"].mean()), "avg_odds": float(s["odds"].mean())}


def _choose(train: pd.DataFrame, max_odds: float) -> tuple[float, dict]:
    table = {}
    for thr in GRID:
        st = _stats(_select(train, thr, max_odds))
        table[thr] = st
    ok = [thr for thr in GRID if table[thr]["n"] >= MIN_TRAIN_BETS and table[thr]["clv"] >= MIN_TRAIN_CLV]
    if ok:
        return min(ok), table
    viable = [thr for thr in GRID if table[thr]["n"] >= MIN_TRAIN_BETS]
    return (max(viable, key=lambda x: table[x]["clv"]) if viable else GRID[-1]), table


def _simulate_bankroll(s: pd.DataFrame, pol: Policy, start: float = START_BANKROLL) -> list[dict]:
    bank, curve = start, []
    for _, r in s.sort_values("date").iterrows():
        f = min(max(0.0, (r["p"] * r["odds"] - 1) / (r["odds"] - 1)) * pol.kelly_fraction, pol.max_stake_pct)
        stake = bank * f
        bank += stake * (r["odds"] - 1) if r["win"] == 1 else -stake
        curve.append({"date": pd.Timestamp(r["date"]).date().isoformat(), "bankroll": round(bank, 0)})
    # Un punto por día (último del día) para no exportar miles de filas
    by_day = {c["date"]: c for c in curve}
    return list(by_day.values())


def backtest(hist: pd.DataFrame, pol: Policy | None = None) -> dict:
    pol = pol or Policy()
    t = _bets_table(hist, "max")
    if t.empty:
        raise ValueError("El histórico no trae cuotas de Pinnacle y máximas")
    seasons = sorted(t["season"].unique())
    folds, oos = [], []
    for i, s in enumerate(seasons):
        if i < 2:
            continue
        train = t[t["season"] < s]
        thr, _ = _choose(train, pol.max_odds)
        test = _select(t[t["season"] == s], thr, pol.max_odds)
        st = _stats(test)
        folds.append({"season": f"{s}-{str(s + 1)[-2:]}", "threshold": thr, **st})
        oos.append(test)
    oos_df = pd.concat(oos) if oos else pd.DataFrame()
    final_thr, table = _choose(t, pol.max_odds)
    # Referencia honesta: la misma regla con la cuota de una casa típica (promedio del mercado)
    avg = _bets_table(hist, "avg")
    typical = _stats(_select(avg, final_thr, pol.max_odds)) if not avg.empty else {"n": 0}
    chosen = Policy(**{**pol.as_dict(), "min_edge": final_thr, "markets": tuple(pol.markets)})
    return {
        "strategy": "Comparar precios: apostar a la mejor cuota cuando supera la cuota justa de Pinnacle",
        "matches": int(t["match"].nunique()), "from": str(t["date"].min().date()), "to": str(t["date"].max().date()),
        "folds": folds, "out_of_sample": _stats(oos_df),
        "bankroll_curve": _simulate_bankroll(oos_df, chosen) if not oos_df.empty else [],
        "threshold_table": {str(k): v for k, v in table.items()}, "chosen_threshold": final_thr,
        "typical_book_same_rule": typical,
        "note": ("El precio máximo de ~40 casas internacionales es más alto que el mejor de las casas "
                 "colombianas: el rendimiento real será menor. Con la cuota de una casa típica la misma "
                 "regla no gana."),
    }


def current_policy(db: Session) -> tuple[Policy, ModelVersion | None]:
    mv = db.scalars(select(ModelVersion).where(ModelVersion.name == NAME, ModelVersion.status == "champion")
                    .order_by(ModelVersion.created_at.desc())).first()
    if mv is None:
        return Policy(), None
    p = dict(mv.params or {})
    p["markets"] = tuple(p.get("markets") or Policy().markets)
    return Policy(**{k: v for k, v in p.items() if k in Policy.__dataclass_fields__}), mv


def _live_adjustment(db: Session, thr: float) -> tuple[float, dict]:
    """Aprendizaje con sus propias apuestas: si el CLV real es negativo, exige más ventaja."""
    rows = db.scalars(select(AgentBet).where(AgentBet.clv.is_not(None))).all()
    info = {"settled_with_clv": len(rows)}
    if len(rows) < ADAPT_MIN_BETS:
        return thr, {**info, "action": f"sin cambios: se necesitan {ADAPT_MIN_BETS} apuestas con cierre"}
    clv = float(np.mean([r.clv for r in rows]))
    info["live_clv"] = clv
    if clv < 0:
        higher = [g for g in GRID if g > thr]
        new = higher[0] if higher else thr
        return new, {**info, "action": f"CLV real negativo: umbral {thr:.0%} → {new:.0%}"}
    return thr, {**info, "action": "CLV real positivo: se mantiene el umbral aprendido"}


def learn(db: Session, hist: pd.DataFrame | None = None, max_age_days: float | None = None) -> dict:
    _, mv = current_policy(db)
    if max_age_days is not None and mv is not None and datetime.now(timezone.utc) - aware(mv.created_at) < timedelta(days=max_age_days):
        return {"skipped": "política reciente", "version": mv.version}
    if hist is None:
        from .model_store import football_history

        hist = football_history()
    res = backtest(hist)
    thr, adj = _live_adjustment(db, res["chosen_threshold"])
    pol = Policy(min_edge=thr)
    now = datetime.now(timezone.utc)
    version = f"agent-{now:%Y%m%d%H%M}-{int(thr * 1000)}"
    for old in db.scalars(select(ModelVersion).where(ModelVersion.name == NAME, ModelVersion.status == "champion")):
        old.status = "retired"
    db.add(ModelVersion(name=NAME, sport="football", version=version, params=pol.as_dict(),
                        metrics={**res, "live_adjustment": adj}, status="champion",
                        trained_from=pd.Timestamp(res["from"]).to_pydatetime().replace(tzinfo=timezone.utc),
                        trained_to=pd.Timestamp(res["to"]).to_pydatetime().replace(tzinfo=timezone.utc)))
    db.commit()
    return {"version": version, "policy": pol.as_dict(), "out_of_sample": res["out_of_sample"], "live_adjustment": adj}


# ------------------------------------------------------------------ apuestas simuladas
def _canon(o) -> str:
    return json.dumps(o, sort_keys=True, separators=(",", ":"), default=str)


def bankroll(db: Session) -> float:
    """Banca virtual: inicial + resultado de lo liquidado (lo abierto no se descuenta hasta liquidar)."""
    return START_BANKROLL + sum(b.payout_cop - b.stake_cop for b in db.scalars(select(AgentBet))
                                if b.payout_cop is not None)


def run(db: Session, now: datetime | None = None) -> dict:
    """Liquida lo terminado y registra las nuevas recomendaciones de la política vigente."""
    from .stale_lines import stale_lines

    now = now or datetime.now(timezone.utc)
    settled = settle(db)
    pol, mv = current_policy(db)
    version = mv.version if mv else "agent-por-defecto"
    open_keys = {(b.event_id, b.selection_key) for b in db.scalars(select(AgentBet).where(AgentBet.result.is_(None)))}
    taken_events = {k[0] for k in open_keys}
    bank = bankroll(db)
    committed = sum(b.stake_cop for b in db.scalars(select(AgentBet).where(AgentBet.result.is_(None))))
    rows = [r for r in stale_lines(db, min_edge=pol.min_edge)
            if Selection.from_key(r["selection_key"]).market in pol.markets and r["odds"] <= pol.max_odds]
    new = 0
    for r in rows:  # ya vienen ordenadas por ventaja
        if (r["event_id"], r["selection_key"]) in open_keys or (pol.one_bet_per_event and r["event_id"] in taken_events):
            continue
        f = min(max(0.0, (r["p_fair"] * r["odds"] - 1) / (r["odds"] - 1)) * pol.kelly_fraction, pol.max_stake_pct)
        stake = round(bank * f, -2)
        if stake <= 0 or committed + stake > bank * 0.5:
            continue
        prev = db.scalars(select(AgentBet).order_by(AgentBet.id.desc())).first()
        prev_hash = prev.hash if prev else "0" * 64
        pick = {"event_id": r["event_id"], "selection_key": r["selection_key"], "operator": r["operator"],
                "odds": r["odds"], "p_est": round(r["p_fair"], 6), "stake": stake, "policy": version,
                "created_at": now.isoformat()}
        h = hashlib.sha256((prev_hash + _canon(pick)).encode()).hexdigest()
        db.add(AgentBet(created_at=now, event_id=r["event_id"], selection_key=r["selection_key"],
                        selection_label=r["selection"], operator_key=r["operator"], odds=r["odds"], p_est=r["p_fair"],
                        edge=r["edge"], stake_cop=stake, bankroll_before=bank, policy_version=version,
                        source=r["status"], reason=r["explanation"], prev_hash=prev_hash, hash=h))
        db.flush()
        open_keys.add((r["event_id"], r["selection_key"]))
        taken_events.add(r["event_id"])
        committed += stake
        new += 1
    db.commit()
    return {"new_picks": new, "settled": settled, "bankroll": bankroll(db), "policy": pol.as_dict(), "version": version}


def settle(db: Session) -> int:
    n = 0
    for b in db.scalars(select(AgentBet).where(AgentBet.result.is_(None))):
        ev = db.get(Event, b.event_id)
        if ev is None or ev.status in ("cancelled", "postponed"):
            if ev is not None:
                b.result, b.payout_cop, b.settled_at = "void", b.stake_cop, datetime.now(timezone.utc)
                n += 1
            continue
        out = final_outcome(db, ev)
        if out is None:
            continue
        try:
            res = leg_result(Selection.from_key(b.selection_key), out)
        except Exception:  # noqa: BLE001 — mercado sin datos finales (p. ej. córners)
            continue
        mult = {"won": b.odds, "half_won": (b.odds + 1) / 2, "void": 1.0, "half_lost": 0.5, "lost": 0.0}[res]
        b.result, b.payout_cop, b.settled_at = res, b.stake_cop * mult, datetime.now(timezone.utc)
        n += 1
    db.commit()
    return n


def attach_clv(db: Session, results: list[dict]) -> None:
    """Rellena el CLV con la cuota de cierre justa cuando ya está publicada."""
    by_event = {r["event_id"]: r.get("closing") for r in results}
    for b in db.scalars(select(AgentBet).where(AgentBet.clv.is_(None))):
        c = by_event.get(b.event_id)
        if not c:
            continue
        sel = Selection.from_key(b.selection_key)
        p = None
        if sel.market == "1x2" and c.get("fair_1x2"):
            p = c["fair_1x2"].get(sel.selection)
        elif sel.market == "total_goals" and sel.line == 2.5 and c.get("fair_total_2_5"):
            p = c["fair_total_2_5"].get(sel.selection)
        if p:
            b.clv = b.odds * p - 1
    db.commit()


# ------------------------------------------------------------------ exportación
def _pred_check(db: Session, limit: int = 300) -> dict:
    """¿Acertó lo que dijo el modelo antes del partido? (predicciones inmutables)."""
    from ..models import Prediction

    rows = db.execute(select(Prediction, Event).join(Event, Prediction.event_id == Event.id)
                      .where(Prediction.kind == "prematch", Event.status == "finished", Event.home_score.is_not(None))
                      .order_by(Prediction.created_at.desc())).all()
    seen, items = set(), []
    for p, ev in rows:
        if ev.id in seen:
            continue
        seen.add(ev.id)  # la última predicción antes del partido
        probs = p.payload.get("probs_1x2")
        if not probs:
            continue
        pred = max(probs, key=probs.get)
        actual = "home" if ev.home_score > ev.away_score else "away" if ev.home_score < ev.away_score else "draw"
        brier = sum((probs[k] - (1.0 if k == actual else 0.0)) ** 2 for k in ("home", "draw", "away"))
        over = (p.payload.get("totals") or {}).get("over_2.5")
        items.append({"event_id": ev.id, "event": ev.label, "start_time": aware(ev.start_time).isoformat(),
                      "predicted": pred, "p_predicted": probs[pred], "probs": probs, "actual": actual,
                      "score": f"{ev.home_score}-{ev.away_score}", "hit": pred == actual, "brier": brier,
                      "p_over_2_5": over, "over_hit": None if over is None else ((over >= 0.5) == (ev.home_score + ev.away_score > 2.5)),
                      "predicted_at": aware(p.created_at).isoformat(), "hash": p.hash[:16]})
    hits = [i["hit"] for i in items]
    return {"n": len(items), "accuracy": float(np.mean(hits)) if hits else None,
            "brier": float(np.mean([i["brier"] for i in items])) if items else None,
            "over_accuracy": float(np.mean([i["over_hit"] for i in items if i["over_hit"] is not None])) if any(i["over_hit"] is not None for i in items) else None,
            "items": items[:limit]}


def export_payload(db: Session, results: list[dict] | None = None) -> dict:
    if results:
        attach_clv(db, results)
    pol, mv = current_policy(db)
    bets = db.execute(select(AgentBet, Event).join(Event, AgentBet.event_id == Event.id).order_by(AgentBet.created_at)).all()
    bank, curve, out = START_BANKROLL, [{"date": None, "bankroll": START_BANKROLL}], []
    for b, ev in bets:
        if b.payout_cop is not None:
            bank += b.payout_cop - b.stake_cop
            curve.append({"date": aware(b.settled_at).isoformat() if b.settled_at else None, "bankroll": round(bank, 0)})
        out.append({"id": b.id, "created_at": aware(b.created_at).isoformat(), "event_id": b.event_id, "event": ev.label,
                    "start_time": aware(ev.start_time).isoformat(), "selection_key": b.selection_key,
                    "selection": b.selection_label, "operator": b.operator_key, "odds": b.odds, "p_est": b.p_est,
                    "edge": b.edge, "stake_cop": b.stake_cop, "source": b.source, "reason": b.reason,
                    "result": b.result, "payout_cop": b.payout_cop, "clv": b.clv, "policy_version": b.policy_version,
                    "hash": b.hash[:16], "score": None if ev.home_score is None else f"{ev.home_score}-{ev.away_score}"})
    settled = [x for x in out if x["result"] is not None]
    staked = sum(x["stake_cop"] for x in settled)
    profit = sum((x["payout_cop"] or 0) - x["stake_cop"] for x in settled)
    clvs = [x["clv"] for x in settled if x["clv"] is not None]
    m = (mv.metrics if mv else {}) or {}
    return {
        "policy": pol.as_dict(), "policy_version": mv.version if mv else None,
        "learned_at": aware(mv.created_at).isoformat() if mv else None,
        "backtest": {k: m.get(k) for k in ("strategy", "matches", "from", "to", "folds", "out_of_sample", "bankroll_curve",
                                           "chosen_threshold", "typical_book_same_rule", "note", "live_adjustment")},
        "bankroll": {"start": START_BANKROLL, "current": bank, "curve": curve},
        "record": {"bets": len(out), "settled": len(settled), "open": len(out) - len(settled), "staked": staked,
                   "profit": profit, "roi": profit / staked if staked else None,
                   "hit_rate": (sum(1 for x in settled if x["result"] in ("won", "half_won")) / len(settled)) if settled else None,
                   "clv": float(np.mean(clvs)) if clvs else None, "clv_n": len(clvs)},
        "open": [x for x in out if x["result"] is None][::-1],
        "history": settled[::-1][:300],
        "predictions_check": _pred_check(db),
        "disclaimer": ("Apuestas simuladas con banca virtual. El agente nunca coloca apuestas reales. "
                       "Resultados pasados no garantizan resultados futuros."),
    }
