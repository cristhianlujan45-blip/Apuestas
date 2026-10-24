"""Asistente de IA deportiva.

El asistente SOLO consulta herramientas de la plataforma (datos y modelos
reales). Con ``ANTHROPIC_API_KEY`` usa Claude para entender la petición,
elegir herramientas y redactar la respuesta; sin clave usa un enrutador de
intenciones en español. En ambos casos los números provienen exclusivamente
de las herramientas: el modelo de lenguaje nunca genera probabilidades.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from ..config import get_settings
from ..models import Event, Operator
from ..names import similarity
from .events import aware, event_dict
from .history import performance
from .odds import compare_event, compare_operators
from .parlay.optimizer import ParlayRequest
from .parlay.service import search_my_odds
from .predictions import build_candidates, model_event, value_bets

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """Eres el analista de la plataforma de inteligencia deportiva para Colombia.
Respondes en español, de forma clara y profesional.

Reglas obligatorias:
- Todo número que menciones (probabilidades, cuotas, EV, métricas) debe salir de los resultados de las herramientas. Nunca estimes ni inventes probabilidades o cuotas.
- Si una herramienta indica que faltan datos o claves de proveedores, dilo con claridad y sugiere cómo resolverlo.
- Diferencia siempre probabilidad alta de acierto y valor esperado positivo: no son lo mismo.
- Solo recomiendas operadores autorizados por Coljuegos. Una combinada se coloca en un único operador.
- No prometes ganancias. Recuerda brevemente el juego responsable cuando hables de apuestas.
- Para pedidos de combinadas o cuotas objetivo usa la herramienta buscar_mi_cuota."""

TOOLS = [
    {"name": "partidos", "description": "Lista partidos de hoy, en directo o próximos con predicción del modelo.",
     "input_schema": {"type": "object", "properties": {
         "scope": {"type": "string", "enum": ["hoy", "directo", "proximos"]},
         "sport": {"type": "string", "description": "football, basketball, tennis, baseball, volleyball"}},
         "required": ["scope"], "additionalProperties": False}},
    {"name": "buscar_mi_cuota", "description": "Optimiza combinadas (Parlay A/B/C/D) para una cuota objetivo con operadores colombianos.",
     "input_schema": {"type": "object", "properties": {
         "target_odds": {"type": "number"}, "max_legs": {"type": "integer"}, "min_legs": {"type": "integer"},
         "sports": {"type": "array", "items": {"type": "string"}},
         "operators": {"type": "array", "items": {"type": "string"}},
         "risk": {"type": "string", "enum": ["low", "medium", "high"]}},
         "required": ["target_odds"], "additionalProperties": False}},
    {"name": "comparar_operadores", "description": "Compara las cuotas de dos operadores en las selecciones comunes.",
     "input_schema": {"type": "object", "properties": {"a": {"type": "string"}, "b": {"type": "string"}},
                      "required": ["a", "b"], "additionalProperties": False}},
    {"name": "mejores_cuotas_partido", "description": "Mejores cuotas por selección para un partido buscado por nombre.",
     "input_schema": {"type": "object", "properties": {"query": {"type": "string"}},
                      "required": ["query"], "additionalProperties": False}},
    {"name": "ultimos_partidos", "description": "Últimos N partidos reales de un equipo con estadísticas.",
     "input_schema": {"type": "object", "properties": {"team": {"type": "string"}, "n": {"type": "integer"}},
                      "required": ["team"], "additionalProperties": False}},
    {"name": "oportunidades_valor", "description": "Selecciones con valor esperado positivo según el modelo.",
     "input_schema": {"type": "object", "properties": {"min_edge": {"type": "number"}},
                      "additionalProperties": False}},
    {"name": "rendimiento_modelos", "description": "Métricas históricas reales de las predicciones (Brier, log loss, ROI).",
     "input_schema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "alineaciones", "description": "Alineaciones confirmadas de un partido (API-Football) y análisis actualizado.",
     "input_schema": {"type": "object", "properties": {"query": {"type": "string"}},
                      "required": ["query"], "additionalProperties": False}},
]


class Toolbox:
    def __init__(self, db: Session, user_id: int | None = None):
        self.db = db
        self.user_id = user_id

    # ------------------------------------------------------------------ util
    def _events(self, scope: str, sport: str | None = None) -> list[Event]:
        now = datetime.now(timezone.utc)
        q = select(Event).options(joinedload(Event.home), joinedload(Event.away), joinedload(Event.competition))
        if scope == "directo":
            q = q.where(Event.status == "live")
        elif scope == "hoy":
            q = q.where(Event.start_time >= now - timedelta(hours=3), Event.start_time < now + timedelta(hours=24))
        else:
            q = q.where(Event.status == "scheduled", Event.start_time >= now, Event.start_time < now + timedelta(days=4))
        if sport:
            q = q.where(Event.sport == sport)
        return list(self.db.scalars(q.order_by(Event.start_time).limit(60)).unique())

    def _find_event(self, query: str) -> Event | None:
        evs = self._events("proximos") + self._events("directo")
        best, score = None, 0.0
        parts = re.split(r"\s+(?:vs\.?|v|contra|-)\s+", query, flags=re.I)
        for ev in evs:
            if len(parts) == 2:
                s = min(similarity(parts[0], ev.home.name), similarity(parts[1], ev.away.name))
            else:
                s = max(similarity(query, ev.home.name), similarity(query, ev.away.name))
            if s > score:
                best, score = ev, s
        return best if score >= 0.6 else None

    # ---------------------------------------------------------------- tools
    def partidos(self, scope: str = "hoy", sport: str | None = None) -> dict:
        out = []
        for ev in self._events(scope, sport)[:25]:
            em = model_event(self.db, ev, n_draws=0)
            d = event_dict(ev)
            if em.summary.get("probs"):
                d["model_probs"] = em.summary["probs"]
                d["expected_goals"] = em.summary.get("expected_goals")
            elif em.summary.get("prediction"):
                d["model"] = {k: v for k, v in em.summary["prediction"].items() if isinstance(v, (int, float))}
            if em.summary.get("live"):
                d["live_probs"] = em.summary["live"]["probs"]
            d["data_sufficient"] = em.sufficient
            d["model_note"] = em.reason
            out.append(d)
        return {"scope": scope, "events": out, "count": len(out)}

    def buscar_mi_cuota(self, target_odds: float, max_legs: int = 6, min_legs: int = 2, sports=None,
                        operators=None, risk: str = "medium") -> dict:
        req = ParlayRequest(target_odds=float(target_odds), max_legs=int(max_legs), min_legs=int(min_legs),
                            sports=sports or None, operators=operators or None, risk=risk)
        res = search_my_odds(self.db, req, self.user_id)
        compact = {}
        for k, a in res["alternatives"].items():
            if not a.get("available"):
                compact[k] = {"label": a["label"], "available": False}
                continue
            compact[k] = {"label": a["label"], "operator": a["operator_name"], "total_odds": a["total_odds"],
                          "joint_probability": a["joint_probability"], "ev": a["ev"],
                          "legs": [{"event": l["event"], "selection": l["selection"], "odds": l["odds"],
                                    "probability": l["probability"]} for l in a["legs"]],
                          "valid": a["validation"]["valid"],
                          "best_single_operator": a["comparison"]["best_single_operator"]}
        return {"alternatives": compact, "messages": res["messages"], "considered": res["considered"],
                "model_report": res["model_report"]}

    def comparar_operadores(self, a: str, b: str) -> dict:
        keys = {o.key: o for o in self.db.scalars(select(Operator))}
        ka = min(keys, key=lambda k: -similarity(a, keys[k].name))
        kb = min(keys, key=lambda k: -similarity(b, keys[k].name))
        return compare_operators(self.db, ka, kb)

    def mejores_cuotas_partido(self, query: str) -> dict:
        ev = self._find_event(query)
        if ev is None:
            return {"error": f"No encontré un partido próximo que coincida con '{query}'"}
        cmp = compare_event(self.db, ev)
        rows = [{"selection": r["label"], "best": r["best"], "spread_pct": r["spread_pct"],
                 "n_operators": len(r["offers"])} for r in cmp["rows"] if r["best"]]
        return {"event": event_dict(ev), "best_odds": rows[:40], "margins": cmp["margins"][:10]}

    def ultimos_partidos(self, team: str, n: int = 10) -> dict:
        from .model_store import football_history

        hist = _history_cache.get("df")
        if hist is None:
            hist = football_history(include_colombia=False)
            _history_cache["df"] = hist
        teams = sorted(set(hist["home"]) | set(hist["away"]))
        best = max(teams, key=lambda t: similarity(team, t)) if teams else None
        if best is None or similarity(team, best) < 0.6:
            return {"error": f"Sin histórico para '{team}'"}
        d = hist[((hist["home"] == best) | (hist["away"] == best)) & hist["hg"].notna()].sort_values("date").tail(int(n))
        rows = []
        for r in d.to_dict("records"):
            home = r["home"] == best
            gf, ga = (r["hg"], r["ag"]) if home else (r["ag"], r["hg"])
            rows.append({"date": str(pd.Timestamp(r["date"]).date()), "opponent": r["away"] if home else r["home"],
                         "venue": "local" if home else "visitante", "score": f"{int(r['hg'])}-{int(r['ag'])}",
                         "result": "G" if gf > ga else ("E" if gf == ga else "P"),
                         "shots": r["hs"] if home else r["as"], "shots_on_target": r["hst"] if home else r["ast"],
                         "corners": r["hc"] if home else r["ac"]})
        res = [x["result"] for x in rows]
        return {"team": best, "matches": rows, "summary": {"wins": res.count("G"), "draws": res.count("E"),
                                                           "losses": res.count("P")}, "source": "football-data.co.uk"}

    def oportunidades_valor(self, min_edge: float = 0.03) -> dict:
        cands, _, report = build_candidates(self.db)
        vb = value_bets([c for c in cands if c.data_sufficient], min_edge)
        return {"value_bets": vb[:25], "count": len(vb), "report": report,
                "note": "EV positivo ≠ alta probabilidad de acierto."}

    def rendimiento_modelos(self) -> dict:
        p = performance(self.db, "football")
        return {k: v for k, v in p.items() if not k.startswith("calibration") and k != "rolling_log_loss"}

    def alineaciones(self, query: str) -> dict:
        from ..providers.api_sports import ApiFootball

        ev = self._find_event(query)
        if ev is None:
            return {"error": f"No encontré el partido '{query}'"}
        api = ApiFootball()
        fid = (ev.external_ids or {}).get("api_football")
        if not api.configured:
            return {"error": "API_FOOTBALL_KEY no configurada: no hay acceso a alineaciones confirmadas."}
        if not fid:
            return {"error": "El partido no está vinculado a API-Football todavía (se vincula en la próxima ingesta)."}
        lineups = api.lineups(fid)
        em = model_event(self.db, ev, n_draws=0)
        return {"event": event_dict(ev), "lineups": lineups, "model_probs": em.summary.get("probs"),
                "note": ("El modelo de goles usa fuerzas de equipo; las alineaciones se muestran para el análisis "
                         "pero aún no ajustan automáticamente las probabilidades por jugador.")}

    def call(self, name: str, args: dict) -> dict:
        fn = getattr(self, name, None)
        if fn is None or name.startswith("_") or name == "call":
            return {"error": f"Herramienta desconocida: {name}"}
        return fn(**args)


_history_cache: dict = {}

# ---------------------------------------------------------------------------
# Enrutador sin LLM
# ---------------------------------------------------------------------------

OPERATOR_WORDS = ["betplay", "wplay", "betsson", "betano", "rushbet", "codere", "bwin", "stake", "rivalo",
                  "luckia", "sportium", "zamba", "yajuego", "mryoker"]


def route(text: str) -> tuple[str, dict] | None:
    t = text.lower()
    m = re.search(r"cuota\s*(?:de|a|objetivo)?\s*(\d+(?:[.,]\d+)?)", t)
    legs = re.search(r"m[aá]ximo\s+(\d+)\s+selecci", t)
    if m or "parlay" in t or "combinada" in t:
        args: dict = {"target_odds": float(m.group(1).replace(",", ".")) if m else 5.0}
        if legs:
            args["max_legs"] = int(legs.group(1))
            args["min_legs"] = min(2, args["max_legs"])
        if "mixto" in t:
            args["sports"] = ["football", "basketball", "tennis", "baseball", "volleyball"]
        if "mayor probabilidad" in t or "conservador" in t:
            args["risk"] = "low"
        return "buscar_mi_cuota", args
    ops = [o for o in OPERATOR_WORDS if o in t]
    if "compar" in t and len(ops) >= 2:
        return "comparar_operadores", {"a": ops[0], "b": ops[1]}
    if "alinea" in t:
        q = re.sub(r".*alineaciones?\s*(confirmadas)?\s*(de|del|para)?\s*", "", t).strip() or t
        return "alineaciones", {"query": q}
    m = re.search(r"[uú]ltimos\s+(\d+|diez|cinco)\s+partidos\s+(?:de|del)\s+(.+)", t)
    if m:
        n = {"diez": 10, "cinco": 5}.get(m.group(1), None) or int(m.group(1))
        return "ultimos_partidos", {"team": m.group(2).strip(" ?."), "n": n}
    if "mejores cuotas" in t:
        q = re.sub(r".*mejores cuotas\s*(para|de|del)?\s*(este partido|el partido)?\s*", "", t).strip(" ?.")
        return "mejores_cuotas_partido", {"query": q or t}
    if "oportunidad" in t or "valor" in t:
        return "oportunidades_valor", {}
    if "rendimiento" in t or "precisi" in t or "métrica" in t:
        return "rendimiento_modelos", {}
    if "directo" in t or "en vivo" in t:
        return "partidos", {"scope": "directo"}
    if "hoy" in t or "analiza" in t:
        return "partidos", {"scope": "hoy"}
    if "próximos" in t or "proximos" in t:
        return "partidos", {"scope": "proximos"}
    return None


def _render_without_llm(name: str, result: dict) -> str:
    if "error" in result:
        return f"⚠️ {result['error']}"
    if name == "buscar_mi_cuota":
        lines = []
        for k, a in result["alternatives"].items():
            if not a.get("available"):
                lines.append(f"**Parlay {k} ({a['label']})**: no disponible.")
                continue
            lines.append(f"**Parlay {k} — {a['label']}** · {a['operator']} · cuota {a['total_odds']:.2f} · "
                         f"prob. estimada {a['joint_probability']:.1%} · EV {a['ev']:+.1%}")
            for leg in a["legs"]:
                lines.append(f"  - {leg['event']}: {leg['selection']} @ {leg['odds']:.2f} (p={leg['probability']:.1%})")
        lines += [f"_{m}_" for m in result["messages"]]
        if result.get("model_report", {}).get("events_with_quotes", 0) == 0:
            lines.append("_No hay cuotas de operadores colombianos cargadas. Configure ODDS_API_NET_KEY o cargue cuotas manualmente._")
        return "\n".join(lines)
    if name == "partidos":
        if not result["events"]:
            return "No hay partidos en ese rango en la base de datos. Ejecute la ingesta de datos."
        lines = []
        for e in result["events"]:
            p = e.get("live_probs") or e.get("model_probs")
            ptxt = f" · L {p['home']:.0%} / E {p.get('draw', 0):.0%} / V {p['away']:.0%}" if p else ""
            lines.append(f"- {e['start_time'][11:16]} UTC {e['label']} ({e.get('competition') or e['sport']}){ptxt}")
        return "\n".join(lines)
    if name == "ultimos_partidos":
        s = result["summary"]
        lines = [f"**{result['team']}** — últimos {len(result['matches'])} partidos: {s['wins']}G {s['draws']}E {s['losses']}P"]
        for m in reversed(result["matches"]):
            sot = f" · tiros al arco {int(m['shots_on_target'])}" if pd.notna(m.get("shots_on_target")) else ""
            lines.append(f"- {m['date']} {m['venue']} vs {m['opponent']}: {m['score']} ({m['result']}){sot}")
        lines.append(f"_Fuente: {result['source']}_")
        return "\n".join(lines)
    if name == "comparar_operadores":
        r = result
        if not r["common_selections"]:
            return f"No hay selecciones con cuota de **{r['operator_a']}** y **{r['operator_b']}** a la vez en la base de datos."
        return (f"**{r['operator_a']}** vs **{r['operator_b']}** en {r['common_selections']} selecciones comunes: "
                f"{r['operator_a']} paga más en {r['a_better']}, {r['operator_b']} en {r['b_better']}, iguales {r['equal']}. "
                f"Diferencia media: {r['avg_pct_difference_a_vs_b']:+.2f} %. Solo en {r['operator_a']}: {r['only_in_a']}; "
                f"solo en {r['operator_b']}: {r['only_in_b']}.")
    if name == "mejores_cuotas_partido":
        ev = result["event"]
        if not result["best_odds"]:
            return f"**{ev['label']}**: no hay cuotas de operadores colombianos cargadas para este partido."
        lines = [f"**{ev['label']}** — mejores cuotas por selección:"]
        for r in result["best_odds"][:15]:
            lines.append(f"- {r['selection']}: {r['best']['odds']:.2f} en {r['best']['operator']} ({r['n_operators']} casas)")
        return "\n".join(lines)
    if name == "oportunidades_valor":
        if not result["value_bets"]:
            return "No encontré selecciones con valor esperado positivo en las cuotas colombianas disponibles."
        lines = ["Selecciones con EV positivo (no implica alta probabilidad de acierto):"]
        for v in result["value_bets"][:10]:
            lines.append(f"- {v['event']}: {v['selection']} @ {v['odds']:.2f} ({v['operator']}) · p={v['probability']:.1%} · EV {v['ev']:+.1%}")
        return "\n".join(lines)
    if name == "rendimiento_modelos":
        if not result.get("n"):
            return result.get("message", "Sin datos de rendimiento todavía.")
        return (f"Predicciones liquidadas: {result['n']} · log loss {result['log_loss']:.4f} · Brier {result['brier']:.4f} · "
                f"RPS {result['rps']:.4f} · acierto {result['accuracy']:.1%}")
    return "```json\n" + json.dumps(result, ensure_ascii=False, indent=1, default=str)[:6000] + "\n```"


# ---------------------------------------------------------------------------
# Bucle con Claude (uso de herramientas)
# ---------------------------------------------------------------------------

def _claude_answer(db: Session, messages: list[dict], user_id: int | None) -> dict:
    import anthropic

    s = get_settings()
    client = anthropic.Anthropic(api_key=s.anthropic_api_key)
    box = Toolbox(db, user_id)
    tools = [{**t, "strict": True} for t in TOOLS]
    convo = list(messages)
    used = []
    for _ in range(6):
        resp = client.beta.messages.create(
            model=s.assistant_model, max_tokens=8000, system=SYSTEM_PROMPT, tools=tools, messages=convo,
            output_config={"effort": "low"}, betas=["server-side-fallback-2026-07-01"], fallbacks="default",
        )
        if resp.stop_reason == "refusal":
            return {"answer": "No puedo ayudar con esa solicitud.", "tools_used": used, "engine": "claude"}
        if resp.stop_reason != "tool_use":
            text = "\n".join(b.text for b in resp.content if b.type == "text")
            return {"answer": text, "tools_used": used, "engine": "claude"}
        convo.append({"role": "assistant", "content": resp.content})
        results = []
        for b in resp.content:
            if b.type != "tool_use":
                continue
            try:
                out = box.call(b.name, dict(b.input))
                results.append({"type": "tool_result", "tool_use_id": b.id,
                                "content": json.dumps(out, ensure_ascii=False, default=str)[:30000]})
            except Exception as exc:  # noqa: BLE001
                results.append({"type": "tool_result", "tool_use_id": b.id, "content": f"Error: {exc}",
                                "is_error": True})
            used.append(b.name)
        convo.append({"role": "user", "content": results})
    return {"answer": "La consulta requirió demasiados pasos; intente una pregunta más concreta.",
            "tools_used": used, "engine": "claude"}


def answer(db: Session, messages: list[dict], user_id: int | None = None) -> dict:
    s = get_settings()
    if s.anthropic_api_key:
        try:
            return _claude_answer(db, messages, user_id)
        except Exception as exc:  # noqa: BLE001
            log.warning("Asistente Claude no disponible, uso enrutador local: %s", exc)
    last = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
    if not isinstance(last, str):
        last = str(last)
    routed = route(last)
    if routed is None:
        return {"answer": ("Puedo analizar los partidos de hoy o en directo, buscar una cuota objetivo "
                           "(«busca una cuota de 5»), comparar operadores («compara BetPlay con Wplay»), "
                           "mostrar las mejores cuotas de un partido, los últimos 10 partidos de un equipo, "
                           "oportunidades de valor y el rendimiento de los modelos."),
                "tools_used": [], "engine": "router"}
    name, args = routed
    result = Toolbox(db, user_id).call(name, args)
    return {"answer": _render_without_llm(name, result), "tools_used": [name], "engine": "router",
            "data": result}
