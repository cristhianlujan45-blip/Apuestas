"""Validación de una combinada antes de presentarla."""

from __future__ import annotations

from datetime import datetime, timezone

from ...engine.markets import Outcomes, joint_same_event
from .optimizer import Candidate, ParlaySolution, _limit

# Pares de mercados del mismo evento que se excluyen mutuamente o son redundantes
CONFLICTS = [
    ({"1x2:home", "1x2:away", "1x2:draw"}, "resultados 1X2 distintos"),
    ({"btts:yes", "btts:no"}, "ambos marcan sí/no"),
]


def validate(sol: ParlaySolution, events: dict[int, dict], operator: dict, now: datetime | None = None,
             stale_seconds: int = 900, live_stale_seconds: int = 60,
             outcomes: dict[int, Outcomes] | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    checks: list[dict] = []

    def add(name: str, ok: bool, detail: str, level: str = "error") -> None:
        checks.append({"check": name, "ok": ok, "detail": detail, "level": "ok" if ok else level})

    legs: list[Candidate] = []
    for c in sol.legs:
        legs.extend(c.components or [c])

    # 1. Encuentros confirmados
    missing = [c.event_label for c in legs if c.event_id not in events]
    started = [c.event_label for c in legs if c.event_id in events and not c.is_live
               and events[c.event_id]["status"] != "scheduled"]
    add("encuentros_confirmados", not missing and not started,
        "Todos los encuentros existen y no han comenzado" if not (missing or started)
        else f"Problemas: {', '.join(missing + started)}")

    # 2. Cuotas vigentes
    stale = []
    for c in legs:
        age = (now - c.captured_at).total_seconds()
        if age > _limit(c, stale_seconds, live_stale_seconds):
            stale.append(f"{c.selection_label} ({int(age // 60)} min)")
    newest = max(c.captured_at for c in legs)
    oldest = min(c.captured_at for c in legs)
    add("cuotas_vigentes", not stale,
        f"Consultadas entre {oldest.astimezone().strftime('%H:%M:%S')} y {newest.astimezone().strftime('%H:%M:%S')}"
        if not stale else "Cuotas desactualizadas: " + "; ".join(stale))

    # 3. Mercados verificados (todas las selecciones se valoraron con el modelo)
    add("mercados_verificados", all(c.pricing is not None for c in legs), "Cada mercado fue valorado por el modelo")

    # 4. Duplicados
    keys = [(c.event_id, c.selection.key) for c in legs]
    dup = len(keys) != len(set(keys))
    add("sin_duplicados", not dup, "Sin selecciones duplicadas" if not dup else "Hay selecciones duplicadas")

    # 5. Mismo evento y correlaciones
    by_event: dict[int, list[Candidate]] = {}
    for c in legs:
        by_event.setdefault(c.event_id, []).append(c)
    same = {eid: cs for eid, cs in by_event.items() if len(cs) > 1}
    corr_notes = []
    for eid, cs in same.items():
        tags = {f"{c.selection.market}:{c.selection.selection}" for c in cs}
        for group, label in CONFLICTS:
            if len(tags & group) > 1:
                add("selecciones_compatibles", False, f"{cs[0].event_label}: {label}")
        if outcomes and eid in outcomes:
            j = joint_same_event([(c.selection, c.odds) for c in cs], outcomes[eid])
            indep = 1.0
            for c in cs:
                indep *= c.p
            corr_notes.append(f"{cs[0].event_label}: prob. conjunta {j['p_all_win']:.1%} vs "
                              f"{indep:.1%} si fueran independientes")
    if not any(c["check"] == "selecciones_compatibles" for c in checks):
        add("selecciones_compatibles", True, "Sin selecciones contradictorias")
    add("correlaciones", True,
        "; ".join(corr_notes) if corr_notes else
        "Selecciones de eventos distintos: se tratan como independientes condicionalmente al modelo",
        level="info")

    # 6. Reglas del operador
    caps = operator.get("capabilities") or {}
    rules_ok = True
    notes = []
    if caps.get("parlays") is False:
        rules_ok = False
        notes.append("el operador no ofrece combinadas")
    if same and not caps.get("same_event_parlays"):
        rules_ok = False
        notes.append("combina mercados del mismo encuentro y no está verificado que el operador lo permita")
    max_legs = caps.get("max_parlay_legs")
    if max_legs and len(legs) > max_legs:
        rules_ok = False
        notes.append(f"supera el máximo de {max_legs} selecciones")
    if operator.get("status") != "authorized":
        rules_ok = False
        notes.append("operador no autorizado en el registro vigente de Coljuegos")
    add("reglas_operador", rules_ok, "Compatible con las reglas conocidas del operador" if rules_ok else "; ".join(notes))
    if caps.get("same_event_parlays_note") and same:
        add("nota_operador", True, caps["same_event_parlays_note"], level="info")

    # 7. Cuota calculada
    prod = 1.0
    for c in sol.legs:
        prod *= c.odds
    add("cuota_calculada", abs(prod - sol.total_odds) < 1e-6, f"Cuota total = {prod:.2f} (producto de las cuotas)")

    # 8. Datos suficientes
    insufficient = [c.selection_label for c in legs if not c.data_sufficient]
    add("datos_suficientes", not insufficient, "Modelos con historial suficiente para todos los equipos"
        if not insufficient else "Datos insuficientes: " + ", ".join(insufficient), level="warning")

    valid = all(c["ok"] or c["level"] in ("info", "warning") for c in checks)
    return {"valid": valid, "checks": checks, "validated_at": now.isoformat()}
