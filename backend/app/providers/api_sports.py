"""API-Sports (API-Football y API-Basketball): partidos, directo, estadísticas y alineaciones.

Una misma cuenta de api-sports.io sirve para todas sus APIs (cabecera
``x-apisports-key``). El plan gratuito permite 100 peticiones/día por API,
por lo que la ingesta prioriza: partidos del día → directo → estadísticas.

Incluye la Liga BetPlay (Colombia, liga 239) y la Copa Colombia (liga 241).
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone

import httpx

from ..config import get_settings
from .base import ProviderEvent, ProviderNotConfigured, ProviderStats, http_get_json

log = logging.getLogger(__name__)

COLOMBIA_LEAGUES = {239: "Primera A (Liga BetPlay)", 240: "Primera B (Torneo BetPlay)", 241: "Copa Colombia"}

STATUS = {"NS": "scheduled", "TBD": "scheduled", "1H": "live", "HT": "live", "2H": "live", "ET": "live",
          "BT": "live", "P": "live", "LIVE": "live", "INT": "live", "FT": "finished", "AET": "finished",
          "PEN": "finished", "PST": "postponed", "CANC": "cancelled", "ABD": "cancelled", "AWD": "finished",
          "WO": "finished", "SUSP": "postponed", "Q1": "live", "Q2": "live", "Q3": "live", "Q4": "live",
          "OT": "live", "AOT": "finished"}

STAT_KEYS = {
    "Shots on Goal": "sot", "Total Shots": "shots", "Corner Kicks": "corners", "Yellow Cards": "yellow",
    "Red Cards": "red", "Ball Possession": "possession", "expected_goals": "xg", "Fouls": "fouls",
    "Shots insidebox": "shots_inside", "Goalkeeper Saves": "saves", "Total passes": "passes",
}


def _num(v):
    if v is None:
        return None
    if isinstance(v, str):
        v = v.strip().rstrip("%")
        try:
            return float(v)
        except ValueError:
            return None
    return float(v)


class ApiFootball:
    name = "api_football"

    def __init__(self, api_key: str | None = None, base_url: str | None = None):
        s = get_settings()
        self.api_key = api_key or s.api_football_key
        self.base_url = (base_url or s.api_football_base_url).rstrip("/")

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def _client(self) -> httpx.Client:
        if not self.api_key:
            raise ProviderNotConfigured("API_FOOTBALL_KEY no configurada")
        return httpx.Client(timeout=30, headers={"x-apisports-key": self.api_key})

    def _get(self, path: str, **params) -> list[dict]:
        with self._client() as c:
            data = http_get_json(c, f"{self.base_url}{path}", params=params)
        if data.get("errors"):  # type: ignore[union-attr]
            log.warning("API-Football %s: %s", path, data["errors"])  # type: ignore[index]
        return data.get("response", [])  # type: ignore[union-attr]

    @staticmethod
    def _event(r: dict) -> ProviderEvent:
        fx, lg, tm, gl = r["fixture"], r["league"], r["teams"], r.get("goals") or {}
        return ProviderEvent(
            provider="api_football", external_id=str(fx["id"]), sport="football",
            home=tm["home"]["name"], away=tm["away"]["name"],
            start_time=datetime.fromisoformat(fx["date"]).astimezone(timezone.utc),
            competition=lg.get("name"), country=lg.get("country"),
            status=STATUS.get(fx["status"]["short"], "scheduled"),
            home_score=gl.get("home"), away_score=gl.get("away"), minute=fx["status"].get("elapsed"),
            extra={"league_id": lg.get("id"), "season": lg.get("season"), "venue": (fx.get("venue") or {}).get("name"),
                   "referee": fx.get("referee"), "status_short": fx["status"]["short"],
                   "home_id": tm["home"]["id"], "away_id": tm["away"]["id"]},
        )

    def fixtures_by_date(self, day: date, tz: str = "America/Bogota") -> list[ProviderEvent]:
        return [self._event(r) for r in self._get("/fixtures", date=day.isoformat(), timezone=tz)]

    def live(self) -> list[ProviderEvent]:
        return [self._event(r) for r in self._get("/fixtures", live="all")]

    def league_season(self, league_id: int, season: int) -> list[ProviderEvent]:
        return [self._event(r) for r in self._get("/fixtures", league=league_id, season=season)]

    def statistics(self, fixture_id: str, minute: int | None = None, final: bool = False) -> ProviderStats:
        rows = self._get("/fixtures/statistics", fixture=fixture_id)
        stats: dict = {}
        for side, r in zip(("home", "away"), rows):
            for s in r.get("statistics", []):
                key = STAT_KEYS.get(s["type"])
                if key:
                    stats[f"{side}_{key}"] = _num(s.get("value"))
        return ProviderStats("api_football", fixture_id, minute, final, stats)

    def lineups(self, fixture_id: str) -> list[dict]:
        out = []
        for r in self._get("/fixtures/lineups", fixture=fixture_id):
            out.append({"team": r["team"]["name"], "formation": r.get("formation"),
                        "start_xi": [p["player"]["name"] for p in r.get("startXI", [])],
                        "substitutes": [p["player"]["name"] for p in r.get("substitutes", [])],
                        "coach": (r.get("coach") or {}).get("name")})
        return out

    def events(self, fixture_id: str) -> list[dict]:
        """Goles, tarjetas y sustituciones."""
        out = []
        for r in self._get("/fixtures/events", fixture=fixture_id):
            out.append({"minute": (r.get("time") or {}).get("elapsed"), "team": (r.get("team") or {}).get("name"),
                        "type": r.get("type"), "detail": r.get("detail"),
                        "player": (r.get("player") or {}).get("name")})
        return out

    def status(self) -> dict:
        with self._client() as c:
            return http_get_json(c, f"{self.base_url}/status")  # type: ignore[return-value]


class ApiBasketball:
    name = "api_basketball"

    def __init__(self, api_key: str | None = None, base_url: str | None = None):
        s = get_settings()
        self.api_key = api_key or s.api_basketball_key or s.api_football_key
        self.base_url = (base_url or s.api_basketball_base_url).rstrip("/")

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def _get(self, path: str, **params) -> list[dict]:
        if not self.api_key:
            raise ProviderNotConfigured("API_BASKETBALL_KEY no configurada")
        with httpx.Client(timeout=30, headers={"x-apisports-key": self.api_key}) as c:
            data = http_get_json(c, f"{self.base_url}{path}", params=params)
        return data.get("response", [])  # type: ignore[union-attr]

    def games(self, **params) -> list[ProviderEvent]:
        out = []
        for g in self._get("/games", **params):
            sc = g.get("scores") or {}
            out.append(ProviderEvent(
                provider=self.name, external_id=str(g["id"]), sport="basketball",
                home=g["teams"]["home"]["name"], away=g["teams"]["away"]["name"],
                start_time=datetime.fromisoformat(g["date"]).astimezone(timezone.utc),
                competition=(g.get("league") or {}).get("name"), country=(g.get("country") or {}).get("name"),
                status=STATUS.get((g.get("status") or {}).get("short", "NS"), "scheduled"),
                home_score=(sc.get("home") or {}).get("total"), away_score=(sc.get("away") or {}).get("total"),
                extra={"league_id": (g.get("league") or {}).get("id"), "season": (g.get("league") or {}).get("season")},
            ))
        return out

    def team_statistics(self, game_id: str) -> list[dict]:
        return self._get("/games/statistics/teams", id=game_id)
