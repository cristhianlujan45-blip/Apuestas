"""PARLAY AI — optimizador matemático de combinadas.

Formulación
-----------
Para un operador dado, cada selección candidata i tiene cuota o_i y
probabilidad estimada p_i (del motor predictivo). Una combinada es un
conjunto de selecciones con como máximo una por evento (o una «compuesta»
del mismo evento si el operador lo permite). Con eventos distintos

    cuota total  O = Π o_i      →  log O = Σ log o_i
    prob. conj.  P = Π p_i      →  log P = Σ log p_i
    retorno esp. R = Π p_i·o_i  →  log R = Σ log(p_i·o_i)

Todas las funciones objetivo son ADITIVAS en logaritmos, así que el problema
«maximizar el objetivo con la cuota total dentro de [mín, máx] y entre
k_min y k_max selecciones» es una mochila por grupos que se resuelve de forma
exacta con programación dinámica sobre log-cuotas discretizadas
(resolución 0.5 %). Después cada solución se reevalúa con el modelo conjunto
(simulación de las selecciones del mismo evento sobre las mismas muestras).

Modos
-----
* conservador: maximiza Σ log p_i^bajo (probabilidad pesimista, cota inferior
  del intervalo de incertidumbre) — prioriza la probabilidad de acierto.
* equilibrado: maximiza Σ [log p_i + ½·log(p_i·o_i)] — probabilidad y valor.
* valor: maximiza Σ log(p_i·o_i) usando solo selecciones con EV ≥ umbral.
* mínimo: menor número de selecciones posible y, a igualdad, máxima P.

Nota: para una cuota total FIJA, maximizar P equivale a maximizar el EV
(EV = P·O − 1). Los modos se diferencian por la banda de cuotas que
explotan, los filtros por selección y el tratamiento de la incertidumbre.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from itertools import combinations
from typing import Literal
from zoneinfo import ZoneInfo

import numpy as np

from ...engine.markets import LegPricing, Outcomes, Selection, joint_same_event

Mode = Literal["conservative", "balanced", "value", "min_legs"]
STEP = 0.005  # resolución en log-cuota (≈0.5 %)

RISK_PROFILES = {
    # prob. mínima por selección, EV mínimo por selección (modo valor), prob. conjunta mínima relativa
    "low": {"min_leg_prob": 0.55, "min_edge": 0.02, "max_negative_ev": 0.12},
    "medium": {"min_leg_prob": 0.40, "min_edge": 0.02, "max_negative_ev": 0.18},
    "high": {"min_leg_prob": 0.20, "min_edge": 0.01, "max_negative_ev": 0.30},
}


@dataclass
class Candidate:
    event_id: int
    event_label: str
    sport: str
    competition: str | None
    start_time: datetime
    selection: Selection
    selection_label: str
    operator_key: str
    odds: float
    captured_at: datetime
    pricing: LegPricing
    p_low: float | None = None
    p_high: float | None = None
    data_sufficient: bool = True
    is_live: bool = False
    source: str = ""
    components: list["Candidate"] = field(default_factory=list)  # selecciones compuestas
    same_event_note: str | None = None

    @property
    def p(self) -> float:
        return self.pricing.p_effective

    @property
    def ev(self) -> float:
        return self.pricing.ev(self.odds)

    @property
    def expected_return(self) -> float:
        return self.pricing.expected_return(self.odds)

    def as_dict(self) -> dict:
        d = {
            "event_id": self.event_id, "event": self.event_label, "sport": self.sport,
            "competition": self.competition, "start_time": self.start_time.isoformat(),
            "selection_key": self.selection.key, "selection": self.selection_label,
            "operator": self.operator_key, "odds": round(self.odds, 3),
            "captured_at": self.captured_at.isoformat(), "probability": self.p,
            "probability_low": self.p_low, "probability_high": self.p_high,
            "fair_odds": self.pricing.fair_odds(), "ev": self.ev, "pricing": self.pricing.as_dict(),
            "data_sufficient": self.data_sufficient, "is_live": self.is_live, "source": self.source,
        }
        if self.components:
            d["components"] = [c.as_dict() for c in self.components]
            d["same_event_note"] = self.same_event_note
        return d


@dataclass
class ParlayRequest:
    target_odds: float
    min_odds: float | None = None
    max_odds: float | None = None
    min_legs: int = 2
    max_legs: int = 6
    sports: list[str] | None = None
    operators: list[str] | None = None
    markets: list[str] | None = None
    risk: Literal["low", "medium", "high"] = "medium"
    allow_same_event: bool = False
    same_day_only: bool = False
    max_hours_ahead: float | None = 72
    include_live: bool = False
    # Días elegidos por el usuario (AAAA-MM-DD, hora de Colombia). Si hay días, no se aplica el horizonte.
    dates: list[str] | None = None
    # Si no hay cuotas colombianas que cumplan los filtros, usar cuotas de referencia
    # internacionales (claramente señaladas) para que el usuario las verifique en su casa.
    use_reference: bool = True

    def band(self) -> tuple[float, float]:
        lo = self.min_odds if self.min_odds else max(1.01, self.target_odds * 0.9)
        hi = self.max_odds if self.max_odds else self.target_odds * 1.15
        if hi < lo:
            raise ValueError("La cuota máxima debe ser mayor que la mínima")
        return lo, hi


@dataclass
class ParlaySolution:
    operator_key: str
    mode: Mode
    legs: list[Candidate]
    total_odds: float
    joint_probability: float          # P(ninguna selección perdida, con nulos)
    joint_probability_all_win: float  # P(todas ganadas completamente)
    independent_probability: float    # Π p_i (referencia)
    expected_return: float
    joint_probability_low: float | None = None
    joint_probability_high: float | None = None

    @property
    def ev(self) -> float:
        return self.expected_return - 1.0

    @property
    def key(self) -> tuple:
        return (self.operator_key, tuple(sorted(c.selection.key + str(c.event_id) for c in self.legs)))

    def as_dict(self) -> dict:
        return {
            "operator": self.operator_key, "mode": self.mode, "legs": [c.as_dict() for c in self.legs],
            "n_legs": sum(max(1, len(c.components)) for c in self.legs),
            "total_odds": round(self.total_odds, 3), "joint_probability": self.joint_probability,
            "joint_probability_all_win": self.joint_probability_all_win,
            "independent_probability": self.independent_probability,
            "joint_probability_low": self.joint_probability_low,
            "joint_probability_high": self.joint_probability_high,
            "fair_total_odds": (1 / self.joint_probability) if self.joint_probability > 0 else None,
            "expected_return": self.expected_return, "ev": self.ev,
        }


def leg_value(c: Candidate, mode: Mode) -> float:
    p = max(c.p, 1e-9)
    if mode == "conservative":
        return math.log(max(c.p_low if c.p_low else p, 1e-9))
    if mode == "balanced":
        return math.log(p) + 0.5 * math.log(max(c.expected_return, 1e-9))
    if mode == "value":
        return math.log(max(c.expected_return, 1e-9))
    return math.log(p)  # min_legs


def _dp(groups: list[list[Candidate]], values: list[list[float]], lo: float, hi: float,
        kmin: int, kmax: int, mode: Mode, top: int = 6) -> list[list[Candidate]]:
    """Mochila por grupos exacta sobre log-cuotas discretizadas.

    Se guarda la tabla de elección de cada etapa para reconstruir de forma
    exacta las mejores soluciones (no solo la óptima)."""
    W = int(math.floor(math.log(hi) / STEP)) + 1
    wlo = int(math.ceil(math.log(lo) / STEP))
    K = kmax
    NEG = -1e18
    weights = [[int(round(math.log(c.odds) / STEP)) for c in g] for g in groups]
    stages = [np.full((K + 1, W + 1), NEG)]
    stages[0][0, 0] = 0.0
    choices = []
    for gi, g in enumerate(groups):
        prev = stages[-1]
        new = prev.copy()
        ch = np.full((K + 1, W + 1), -1, dtype=np.int16)
        for ii, (w, v) in enumerate(zip(weights[gi], values[gi])):
            if w <= 0 or w > W:
                continue
            cand = np.full_like(prev, NEG)
            cand[1:, w:] = prev[:-1, : W + 1 - w] + v
            better = cand > new + 1e-12
            new = np.where(better, cand, new)
            ch[better] = ii
        stages.append(new)
        choices.append(ch)
    best = stages[-1]
    finals = [(k, w, best[k, w]) for k in range(kmin, K + 1) for w in range(wlo, W + 1) if best[k, w] > NEG / 2]
    if not finals:
        return []
    if mode == "min_legs":
        kbest = min(f[0] for f in finals)
        finals = [f for f in finals if f[0] == kbest]
    finals.sort(key=lambda f: f[2], reverse=True)
    out, seen = [], set()
    for k, w, _ in finals:
        legs, kk, ww = [], k, w
        for gi in range(len(groups) - 1, -1, -1):
            ii = int(choices[gi][kk, ww])
            if ii >= 0:
                legs.append(groups[gi][ii])
                ww -= weights[gi][ii]
                kk -= 1
        if kk != 0 or ww != 0:
            continue
        key = tuple(sorted(id(c) for c in legs))
        if key in seen:
            continue
        seen.add(key)
        out.append(list(reversed(legs)))
        if len(out) >= top:
            break
    return out


def evaluate(operator: str, mode: Mode, legs: list[Candidate],
             outcomes: dict[int, Outcomes] | None = None) -> ParlaySolution:
    total = 1.0
    p_no_loss = 1.0
    p_all = 1.0
    indep = 1.0
    er = 1.0
    plow = 1.0
    phigh = 1.0
    for c in legs:
        total *= c.odds
        if c.components and outcomes and c.event_id in outcomes:
            j = joint_same_event([(x.selection, x.odds) for x in c.components], outcomes[c.event_id])
            p_no_loss *= j["p_no_loss"]
            p_all *= j["p_all_win"]
            er *= j["expected_return"]
            for x in c.components:
                indep *= x.p
        else:
            pr = c.pricing
            p_no_loss *= 1 - pr.p_lose
            p_all *= pr.p_win
            er *= c.expected_return
            indep *= c.p
        plow *= c.p_low if c.p_low else c.p
        phigh *= c.p_high if c.p_high else c.p
    return ParlaySolution(operator, mode, legs, total, p_no_loss, p_all, indep, er, plow, phigh)


def build_same_event_composites(cands: list[Candidate], outcomes: Outcomes, max_pairs: int = 15) -> list[Candidate]:
    """Selecciones compuestas del mismo evento (2 mercados distintos)."""
    from ...engine.markets import UnsupportedMarket

    out = []
    pool = sorted(cands, key=lambda c: c.p, reverse=True)[:8]
    for a, b in combinations(pool, 2):
        if a.selection.market == b.selection.market:
            continue
        try:
            j = joint_same_event([(a.selection, a.odds), (b.selection, b.odds)], outcomes)
        except UnsupportedMarket:
            continue
        if j["p_all_win"] < 1e-4:
            continue  # selecciones incompatibles
        odds = a.odds * b.odds
        p_all = j["p_all_win"]
        # Representar la compuesta como una selección binaria con su prob. conjunta
        pricing = LegPricing(p_all, 0.0, max(0.0, j["p_no_loss"] - p_all), 0.0, 1 - j["p_no_loss"])
        comp = Candidate(
            event_id=a.event_id, event_label=a.event_label, sport=a.sport, competition=a.competition,
            start_time=a.start_time, selection=Selection("same_event", f"{a.selection.key}+{b.selection.key}"),
            selection_label=f"{a.selection_label} + {b.selection_label}", operator_key=a.operator_key,
            odds=odds, captured_at=min(a.captured_at, b.captured_at), pricing=pricing,
            data_sufficient=a.data_sufficient and b.data_sufficient, components=[a, b],
            same_event_note=("Probabilidad conjunta simulada sobre el mismo partido. La cuota mostrada es el "
                             "producto; el operador puede ajustarla en su creador de apuestas."),
        )
        out.append(comp)
        if len(out) >= max_pairs:
            break
    return out


@dataclass
class OptimizationResult:
    request: ParlayRequest
    alternatives: dict[str, ParlaySolution | None]
    per_operator: dict[str, list[ParlaySolution]]
    considered: dict
    messages: list[str]


BOGOTA = ZoneInfo("America/Bogota")


def bogota_date(t: datetime) -> str:
    return t.astimezone(BOGOTA).date().isoformat()


def _limit(c: "Candidate", stale_seconds: int, live_stale_seconds: int) -> int:
    from ..odds import stale_limit

    return live_stale_seconds if c.is_live else max(stale_seconds, stale_limit(c.source, False, stale_seconds))


def filter_candidates(cands: list[Candidate], req: ParlayRequest, authorized: set[str],
                      now: datetime | None = None, stale_seconds: int = 900,
                      live_stale_seconds: int = 60) -> tuple[list[Candidate], dict]:
    now = now or datetime.now(timezone.utc)
    prof = RISK_PROFILES[req.risk]
    reasons: dict[str, int] = {}

    def drop(r: str) -> None:
        reasons[r] = reasons.get(r, 0) + 1

    keep = []
    for c in cands:
        if c.operator_key not in authorized:
            drop("operador no autorizado por Coljuegos")
            continue
        if req.operators and c.operator_key not in req.operators:
            drop("operador excluido por el usuario")
            continue
        if req.sports and c.sport not in req.sports:
            drop("deporte excluido")
            continue
        if req.markets and c.selection.market not in req.markets:
            drop("mercado excluido")
            continue
        if c.is_live and not req.include_live:
            drop("en directo excluido")
            continue
        if not c.is_live and c.start_time <= now:
            drop("evento ya iniciado")
            continue
        if req.dates and bogota_date(c.start_time) not in req.dates:
            drop("fuera de los días elegidos")
            continue
        if not req.dates and req.max_hours_ahead and (c.start_time - now).total_seconds() > req.max_hours_ahead * 3600:
            drop("fuera de la ventana temporal")
            continue
        if req.same_day_only and bogota_date(c.start_time) != bogota_date(now):
            drop("no es del mismo día")
            continue
        age = (now - c.captured_at).total_seconds()
        if age > _limit(c, stale_seconds, live_stale_seconds):
            drop("cuota desactualizada")
            continue
        if not c.data_sufficient:
            drop("datos insuficientes para el modelo")
            continue
        if c.p < prof["min_leg_prob"]:
            drop("probabilidad por debajo del perfil de riesgo")
            continue
        if c.odds < 1.03:
            drop("cuota demasiado baja")
            continue
        keep.append(c)
    return keep, reasons


def optimize(cands: list[Candidate], req: ParlayRequest, authorized: set[str],
             same_event_allowed: dict[str, bool] | None = None,
             max_legs_by_operator: dict[str, int | None] | None = None,
             outcomes: dict[int, Outcomes] | None = None, now: datetime | None = None,
             stale_seconds: int = 900, per_event_top: int = 6) -> OptimizationResult:
    lo, hi = req.band()
    prof = RISK_PROFILES[req.risk]
    pool, reasons = filter_candidates(cands, req, authorized, now, stale_seconds)
    messages: list[str] = []
    by_op: dict[str, dict[int, list[Candidate]]] = {}
    for c in pool:
        by_op.setdefault(c.operator_key, {}).setdefault(c.event_id, []).append(c)

    per_operator: dict[str, list[ParlaySolution]] = {}
    modes: list[Mode] = ["conservative", "balanced", "value", "min_legs"]
    for op, events in by_op.items():
        kmax = req.max_legs
        cap = (max_legs_by_operator or {}).get(op)
        if cap:
            kmax = min(kmax, cap)
        if len(events) < req.min_legs:
            continue
        sols: list[ParlaySolution] = []
        for mode in modes:
            groups, values = [], []
            for eid, items in events.items():
                its = list(items)
                if req.allow_same_event and (same_event_allowed or {}).get(op) and outcomes and eid in outcomes:
                    its += build_same_event_composites(items, outcomes[eid])
                if mode == "value":
                    its = [c for c in its if c.ev >= prof["min_edge"]]
                if not its:
                    continue
                its.sort(key=lambda c: leg_value(c, mode), reverse=True)
                its = its[:per_event_top]
                groups.append(its)
                values.append([leg_value(c, mode) for c in its])
            if len(groups) < req.min_legs:
                continue
            for legs in _dp(groups, values, lo, hi, req.min_legs, kmax, mode, top=3):
                sols.append(evaluate(op, mode, legs, outcomes))
        if sols:
            per_operator[op] = sols

    def pick(mode: Mode) -> ParlaySolution | None:
        options = [s for ss in per_operator.values() for s in ss if s.mode == mode]
        if mode == "value":
            options = [s for s in options if s.ev > 0]
        if not options:
            return None
        if mode == "conservative":
            return max(options, key=lambda s: (s.joint_probability_low or s.joint_probability))
        if mode == "balanced":
            return max(options, key=lambda s: math.log(max(s.joint_probability, 1e-12))
                       + 0.5 * math.log(max(s.expected_return, 1e-12)))
        if mode == "value":
            return max(options, key=lambda s: s.ev)
        kmin = min(len(s.legs) for s in options)
        return max((s for s in options if len(s.legs) == kmin), key=lambda s: s.joint_probability)

    alternatives = {
        "A": pick("conservative"),
        "B": pick("balanced"),
        "C": pick("value"),
        "D": pick("min_legs"),
    }
    # Solidez: no presentar combinadas cuyo EV sea peor que el límite del perfil
    for label, sol in list(alternatives.items()):
        if sol is None:
            continue
        if sol.ev < -prof["max_negative_ev"]:
            messages.append(
                f"Parlay {label}: descartado. Su valor esperado estimado ({sol.ev:+.1%}) es peor que el "
                f"límite del perfil de riesgo ({-prof['max_negative_ev']:.0%}).")
            alternatives[label] = None
    if alternatives["C"] is None:
        messages.append("No se encontró ninguna combinada con valor esperado positivo y respaldo "
                        "estadístico dentro de la banda de cuotas solicitada.")
    if all(v is None for v in alternatives.values()):
        messages.append("No existe una combinación suficientemente sólida para la cuota solicitada con "
                        "los datos disponibles. No se fuerza un resultado.")
    considered = {"candidates_in": len(cands), "candidates_used": len(pool), "operators": list(by_op),
                  "discarded": reasons, "band": [lo, hi]}
    return OptimizationResult(req, alternatives, per_operator, considered, messages)
