"""BUSCAR MI CUOTA: orquesta datos → modelos → optimizador → validación → comparación por casa."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...config import get_settings
from ...models import Event, Operator, Parlay
from ..events import event_dict
from ..operators import operator_dict
from ..predictions import build_candidates
from .optimizer import Candidate, ParlayRequest, ParlaySolution, optimize
from .validation import validate

LABELS = {
    "A": "Mayor probabilidad estimada",
    "B": "Equilibrio probabilidad / valor",
    "C": "Mejor valor esperado",
    "D": "Menor número de selecciones",
}
MODE_EXPLANATION = {
    "conservative": "Maximiza la probabilidad conjunta usando la cota inferior de la incertidumbre del modelo.",
    "balanced": "Maximiza log P + ½·log(retorno esperado): equilibra acierto y valor.",
    "value": "Solo selecciones con EV positivo; maximiza el retorno esperado de la combinada.",
    "min_legs": "Busca el menor número de selecciones que alcanza la cuota y, entre ellas, la de mayor probabilidad.",
}


REFERENCE_STALE_SECONDS = 12 * 3600
REFERENCE_NAME = "Referencia internacional (no es casa colombiana)"
REFERENCE_NOTE = ("No hay cuotas de casas colombianas para estos filtros. Se usaron cuotas de REFERENCIA "
                  "(promedio de casas internacionales): su casa puede pagar distinto. Verifique cada cuota "
                  "antes de apostar o cárguela en «Cuotas desde foto» para revaluar la combinada.")


def operator_comparison(sol: ParlaySolution, all_cands: list[Candidate], op_names: dict[str, str]) -> dict:
    """Para cada selección: cuota en cada operador consultado y total por operador."""
    index: dict[tuple, dict[str, Candidate]] = defaultdict(dict)
    for c in all_cands:
        index[(c.event_id, c.selection.key)][c.operator_key] = c
    legs = []
    for c in sol.legs:
        legs.extend(c.components or [c])
    operators = sorted({op for c in legs for op in index[(c.event_id, c.selection.key)]})
    rows = []
    for c in legs:
        offers = index[(c.event_id, c.selection.key)]
        best_op = max(offers, key=lambda o: offers[o].odds) if offers else None
        rows.append({
            "event": c.event_label, "selection": c.selection_label, "selection_key": c.selection.key,
            "probability": c.p,
            "offers": {op: {"odds": offers[op].odds, "captured_at": offers[op].captured_at.isoformat(),
                            "available": True} for op in offers},
            "best_operator": best_op, "best_odds": offers[best_op].odds if best_op else None,
            "unavailable_at": [o for o in operators if o not in offers],
        })
    totals = {}
    for op in operators:
        if all(op in index[(c.event_id, c.selection.key)] for c in legs):
            t = 1.0
            for c in legs:
                t *= index[(c.event_id, c.selection.key)][op].odds
            totals[op] = {"total_odds": t, "complete": True, "name": op_names.get(op, op)}
        else:
            missing = [c.selection_label for c in legs if op not in index[(c.event_id, c.selection.key)]]
            totals[op] = {"total_odds": None, "complete": False, "missing": missing, "name": op_names.get(op, op)}
    complete = {k: v for k, v in totals.items() if v["complete"]}
    best_single = max(complete, key=lambda k: complete[k]["total_odds"]) if complete else None
    return {
        "rows": rows, "per_operator_totals": totals, "best_single_operator": best_single,
        "note": ("Cada total corresponde a la combinada completa en UNA sola casa. No se suman cuotas de "
                 "operadores distintos: una combinada solo puede colocarse en un operador."),
    }


def _hash(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()


def search_my_odds(db: Session, req: ParlayRequest, user_id: int | None = None, save: bool = True) -> dict:
    s = get_settings()
    ops = {o.key: o for o in db.scalars(select(Operator))}
    authorized = {k for k, o in ops.items() if o.status == "authorized"}
    cands, outcomes, model_report = build_candidates(db, include_live=req.include_live)
    same_event_ok = {k: bool((o.capabilities or {}).get("same_event_parlays")) for k, o in ops.items()}
    max_legs = {k: (o.capabilities or {}).get("max_parlay_legs") for k, o in ops.items()}
    stale = s.odds_stale_after_seconds
    result = optimize(cands, req, authorized, same_event_ok, max_legs, outcomes, stale_seconds=stale)
    reference = False
    if req.use_reference and result.considered["candidates_used"] == 0:
        ref_cands, ref_outcomes, _ = build_candidates(db, include_live=req.include_live, operator_status="reference_only")
        if ref_cands:
            ref_keys = {c.operator_key for c in ref_cands}
            stale = REFERENCE_STALE_SECONDS
            ref_req = ParlayRequest(**{**req.__dict__, "operators": None, "allow_same_event": False})
            ref_result = optimize(ref_cands, ref_req, ref_keys, {k: False for k in ref_keys}, {}, ref_outcomes,
                                  stale_seconds=stale)
            if ref_result.considered["candidates_used"]:
                cands, outcomes, result, reference = ref_cands, ref_outcomes, ref_result, True
                result.messages.insert(0, REFERENCE_NOTE)
    event_ids = {c.event_id for c in cands}
    events = {e.id: event_dict(e) for e in db.scalars(select(Event).where(Event.id.in_(event_ids)))} if event_ids else {}
    op_names = {k: o.name for k, o in ops.items()}

    alternatives = {}
    for label, sol in result.alternatives.items():
        if sol is None:
            alternatives[label] = {"label": LABELS[label], "available": False}
            continue
        op_info = operator_dict(ops[sol.operator_key])
        if reference:
            op_info = {**op_info, "status": "authorized", "capabilities": {"parlays": True}}
        v = validate(sol, events, op_info, outcomes=outcomes,
                     stale_seconds=stale, live_stale_seconds=s.live_odds_stale_after_seconds)
        entry = {
            "label": LABELS[label], "available": True, "explanation": MODE_EXPLANATION[sol.mode],
            "operator_name": (REFERENCE_NAME if reference else op_names.get(sol.operator_key, sol.operator_key)),
            "reference": reference,
            **sol.as_dict(), "validation": v,
            "comparison": operator_comparison(sol, cands, op_names),
        }
        if save:
            p = Parlay(user_id=user_id, request=req.__dict__, label=label, mode=sol.mode,
                       operator_key=sol.operator_key, total_odds=sol.total_odds,
                       joint_probability=sol.joint_probability, expected_value=sol.ev,
                       legs=[c.as_dict() for c in sol.legs], validation=v, hash=_hash(entry))
            db.add(p)
            db.flush()
            entry["parlay_id"] = p.id
        alternatives[label] = entry
    if save:
        db.commit()
    # Diferencias entre modos
    modes_diff = []
    for label, a in alternatives.items():
        if a.get("available"):
            modes_diff.append({"parlay": label, "mode": a["mode"], "operator": a["operator"], "n_legs": a["n_legs"],
                               "total_odds": a["total_odds"], "joint_probability": a["joint_probability"],
                               "ev": a["ev"]})
    return {
        "request": req.__dict__, "band": result.considered["band"], "alternatives": alternatives,
        "modes_comparison": modes_diff, "messages": result.messages, "considered": result.considered,
        "model_report": model_report, "reference": reference, "generated_at": datetime.now(timezone.utc).isoformat(),
        "disclaimer": ("Estimaciones estadísticas, no garantías. Las probabilidades provienen de modelos "
                       "entrenados con datos históricos y pueden estar equivocadas. Juega con responsabilidad."),
    }
