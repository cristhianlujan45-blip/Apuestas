"""Validación temporal (walk-forward) y selección de modelos.

Cada predicción fuera de muestra se genera con un modelo ajustado SOLO con
partidos anteriores a la semana evaluada. Así las métricas reflejan el
rendimiento que el sistema habría tenido en tiempo real.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import metrics as M
from .football.engine import group_of
from .football.features import FEATURE_COLUMNS, MARKET_COLUMNS, build_training_table
from .football.goals import BivariatePoissonModel, TeamRatingModel, outcome_probs
from .ml import combine, fit_predict, fit_stacking_weights
from .odds_math import devig
from .ratings import OrderedLogit

log = logging.getLogger(__name__)


@dataclass
class WalkForwardResult:
    predictions: pd.DataFrame
    per_model: dict[str, dict]
    ensemble: dict
    weights: dict[str, float]
    champion: str
    totals: dict
    roi: dict
    folds: list[dict] = field(default_factory=list)
    elapsed_s: float = 0.0

    def to_dict(self) -> dict:
        return {
            "per_model": self.per_model, "ensemble": self.ensemble, "weights": self.weights,
            "champion": self.champion, "totals": self.totals, "roi": self.roi, "folds": self.folds,
            "n": int(len(self.predictions)), "elapsed_s": self.elapsed_s,
        }


def walk_forward_football(history: pd.DataFrame, test_from: str, test_to: str | None = None,
                          ml_models: tuple[str, ...] = ("logreg", "lightgbm", "xgboost", "catboost",
                                                         "random_forest", "torch_mlp", "lightgbm_mkt"),
                          refit_days: int = 7, ml_refit_days: int = 56, bivariate: bool = True,
                          min_edge: float = 0.03) -> WalkForwardResult:
    t0 = time.time()
    hist = history.dropna(subset=["hg", "ag"]).sort_values("date", kind="mergesort").reset_index(drop=True)
    hist["date"] = pd.to_datetime(hist["date"])
    table, _ = build_training_table(hist)
    table["date"] = pd.to_datetime(table["date"])
    hist_naive = hist.assign(date_naive=hist["date"].dt.tz_localize(None), group=hist["league"].map(group_of))
    start = pd.Timestamp(test_from)
    end = pd.Timestamp(test_to) if test_to else table["date"].max() + pd.Timedelta(days=1)
    test_mask = (table["date"] >= start) & (table["date"] < end)
    test_idx = np.where(test_mask)[0]
    if len(test_idx) == 0:
        raise ValueError("No hay partidos en el periodo de validación")

    comp: dict[str, np.ndarray] = {}
    n = len(table)

    def store(name: str, idx: np.ndarray, p: np.ndarray) -> None:
        if name not in comp:
            comp[name] = np.full((n, 3), np.nan)
        comp[name][idx] = p

    exp_total = np.full(n, np.nan)
    p_over25 = np.full(n, np.nan)

    # --- Modelos de goles: reajuste semanal por grupo de ligas ---------------
    week_starts = pd.date_range(start.normalize(), end, freq=f"{refit_days}D")
    folds = []
    biv_cache: dict[str, tuple[pd.Timestamp, BivariatePoissonModel]] = {}
    for ws in week_starts:
        we = ws + pd.Timedelta(days=refit_days)
        wmask = (table["date"] >= ws) & (table["date"] < we) & test_mask
        widx = np.where(wmask)[0]
        if len(widx) == 0:
            continue
        wk = table.iloc[widx]
        for g, grp_rows in wk.groupby(wk["league"].map(group_of)):
            train = hist_naive[(hist_naive["group"] == g) & (hist_naive["date_naive"] < ws)
                               & (hist_naive["date_naive"] >= ws - pd.Timedelta(days=730))]
            if len(train) < 100:
                continue
            ref = ws.to_pydatetime()
            try:
                dc = TeamRatingModel(name="dixon_coles", use_rho=True, compute_cov=False).fit(train, ref)
                po = TeamRatingModel(name="poisson", use_rho=False, compute_cov=False).fit(train, ref)
            except ValueError:
                continue
            bp = None
            if bivariate:
                cached = biv_cache.get(g)
                if cached is None or (ws - cached[0]).days >= 28:
                    try:
                        cached = (ws, BivariatePoissonModel().fit(train, ref))
                        biv_cache[g] = cached
                    except ValueError:
                        cached = None
                bp = cached[1] if cached else None
            rows_idx = grp_rows.index.to_numpy()
            pdc, ppo, pbp = [], [], []
            for i in rows_idx:
                h, a = table.at[i, "home"], table.at[i, "away"]
                m = dc.score_matrix(h, a)
                pdc.append(outcome_probs(m))
                ppo.append(outcome_probs(po.score_matrix(h, a)))
                if bp is not None:
                    pbp.append(outcome_probs(bp.score_matrix(h, a)))
                lam, mu = dc.rates(h, a)
                exp_total[i] = lam + mu
                p_over25[i] = 1 - sum(m[x, y] for x in range(3) for y in range(3 - x))
            store("dixon_coles", rows_idx, np.array(pdc))
            store("poisson", rows_idx, np.array(ppo))
            if pbp:
                store("bivariate_poisson", rows_idx, np.array(pbp))
        folds.append({"week": str(ws.date()), "n": int(len(widx))})

    # --- Ratings + ML: reajuste cada ``ml_refit_days`` ------------------------
    for ms in pd.date_range(start.normalize(), end, freq=f"{ml_refit_days}D"):
        me = ms + pd.Timedelta(days=ml_refit_days)
        midx = np.where((table["date"] >= ms) & (table["date"] < me) & test_mask)[0]
        if len(midx) == 0:
            continue
        train = table[table["date"] < ms]
        if len(train) < 500:
            continue
        te = table.iloc[midx]
        ol = OrderedLogit().fit(train["elo_diff"].to_numpy(), train["result"].to_numpy())
        store("elo", midx, ol.probs(te["elo_diff"].to_numpy()))
        gl = OrderedLogit().fit((train["glicko_exp"].to_numpy() - 0.5) * 1000, train["result"].to_numpy())
        store("glicko2", midx, gl.probs((te["glicko_exp"].to_numpy() - 0.5) * 1000))
        for name in ml_models:
            base = name.removesuffix("_mkt")
            use_mkt = name.endswith("_mkt")
            cols = FEATURE_COLUMNS + (MARKET_COLUMNS if use_mkt else [])
            tr = train.dropna(subset=MARKET_COLUMNS) if use_mkt else train
            if len(tr) < 500:
                continue
            te_rows = te.dropna(subset=MARKET_COLUMNS) if use_mkt else te
            if len(te_rows) == 0:
                continue
            try:
                _, p = fit_predict(base, tr[cols].to_numpy(float), tr["result"].to_numpy(),
                                   te_rows[cols].to_numpy(float))
            except Exception as exc:  # pragma: no cover - dependencias opcionales
                log.warning("Modelo %s falló: %s", name, exc)
                continue
            store(name, te_rows.index.to_numpy(), p)

    # --- Mercado (cuotas de referencia previas, sin margen) -------------------
    mkt = table[MARKET_COLUMNS].to_numpy(float)
    store("market", np.arange(n), mkt)

    y = table["result"].to_numpy()
    per_model: dict[str, dict] = {}
    for name, p in comp.items():
        ok = test_mask.to_numpy() & ~np.isnan(p).any(axis=1)
        if ok.sum() < 50:
            continue
        s = M.multiclass_summary(p[ok], y[ok])
        s["coverage"] = float(ok.sum() / test_mask.sum())
        per_model[name] = s

    # --- Ensembles por apilamiento --------------------------------------------
    # Dos conjuntos de evaluación:
    #  * "sin mercado": modelos propios con cobertura >= 90 %, filas donde todos predicen;
    #  * "con mercado": los anteriores + cuotas de referencia (y modelos *_mkt), solo en
    #    filas que tienen cuotas. Las comparaciones se hacen SIEMPRE sobre el mismo
    #    conjunto de partidos (comparación pareada).
    is_mkt = lambda k: k == "market" or k.endswith("_mkt")  # noqa: E731
    test_arr = test_mask.to_numpy()
    nm_models = [k for k, v in per_model.items() if v["coverage"] >= 0.9 and not is_mkt(k)]
    mk_models = nm_models + [k for k in per_model if is_mkt(k)]

    def rows_with(models: list[str]) -> np.ndarray:
        ok = test_arr.copy()
        for k in models:
            ok &= ~np.isnan(comp[k]).any(axis=1)
        return np.where(ok)[0]

    def stack(models: list[str], idx: np.ndarray) -> tuple[np.ndarray, dict[str, float]]:
        """Predicción fuera de muestra por validación cruzada temporal de 2 bloques + pesos finales."""
        half = len(idx) // 2
        a_idx, b_idx = idx[:half], idx[half:]
        wa = fit_stacking_weights([comp[k][a_idx] for k in models], y[a_idx])
        wb = fit_stacking_weights([comp[k][b_idx] for k in models], y[b_idx])
        out = np.full((n, 3), np.nan)
        out[b_idx] = combine([comp[k][b_idx] for k in models], wa)
        out[a_idx] = combine([comp[k][a_idx] for k in models], wb)
        w_all = fit_stacking_weights([comp[k][idx] for k in models], y[idx])
        return out, {k: float(w) for k, w in zip(models, w_all)}

    ensemble: dict = {}
    weights: dict[str, float] = {}
    nm_idx = rows_with(nm_models) if nm_models else np.array([], int)
    mk_idx = rows_with(mk_models) if len(mk_models) > len(nm_models) else np.array([], int)
    if len(nm_idx) >= 100:
        ens_nm, w_nm = stack(nm_models, nm_idx)
        ens = ens_nm.copy()
        ensemble["weights_no_market"] = w_nm
        if len(mk_idx) >= 100:
            ens_mk, w_mk = stack(mk_models, mk_idx)
            ens[mk_idx] = ens_mk[mk_idx]  # con cuotas de referencia se usa el ensemble con mercado
            weights = w_mk
        else:
            weights = w_nm
        comp["ensemble"] = ens
        ensemble.update(M.multiclass_summary(ens[nm_idx], y[nm_idx]))
        ensemble["method"] = "stacking convexo, validación cruzada temporal de 2 bloques; ensemble con mercado donde hay cuotas"
        ensemble["n_no_market_set"] = int(len(nm_idx))
        ensemble["n_market_set"] = int(len(mk_idx))
        for k in nm_models:
            per_model[k]["common_log_loss"] = M.log_loss(comp[k][nm_idx], y[nm_idx])
        ensemble["common_log_loss"] = ensemble["log_loss"]
        ensemble["no_market_log_loss"] = M.log_loss(ens_nm[nm_idx], y[nm_idx])
        if len(mk_idx) >= 100:
            ensemble["market_subset"] = {
                "n": int(len(mk_idx)),
                "ensemble_log_loss": M.log_loss(ens[mk_idx], y[mk_idx]),
                "ensemble_no_market_log_loss": M.log_loss(ens_nm[mk_idx], y[mk_idx]),
                "models": {k: M.log_loss(comp[k][mk_idx], y[mk_idx]) for k in mk_models},
            }
            for k in mk_models:
                per_model[k]["market_subset_log_loss"] = ensemble["market_subset"]["models"][k]
                if is_mkt(k):
                    per_model[k]["common_log_loss"] = per_model[k]["market_subset_log_loss"]

    # Campeón: comparación pareada en el conjunto con mercado (si existe), si no en el común
    if ensemble.get("market_subset"):
        ranking = {**ensemble["market_subset"]["models"], "ensemble": ensemble["market_subset"]["ensemble_log_loss"]}
        champion_scope = "partidos con cuotas de referencia"
    else:
        ranking = {k: v.get("common_log_loss", v["log_loss"]) for k, v in per_model.items() if not is_mkt(k)}
        if ensemble:
            ranking["ensemble"] = ensemble["log_loss"]
        champion_scope = "conjunto común"
    champion = min(ranking, key=ranking.get)
    ensemble["champion_scope"] = champion_scope
    ensemble["champion_ranking"] = dict(sorted(ranking.items(), key=lambda kv: kv[1]))

    # --- Totales de goles -------------------------------------------------
    tot_ok = test_mask.to_numpy() & ~np.isnan(exp_total)
    actual_total = (table["hg"] + table["ag"]).to_numpy(float)
    over_actual = (actual_total > 2.5).astype(float)
    totals = {
        "n": int(tot_ok.sum()),
        "mae_total_goals": M.mae(exp_total[tot_ok], actual_total[tot_ok]),
        "rmse_total_goals": M.rmse(exp_total[tot_ok], actual_total[tot_ok]),
        "brier_over_2_5": M.brier(p_over25[tot_ok], over_actual[tot_ok]),
        "log_loss_over_2_5": M.log_loss(p_over25[tot_ok], over_actual[tot_ok].astype(int)),
        "calibration_over_2_5": M.calibration_table(p_over25[tot_ok], over_actual[tot_ok]),
    }
    # Mezcla con el mercado de más/menos 2.5 (consenso sin margen): el peso se elige por log loss
    # sobre los partidos del periodo de validación que tienen ambas cuotas.
    if {"o25", "u25"} <= set(hist.columns):
        o = hist["o25"].to_numpy(float)
        u = hist["u25"].to_numpy(float)
        with np.errstate(divide="ignore", invalid="ignore"):
            p_mkt = (1 / o) / (1 / o + 1 / u)
        m_ok = tot_ok & np.isfinite(p_mkt) & (o > 1) & (u > 1)
        if m_ok.sum() >= 200:
            grid = {}
            for w in np.round(np.linspace(0, 1, 11), 2):
                pb = w * p_mkt[m_ok] + (1 - w) * p_over25[m_ok]
                grid[float(w)] = M.log_loss(pb, over_actual[m_ok].astype(int))
            best_w = min(grid, key=grid.get)
            totals["market_blend"] = {
                "n": int(m_ok.sum()), "log_loss_by_market_weight": grid, "market_weight": best_w,
                "brier_model": M.brier(p_over25[m_ok], over_actual[m_ok]),
                "brier_market": M.brier(p_mkt[m_ok], over_actual[m_ok]),
                "brier_blend": M.brier(best_w * p_mkt[m_ok] + (1 - best_w) * p_over25[m_ok], over_actual[m_ok]),
            }

    # --- Rentabilidad simulada (cuotas de referencia internacionales) -------
    roi: dict = {}
    odds_prev = hist[["odds_h", "odds_d", "odds_a"]].to_numpy(float)
    odds_max = hist[["max_h", "max_d", "max_a"]].to_numpy(float)
    closing = hist[["psc_h", "psc_d", "psc_a"]].to_numpy(float)
    # ``table`` y ``hist`` comparten orden (build_training_table ordena por fecha)
    for name in [champion, "dixon_coles", "ensemble"]:
        p = comp.get(name)
        if p is None:
            continue
        ok = test_mask.to_numpy() & ~np.isnan(p).any(axis=1)
        roi[name] = {
            "avg_odds": M.value_bet_roi(p[ok], odds_prev[ok], y[ok], min_edge, closing[ok]),
            "best_odds": M.value_bet_roi(p[ok], odds_max[ok], y[ok], min_edge, closing[ok]),
        }

    pred_df = table.loc[test_mask, ["match_id", "date", "league", "home", "away", "hg", "ag", "result"]].copy()
    for name, p in comp.items():
        pred_df[f"{name}_h"] = p[test_mask.to_numpy(), 0]
        pred_df[f"{name}_d"] = p[test_mask.to_numpy(), 1]
        pred_df[f"{name}_a"] = p[test_mask.to_numpy(), 2]
    pred_df["exp_total"] = exp_total[test_mask.to_numpy()]
    pred_df["p_over25"] = p_over25[test_mask.to_numpy()]

    # Degradación: log loss por partido del campeón en orden temporal
    champ_p = comp.get(champion)
    if champ_p is not None:
        ok = test_mask.to_numpy() & ~np.isnan(champ_p).any(axis=1)
        losses = -np.log(np.clip(champ_p[ok][np.arange(ok.sum()), y[ok]], 1e-12, None))
        roi["degradation"] = M.degradation_check(losses)
        roi["rolling_log_loss"] = M.rolling_metric(losses, 100)[::10]

    return WalkForwardResult(pred_df, per_model, ensemble, weights, champion, totals, roi, folds,
                             elapsed_s=time.time() - t0)


def devig_row(o: tuple[float, float, float]) -> np.ndarray | None:
    if any(x is None or not np.isfinite(x) or x <= 1 for x in o):
        return None
    return devig(list(o))
