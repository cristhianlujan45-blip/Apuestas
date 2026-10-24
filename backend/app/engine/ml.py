"""Clasificadores supervisados para resultados (1X2, ganador, etc.).

Todos comparten la interfaz ``fit(X, y)`` / ``predict_proba(X)`` y se comparan
con validación temporal (walk-forward) en ``engine.validation``. Ninguna
probabilidad sale de un modelo de lenguaje: todas provienen de estos modelos
entrenados con datos históricos reales.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from typing import Callable

import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

warnings.filterwarnings("ignore", category=UserWarning)


class TorchMLP:
    """Perceptrón multicapa en PyTorch con parada temprana temporal."""

    def __init__(self, hidden: int = 32, dropout: float = 0.2, weight_decay: float = 1e-3,
                 epochs: int = 200, lr: float = 3e-3, seed: int = 7):
        self.hidden, self.dropout, self.weight_decay = hidden, dropout, weight_decay
        self.epochs, self.lr, self.seed = epochs, lr, seed
        self.net = None
        self.imputer = SimpleImputer(strategy="median")
        self.scaler = StandardScaler()
        self.n_classes = 3

    def fit(self, X: np.ndarray, y: np.ndarray) -> "TorchMLP":
        import torch
        from torch import nn

        torch.manual_seed(self.seed)
        torch.set_num_threads(2)
        self.n_classes = int(max(y.max() + 1, 2))
        Xs = self.scaler.fit_transform(self.imputer.fit_transform(X)).astype(np.float32)
        n_val = max(50, int(len(Xs) * 0.15))
        Xtr, ytr = torch.tensor(Xs[:-n_val]), torch.tensor(y[:-n_val], dtype=torch.long)
        Xva, yva = torch.tensor(Xs[-n_val:]), torch.tensor(y[-n_val:], dtype=torch.long)
        net = nn.Sequential(
            nn.Linear(Xs.shape[1], self.hidden), nn.ReLU(), nn.Dropout(self.dropout),
            nn.Linear(self.hidden, self.hidden), nn.ReLU(), nn.Dropout(self.dropout),
            nn.Linear(self.hidden, self.n_classes),
        )
        opt = torch.optim.AdamW(net.parameters(), lr=self.lr, weight_decay=self.weight_decay)
        loss_fn = nn.CrossEntropyLoss()
        best, best_state, patience = float("inf"), None, 0
        for _ in range(self.epochs):
            net.train()
            perm = torch.randperm(len(Xtr))
            for i in range(0, len(Xtr), 256):
                b = perm[i:i + 256]
                opt.zero_grad()
                loss = loss_fn(net(Xtr[b]), ytr[b])
                loss.backward()
                opt.step()
            net.eval()
            with torch.no_grad():
                vl = float(loss_fn(net(Xva), yva))
            if vl < best - 1e-4:
                best, best_state, patience = vl, {k: v.clone() for k, v in net.state_dict().items()}, 0
            else:
                patience += 1
                if patience >= 15:
                    break
        if best_state is not None:
            net.load_state_dict(best_state)
        self.net = net
        return self

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        import torch

        Xs = self.scaler.transform(self.imputer.transform(X)).astype(np.float32)
        self.net.eval()
        with torch.no_grad():
            logits = self.net(torch.tensor(Xs))
            return torch.softmax(logits, dim=1).numpy()


def _logreg():
    return make_pipeline(SimpleImputer(strategy="median"), StandardScaler(),
                         LogisticRegression(C=0.3, max_iter=3000))


def _random_forest():
    return make_pipeline(SimpleImputer(strategy="median"),
                         RandomForestClassifier(n_estimators=300, min_samples_leaf=25, max_features=0.5,
                                                n_jobs=-1, random_state=7))


def _lightgbm():
    from lightgbm import LGBMClassifier

    return LGBMClassifier(n_estimators=250, learning_rate=0.03, num_leaves=12, min_child_samples=50,
                          subsample=0.8, subsample_freq=1, colsample_bytree=0.8, reg_lambda=2.0,
                          random_state=7, verbose=-1)


def _xgboost():
    from xgboost import XGBClassifier

    return XGBClassifier(n_estimators=250, max_depth=3, learning_rate=0.03, subsample=0.8,
                         colsample_bytree=0.8, reg_lambda=2.0, min_child_weight=10,
                         objective="multi:softprob", eval_metric="mlogloss", random_state=7, n_jobs=2)


def _catboost():
    from catboost import CatBoostClassifier

    return CatBoostClassifier(iterations=400, depth=4, learning_rate=0.04, l2_leaf_reg=5,
                              loss_function="MultiClass", verbose=0, random_seed=7, thread_count=2,
                              allow_writing_files=False)


def _torch_mlp():
    return TorchMLP()


@dataclass
class ModelSpec:
    name: str
    label: str
    family: str
    factory: Callable


ML_MODELS: dict[str, ModelSpec] = {
    "logreg": ModelSpec("logreg", "Regresión logística multinomial", "lineal", _logreg),
    "random_forest": ModelSpec("random_forest", "Random Forest", "árboles", _random_forest),
    "lightgbm": ModelSpec("lightgbm", "LightGBM", "boosting", _lightgbm),
    "xgboost": ModelSpec("xgboost", "XGBoost", "boosting", _xgboost),
    "catboost": ModelSpec("catboost", "CatBoost", "boosting", _catboost),
    "torch_mlp": ModelSpec("torch_mlp", "Red neuronal (PyTorch MLP)", "deep learning", _torch_mlp),
}


def fit_predict(name: str, Xtr: np.ndarray, ytr: np.ndarray, Xte: np.ndarray) -> tuple[object, np.ndarray]:
    model = ML_MODELS[name].factory()
    model.fit(Xtr, ytr)
    p = model.predict_proba(Xte)
    p = np.clip(p, 1e-6, 1.0)
    return model, p / p.sum(axis=1, keepdims=True)


# ---------------------------------------------------------------------------
# Ensemble por apilamiento (combinación convexa que minimiza log loss)
# ---------------------------------------------------------------------------

def fit_stacking_weights(prob_list: list[np.ndarray], y: np.ndarray) -> np.ndarray:
    from scipy.optimize import minimize

    k = len(prob_list)
    P = np.stack(prob_list, axis=0)  # k × n × c

    def loss(z):
        w = np.exp(z) / np.exp(z).sum()
        mix = np.tensordot(w, P, axes=1)
        return -np.mean(np.log(np.clip(mix[np.arange(len(y)), y], 1e-12, None)))

    res = minimize(loss, np.zeros(k), method="L-BFGS-B")
    w = np.exp(res.x) / np.exp(res.x).sum()
    return w


def combine(prob_list: list[np.ndarray], weights: np.ndarray) -> np.ndarray:
    P = np.stack(prob_list, axis=0)
    mix = np.tensordot(weights, P, axes=1)
    return mix / mix.sum(axis=-1, keepdims=True)
