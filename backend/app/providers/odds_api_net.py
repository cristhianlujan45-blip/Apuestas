"""odds-api.net — cuotas de casas colombianas (proveedor con licencia de datos).

Es el único agregador evaluado que publica cobertura de los 14 operadores del
listado vigente de Coljuegos (betplay, wplay, betsson, zamba, codere, luckia,
sportiumco, rushbet, rivalo, yajuego, bwin, stakeco, betano, mryoker) además
de Pinnacle como referencia. La plataforma NO extrae datos de las webs de los
operadores: solo consume este feed autorizado.

Documentación: https://odds-api.net/docs (REST con cabecera X-API-Key, SSE y
WebSocket para deltas).
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone

import httpx

from ..config import get_settings
from .base import ProviderEvent, ProviderNotConfigured, ProviderQuote, http_get_json

log = logging.getLogger(__name__)

SPORT_MAP = {"soccer": "football", "football": "football", "basketball": "basketball", "tennis": "tennis",
             "baseball": "baseball", "volleyball": "volleyball"}
API_SPORTS = {"football": "soccer", "basketball": "basketball", "tennis": "tennis", "baseball": "baseball",
              "volleyball": "volleyball"}

STAT_METRICS = {"corners": "corners", "corner": "corners", "cards": "cards", "bookings": "cards",
                "shots": "shots", "shots on target": "shots_on_target", "shots_on_target": "shots_on_target"}
PLAYER_METRICS = {"points": "points", "rebounds": "rebounds", "assists": "assists", "threes": "threes",
                  "3 point field goals": "threes", "three pointers": "threes"}


def _float(v) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        m = re.search(r"-?\d+(\.\d+)?", str(v))
        return float(m.group()) if m else None


def map_market(sport: str, item: dict) -> tuple[str, str, float | None, str | None] | None:
    """Traduce una línea del feed al catálogo interno (mercado, selección, línea, jugador)."""
    bet = f"{item.get('bet_type') or ''} {item.get('market_key') or ''}".lower()
    side = str(item.get("side") or item.get("selection_name") or "").lower().strip()
    metric = str(item.get("metric") or "").lower()
    player = item.get("player_name") or None
    line = _float(item.get("line", item.get("hdp", item.get("points"))))
    team_subject = str(item.get("team_subject") or "").lower()
    if side in ("1", "local"):
        side = "home"
    elif side in ("2", "visitante"):
        side = "away"
    elif side in ("x", "tie", "empate"):
        side = "draw"

    if player:
        stat = PLAYER_METRICS.get(metric) or next((v for k, v in PLAYER_METRICS.items() if k in bet), None)
        if sport == "basketball" and stat and side in ("over", "under") and line is not None:
            return f"player_{stat}", side, line, player
        return None
    if "double" in bet and "chance" in bet:
        sel = {"home_draw": "1X", "1x": "1X", "draw_away": "X2", "x2": "X2", "home_away": "12", "12": "12"}.get(
            side.replace(" ", "_").replace("/", "_").replace("or", "").strip("_"), None)
        return ("double_chance", sel, None, None) if sel else None
    if "draw no bet" in bet or "dnb" in bet:
        return ("dnb", side, None, None) if side in ("home", "away") else None
    if "both" in bet and "score" in bet or "btts" in bet:
        return ("btts", side, None, None) if side in ("yes", "no") else None
    if "correct" in bet and "score" in bet:
        m = re.match(r"(\d+)\s*[-:]\s*(\d+)", side)
        return ("correct_score", f"{m.group(1)}-{m.group(2)}", None, None) if m else None
    if "moneyline" in bet or bet.strip() in ("1x2", "h2h", "winner", "match winner"):
        if sport == "football":
            return ("1x2", side, None, None) if side in ("home", "draw", "away") else None
        return ("moneyline", side, None, None) if side in ("home", "away") else None
    stat = STAT_METRICS.get(metric) or next((v for k, v in STAT_METRICS.items() if k in bet), None)
    if "spread" in bet or "handicap" in bet:
        if line is None or side not in ("home", "away", "draw"):
            return None
        if sport == "football":
            if "european" in bet or "3w" in bet or side == "draw":
                return "european_handicap", side, line, None
            return "asian_handicap", side, line, None
        if sport == "tennis":
            return ("games_handicap" if metric in ("", "games") else "set_handicap"), side, line, None
        if sport == "volleyball":
            return "set_handicap", side, line, None
        return "spread", side, line, None
    if "total" in bet or side in ("over", "under"):
        if line is None or side not in ("over", "under"):
            return None
        if team_subject in ("home", "away"):
            if sport == "football" and not stat:
                return f"team_total_{team_subject}", side, line, None
            if sport == "basketball":
                return f"team_points_{team_subject}", side, line, None
            if stat == "corners":
                return f"corners_{team_subject}", side, line, None
            return None
        if sport == "football":
            if stat:
                return {"corners": "corners_total", "cards": "cards_total", "shots": "shots_total",
                        "shots_on_target": "shots_on_target_total"}[stat], side, line, None
            return "total_goals", side, line, None
        return {"basketball": "total_points", "tennis": "total_games", "baseball": "total_runs",
                "volleyball": "total_points"}.get(sport, "total_points"), side, line, None
    return None


def _period(item: dict) -> str | None:
    p = str(item.get("period", "full time")).lower()
    if p in ("full time", "0", "ft", "match", "full_time", "regular time"):
        return "ft"
    return None  # otros periodos no se modelan todavía


class OddsApiNet:
    name = "odds_api_net"

    def __init__(self, api_key: str | None = None, base_url: str | None = None):
        s = get_settings()
        self.api_key = api_key or s.odds_api_net_key
        self.base_url = (base_url or s.odds_api_net_base_url).rstrip("/")

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def _client(self) -> httpx.Client:
        if not self.api_key:
            raise ProviderNotConfigured("ODDS_API_NET_KEY no configurada")
        return httpx.Client(timeout=30, headers={"X-API-Key": self.api_key})

    def status(self) -> dict:
        with httpx.Client(timeout=15) as c:
            return http_get_json(c, f"{self.base_url}/status")  # type: ignore[return-value]

    def bookmakers(self, country_code: str = "CO") -> list[dict]:
        with self._client() as c:
            data = http_get_json(c, f"{self.base_url}/bookmakers", params={"country_code": country_code})
        return data.get("items", [])  # type: ignore[union-attr]

    def usage(self) -> dict:
        with self._client() as c:
            return http_get_json(c, f"{self.base_url}/usage")  # type: ignore[return-value]

    def events(self, sport: str, hours_ahead: int = 72, league: str | None = None, live: bool = False,
               limit: int = 100) -> list[ProviderEvent]:
        api_sport = API_SPORTS.get(sport, sport)
        now = datetime.now(timezone.utc)
        params: dict = {"sport": api_sport, "limit": limit}
        if league:
            params["league"] = league
        if live:
            path = "/events/live"
        else:
            path = "/events"
            params.update({"start_from": int(now.timestamp()), "start_to": int((now + timedelta(hours=hours_ahead)).timestamp()),
                           "not_started_only": "true"})
        out: list[ProviderEvent] = []
        with self._client() as c:
            cursor = None
            for _ in range(20):
                if cursor:
                    params["cursor"] = cursor
                data = http_get_json(c, f"{self.base_url}{path}", params=params)
                for it in data.get("items", []):  # type: ignore[union-attr]
                    st = it.get("start_time")
                    if not st:
                        continue
                    out.append(ProviderEvent(
                        provider=self.name, external_id=str(it["event_id"]),
                        sport=SPORT_MAP.get(str(it.get("sport", api_sport)).lower(), sport),
                        home=it.get("home_team", ""), away=it.get("away_team", ""),
                        start_time=datetime.fromtimestamp(int(st), tz=timezone.utc),
                        competition=it.get("league"),
                        status="live" if live or it.get("live_status") in ("live", "in_play") else "scheduled",
                        extra={"event_state": it.get("event_state"), "bookmakers": list((it.get("bookmakers") or {}).keys())},
                    ))
                cursor = data.get("next_cursor")  # type: ignore[union-attr]
                if not cursor:
                    break
        return out

    def odds(self, event: ProviderEvent, bookmakers: list[str]) -> tuple[list[ProviderQuote], dict]:
        """Snapshot de cuotas de un evento para los operadores indicados."""
        params = {"bookmakers": ",".join(bookmakers), "price_fields": "odds", "include_unavailable": "true"}
        with self._client() as c:
            data = http_get_json(c, f"{self.base_url}/events/{event.external_id}/odds/snapshot", params=params)
        quotes: list[ProviderQuote] = []
        unmapped: dict[str, int] = {}
        per_book_ts = data.get("bookmaker_as_of_ts_ms") or {}  # type: ignore[union-attr]
        for it in data.get("items", []):  # type: ignore[union-attr]
            period = _period(it)
            mapped = map_market(event.sport, it) if period else None
            if not mapped:
                k = f"{it.get('bet_type')}|{it.get('period')}"
                unmapped[k] = unmapped.get(k, 0) + 1
                continue
            market, sel, line, player = mapped
            odds = _float(it.get("odds"))
            if not odds or odds <= 1:
                continue
            ts = per_book_ts.get(it.get("bookmaker")) if isinstance(per_book_ts, dict) else None
            ts = ts or data.get("as_of_ts_ms")  # type: ignore[union-attr]
            quotes.append(ProviderQuote(
                provider=self.name, external_event_id=event.external_id, operator_key=str(it["bookmaker"]),
                market=market, selection=sel, line=line, player=player, period=period or "ft", odds=odds,
                available=bool(it.get("is_available", True)), is_live=event.status == "live",
                provider_ts=datetime.fromtimestamp(ts / 1000, tz=timezone.utc) if ts else None,
            ))
        meta = {"unmapped": unmapped, "stale_bookmakers": data.get("stale_bookmakers", []),  # type: ignore[union-attr]
                "excluded_bookmakers": data.get("excluded_bookmakers", [])}  # type: ignore[union-attr]
        return quotes, meta
