"""OddsPapi — cuotas de BetPlay y Rushbet (Colombia) con plan gratuito.

Plan gratuito: 250 peticiones/mes, sin tarjeta (https://oddspapi.io). La API
v4 usa ``apiKey`` como parámetro. Para no agotar el cupo:

* catálogos (mercados, participantes, torneos) se guardan en caché 7 días;
* las cuotas se piden por lotes de torneos y como máximo cada
  ``ODDSPAPI_MIN_HOURS`` horas (por defecto 8 → ~200 peticiones/mes).

Documentación: https://oddspapi.io/docs (odds-by-tournaments, markets,
participants, tournaments).
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

from ..config import DATA_DIR, get_settings
from .base import ProviderEvent, ProviderNotConfigured, ProviderQuote, http_get_json

log = logging.getLogger(__name__)
CACHE = DATA_DIR / "raw" / "oddspapi"
BASE = "https://api.oddspapi.io/v4"
FOOTBALL = 10

# Casas colombianas disponibles en OddsPapi → clave interna. Pinnacle viaja en la misma
# petición (no gasta cupo) como referencia para detectar cuotas retrasadas.
BOOKMAKERS = {"betplay": "betplay", "rushbet-co": "rushbet", "pinnacle": "pinnacle"}

# Torneos de interés (nombre de categoría, nombre de torneo) en minúsculas
WANTED = [
    ("colombia", "primera a"), ("colombia", "liga betplay"), ("colombia", "primera b"), ("colombia", "copa colombia"),
    ("england", "premier league"), ("england", "championship"), ("spain", "laliga"), ("spain", "laliga 2"),
    ("italy", "serie a"), ("italy", "serie b"), ("germany", "bundesliga"), ("germany", "2. bundesliga"),
    ("france", "ligue 1"), ("france", "ligue 2"), ("netherlands", "eredivisie"), ("portugal", "liga portugal"),
    ("belgium", "pro league"), ("turkey", "super lig"), ("scotland", "premiership"), ("argentina", "liga profesional"),
    ("brazil", "brasileiro serie a"), ("mexico", "liga mx"), ("usa", "mls"),
    ("international clubs", "uefa champions league"), ("international clubs", "uefa europa league"),
    ("international clubs", "copa libertadores"), ("international clubs", "copa sudamericana"),
]


def _cached(name: str, max_age_days: float, fetch):
    path = CACHE / name
    if path.exists() and time.time() - path.stat().st_mtime < max_age_days * 86400:
        return json.loads(path.read_text())
    data = fetch()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))
    return data


def map_market(m: dict, outcome_id: int) -> tuple[str, str, float | None] | None:
    """Convierte (mercado, resultado) de OddsPapi al catálogo interno."""
    if m.get("period") not in ("fulltime", "full time", None) or m.get("playerProp"):
        return None
    name = str(m.get("marketName", "")).lower()
    outs = {o["outcomeId"]: str(o["outcomeName"]).lower() for o in m.get("outcomes", [])}
    out = outs.get(outcome_id)
    if out is None:
        return None
    h = m.get("handicap")
    if name in ("full time result", "1x2", "match result"):
        return {"1": ("1x2", "home", None), "x": ("1x2", "draw", None), "2": ("1x2", "away", None)}.get(out)
    if "both teams to score" in name:
        return ("btts", "yes", None) if out == "yes" else ("btts", "no", None) if out == "no" else None
    if "double chance" in name:
        sel = {"1x": "1X", "x2": "X2", "12": "12", "1 or x": "1X", "x or 2": "X2", "1 or 2": "12"}.get(out.replace(" ", "") if len(out) <= 3 else out)
        return ("double_chance", sel, None) if sel else None
    if "draw no bet" in name:
        return {"1": ("dnb", "home", None), "2": ("dnb", "away", None)}.get(out)
    if name.startswith("over under") and "team" not in name and "corner" not in name and "card" not in name and h is not None:
        return {"over": ("total_goals", "over", float(h)), "under": ("total_goals", "under", float(h))}.get(out)
    # El hándicap asiático no se importa: la documentación no precisa a qué equipo
    # se refiere la línea y un signo equivocado invertiría el valor esperado.
    return None


class OddsPapi:
    name = "oddspapi"

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or get_settings().oddspapi_key

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def _get(self, path: str, **params):
        if not self.api_key:
            raise ProviderNotConfigured("ODDSPAPI_KEY no configurada")
        with httpx.Client(timeout=40) as c:
            data = http_get_json(c, f"{BASE}{path}", params={**params, "apiKey": self.api_key})
        time.sleep(1.1)  # cooldown documentado de 1000 ms por endpoint
        return data

    def markets(self) -> dict[int, dict]:
        rows = _cached("markets.json", 7, lambda: self._get("/markets", language="en"))
        return {int(m["marketId"]): m for m in rows if m.get("sportId") == FOOTBALL}

    def participants(self) -> dict[str, str]:
        return _cached("participants_10.json", 7, lambda: self._get("/participants", sportId=FOOTBALL))

    def tournaments(self) -> list[dict]:
        return _cached("tournaments_10.json", 3, lambda: self._get("/tournaments", sportId=FOOTBALL))

    def wanted_tournaments(self) -> list[dict]:
        out = []
        for t in self.tournaments():
            cat, name = str(t.get("categoryName", "")).lower(), str(t.get("tournamentName", "")).lower()
            if any(cat == c and name == n for c, n in WANTED) and (t.get("futureFixtures") or t.get("upcomingFixtures")):
                out.append(t)
        return out

    def odds(self, chunk: int = 12) -> tuple[list[ProviderEvent], list[ProviderQuote], dict]:
        markets = self.markets()
        names = self.participants()
        tours = self.wanted_tournaments()
        tname = {t["tournamentId"]: (t["tournamentName"], t.get("categoryName")) for t in tours}
        events: list[ProviderEvent] = []
        quotes: list[ProviderQuote] = []
        requests = 0
        for i in range(0, len(tours), chunk):
            ids = ",".join(str(t["tournamentId"]) for t in tours[i:i + chunk])
            data = self._get("/odds-by-tournaments", tournamentIds=ids, bookmakers=",".join(BOOKMAKERS))
            requests += 1
            for fx in data if isinstance(data, list) else data.get("data", []):
                if fx.get("statusId") not in (0, None):
                    continue
                home = names.get(str(fx.get("participant1Id")))
                away = names.get(str(fx.get("participant2Id")))
                if not home or not away or not fx.get("startTime"):
                    continue
                comp, country = tname.get(fx.get("tournamentId"), (None, None))
                ext = str(fx["fixtureId"])
                events.append(ProviderEvent(self.name, ext, "football", home, away,
                                            datetime.fromisoformat(fx["startTime"].replace("Z", "+00:00")),
                                            competition=comp, country=country))
                for slug, books in (fx.get("bookmakerOdds") or {}).items():
                    op = BOOKMAKERS.get(slug)
                    if not op or not books.get("bookmakerIsActive", True) or books.get("suspended"):
                        continue
                    for mid, mk in (books.get("markets") or {}).items():
                        meta = markets.get(int(mid))
                        if not meta:
                            continue
                        for oid, oc in (mk.get("outcomes") or {}).items():
                            p = (oc.get("players") or {}).get("0") or {}
                            price = p.get("price")
                            mapped = map_market(meta, int(oid))
                            if not mapped or not price or price <= 1 or not p.get("active", True):
                                continue
                            market, sel, line = mapped
                            ts = p.get("changedAt") or p.get("bookmakerChangedAt")
                            quotes.append(ProviderQuote(self.name, ext, op, market, sel, float(price), line=line,
                                                        provider_ts=datetime.fromisoformat(ts.replace("Z", "+00:00")) if ts else None))
        return events, quotes, {"requests": requests, "tournaments": len(tours)}


def due(last_ok: datetime | None) -> bool:
    hours = get_settings().oddspapi_min_hours
    return last_ok is None or (datetime.now(timezone.utc) - last_ok).total_seconds() >= hours * 3600


def cache_dir() -> Path:
    return CACHE
