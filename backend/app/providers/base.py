"""Tipos normalizados compartidos por todos los proveedores."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime

import httpx

log = logging.getLogger(__name__)


class ProviderNotConfigured(RuntimeError):
    """Falta la clave o configuración del proveedor."""


class ProviderError(RuntimeError):
    pass


@dataclass
class ProviderEvent:
    provider: str
    external_id: str
    sport: str
    home: str
    away: str
    start_time: datetime
    competition: str | None = None
    country: str | None = None
    status: str = "scheduled"
    home_score: int | None = None
    away_score: int | None = None
    minute: int | None = None
    extra: dict = field(default_factory=dict)


@dataclass
class ProviderQuote:
    provider: str
    external_event_id: str
    operator_key: str
    market: str
    selection: str
    odds: float
    line: float | None = None
    player: str | None = None
    period: str = "ft"
    available: bool = True
    is_live: bool = False
    provider_ts: datetime | None = None


@dataclass
class ProviderStats:
    provider: str
    external_event_id: str
    minute: int | None
    is_final: bool
    stats: dict


def http_get_json(client: httpx.Client, url: str, *, params: dict | None = None, headers: dict | None = None,
                  retries: int = 3) -> dict | list:
    """GET con reintentos exponenciales y respeto de ``Retry-After`` en 429."""
    delay = 2.0
    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            r = client.get(url, params=params, headers=headers)
            if r.status_code == 429:
                wait = float(r.headers.get("Retry-After", delay))
                log.warning("429 de %s, esperando %.1fs", url, wait)
                time.sleep(min(wait, 60))
                delay *= 2
                continue
            if r.status_code >= 500:
                raise ProviderError(f"{r.status_code} {r.text[:200]}")
            if r.status_code >= 400:
                raise ProviderError(f"{r.status_code} {r.text[:300]}")
            return r.json()
        except (httpx.TransportError, ProviderError) as exc:
            last = exc
            if isinstance(exc, ProviderError) and not str(exc).startswith("5"):
                raise
            if attempt < retries:
                time.sleep(delay)
                delay *= 2
    raise ProviderError(str(last))
