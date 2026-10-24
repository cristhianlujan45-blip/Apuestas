"""Registro de operadores (Coljuegos) y verificación periódica."""

from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import DATA_DIR
from ..models import Alert, Operator

log = logging.getLogger(__name__)
REGISTRY_PATH = DATA_DIR / "operators" / "coljuegos_registry.json"
COLJUEGOS_URL = "https://www.coljuegos.gov.co/publicaciones/301841/juegosonline/"

CAPABILITY_KEYS = ("platform_provider", "official_public_api", "live_betting", "parlays", "same_event_parlays",
                   "same_event_parlays_note", "odds_format", "max_parlay_legs", "sports_reported",
                   "previous_contracts", "note")


def load_registry() -> dict:
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def sync_operators(db: Session) -> int:
    reg = load_registry()
    verified = date.fromisoformat(reg["source"]["verified_at"])
    n = 0
    entries = [(o, o.get("status", "authorized")) for o in reg["operators"]]
    entries += [(o, "reference_only") for o in reg.get("reference_books", [])]
    for o, status in entries:
        op = db.scalar(select(Operator).where(Operator.key == o["key"]))
        if op is None:
            op = Operator(key=o["key"])
            db.add(op)
        op.name = o["name"]
        op.legal_name = o.get("legal_name")
        op.domains = o.get("domains", [])
        op.contract = o.get("contract")
        op.status = status
        op.capabilities = {k: o.get(k) for k in CAPABILITY_KEYS if k in o}
        op.feed_keys = o.get("odds_feed_keys", {})
        op.source_url = reg["source"]["primary_url"] if status != "reference_only" else None
        op.verified_at = verified
        n += 1
    db.commit()
    return n


def authorized_keys(db: Session) -> set[str]:
    return set(db.scalars(select(Operator.key).where(Operator.status == "authorized")))


def feed_to_operator(db: Session, feed: str = "odds_api_net") -> dict[str, str]:
    """Clave de bookmaker en el feed → clave interna del operador."""
    out = {}
    for op in db.scalars(select(Operator)):
        k = (op.feed_keys or {}).get(feed)
        if k:
            out[k] = op.key
    out.setdefault("pinnacle", "pinnacle")
    return out


def operator_dict(op: Operator) -> dict:
    return {
        "key": op.key, "name": op.name, "legal_name": op.legal_name, "domains": op.domains,
        "contract": op.contract, "status": op.status, "authorized": op.is_authorized,
        "capabilities": op.capabilities, "feed_keys": op.feed_keys, "source_url": op.source_url,
        "verified_at": op.verified_at.isoformat() if op.verified_at else None,
    }


def add_operator(db: Session, data: dict) -> Operator:
    """Alta de un operador nuevo. Queda como 'pending_verification' hasta
    confirmarse en el registro oficial (ver ``verify_against_coljuegos``)."""
    if db.scalar(select(Operator).where(Operator.key == data["key"])):
        raise ValueError("Ya existe un operador con esa clave")
    op = Operator(
        key=data["key"], name=data["name"], legal_name=data.get("legal_name"),
        domains=data.get("domains", []), contract=data.get("contract"), status="pending_verification",
        capabilities={k: data.get(k) for k in CAPABILITY_KEYS if k in data},
        feed_keys=data.get("feed_keys", {}), source_url=COLJUEGOS_URL,
    )
    db.add(op)
    db.commit()
    return op


def _extract_domains(html: str) -> set[str]:
    found = set(re.findall(r"\b((?:[a-z0-9-]+\.)+(?:com\.co|co))\b", html.lower()))
    return {d.removeprefix("www.") for d in found if "coljuegos" not in d and "gov.co" not in d}


def verify_against_coljuegos(db: Session, html: str | None = None) -> dict:
    """Compara los dominios del registro con la página oficial vigente.

    Descarga la página pública de Coljuegos (sin eludir ninguna protección).
    Si un operador autorizado deja de aparecer, se marca como
    'not_in_current_list' y se crea una alerta crítica.
    """
    if html is None:
        with httpx.Client(timeout=30, follow_redirects=True) as c:
            r = c.get(COLJUEGOS_URL)
            r.raise_for_status()
            html = r.text
    page_domains = _extract_domains(html)
    report = {"checked_at": datetime.now(timezone.utc).isoformat(), "source": COLJUEGOS_URL,
              "page_domains": sorted(page_domains), "missing": [], "confirmed": [], "pending_confirmed": []}
    for op in db.scalars(select(Operator).where(Operator.status.in_(["authorized", "pending_verification"]))):
        doms = {d.removeprefix("www.").split("/")[0] for d in (op.domains or [])}
        if doms & page_domains:
            if op.status == "pending_verification":
                op.status = "authorized"
                report["pending_confirmed"].append(op.key)
            report["confirmed"].append(op.key)
            op.verified_at = date.today()
        elif op.status == "authorized":
            report["missing"].append(op.key)
    known = {d for op in db.scalars(select(Operator)) for d in (op.domains or [])}
    report["unknown_on_page"] = sorted(d for d in page_domains if d not in known and not d.startswith("sports."))
    if report["missing"] and len(report["confirmed"]) >= 5:
        # Solo se degrada si la página se leyó correctamente (muchos confirmados)
        for key in report["missing"]:
            op = db.scalar(select(Operator).where(Operator.key == key))
            op.status = "not_in_current_list"
        db.add(Alert(kind="coljuegos_registry", severity="critical",
                     message=f"Operadores ya no listados en Coljuegos: {', '.join(report['missing'])}",
                     payload=report))
    elif len(report["confirmed"]) < 5:
        db.add(Alert(kind="coljuegos_registry", severity="warning",
                     message="No se pudo verificar el registro de Coljuegos (página con formato inesperado)",
                     payload={"confirmed": report["confirmed"]}))
    if report["unknown_on_page"]:
        db.add(Alert(kind="coljuegos_registry", severity="info",
                     message="Dominios nuevos en la página de Coljuegos: " + ", ".join(report["unknown_on_page"]),
                     payload=report))
    db.commit()
    return report
