"""Directo: difusión por WebSocket de probabilidades y cuotas actualizadas.

El ``worker`` ingiere datos en directo de los proveedores y escribe en la
base de datos; si hay Redis publica un aviso en el canal ``live`` para que la
API recalcule al instante. Sin Redis, el hub sondea la base de datos.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone

from fastapi import WebSocket
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from ..config import get_settings
from ..db import SessionLocal
from ..models import Event
from .events import event_dict
from .odds import compare_event
from .predictions import model_event

log = logging.getLogger(__name__)


class LiveHub:
    def __init__(self) -> None:
        self.clients: set[WebSocket] = set()
        self.last: dict[int, str] = {}
        self._task: asyncio.Task | None = None
        self._wake = asyncio.Event()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self.clients.add(ws)
        await ws.send_text(json.dumps({"type": "snapshot", "events": self.snapshot()}, default=str))

    def disconnect(self, ws: WebSocket) -> None:
        self.clients.discard(ws)

    def snapshot(self) -> list[dict]:
        db = SessionLocal()
        try:
            evs = db.scalars(select(Event).where(Event.status == "live")
                             .options(joinedload(Event.home), joinedload(Event.away), joinedload(Event.competition))).unique().all()
            out = []
            for ev in evs:
                em = model_event(db, ev, n_draws=0)
                d = event_dict(ev)
                d["live_model"] = em.summary.get("live")
                d["prematch_probs"] = em.summary.get("probs")
                d["model_note"] = em.reason
                cmp = compare_event(db, ev)
                d["best_odds"] = [{"selection": r["label"], **(r["best"] or {})} for r in cmp["rows"] if r["best"]][:12]
                out.append(d)
            return out
        finally:
            db.close()

    async def broadcast(self, payload: dict) -> None:
        dead = []
        msg = json.dumps(payload, default=str)
        for ws in list(self.clients):
            try:
                await ws.send_text(msg)
            except Exception:  # noqa: BLE001
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

    async def run(self) -> None:
        s = get_settings()
        asyncio.create_task(self._redis_listener())
        while True:
            try:
                if self.clients:
                    events = await asyncio.to_thread(self.snapshot)
                    changed = []
                    for e in events:
                        sig = json.dumps([e.get("home_score"), e.get("away_score"), e.get("minute"),
                                          e.get("live_model"), e.get("best_odds")], default=str, sort_keys=True)
                        if self.last.get(e["id"]) != sig:
                            self.last[e["id"]] = sig
                            changed.append(e)
                    if changed:
                        await self.broadcast({"type": "update", "at": datetime.now(timezone.utc).isoformat(),
                                              "events": changed})
            except Exception as exc:  # noqa: BLE001
                log.warning("LiveHub: %s", exc)
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=max(5, s.live_poll_seconds // 2))
            except asyncio.TimeoutError:
                pass
            self._wake.clear()

    async def _redis_listener(self) -> None:
        url = get_settings().redis_url
        if not url:
            return
        try:
            import redis.asyncio as aioredis

            r = aioredis.from_url(url)
            ps = r.pubsub()
            await ps.subscribe("live")
            async for msg in ps.listen():
                if msg.get("type") == "message":
                    self._wake.set()
        except Exception as exc:  # noqa: BLE001
            log.warning("Redis no disponible para directo: %s", exc)

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self.run())


hub = LiveHub()


def notify_live_update() -> None:
    """Llamado por el worker tras ingerir datos en directo."""
    url = get_settings().redis_url
    if not url:
        return
    try:
        import redis

        redis.from_url(url).publish("live", "refresh")
    except Exception as exc:  # noqa: BLE001
        log.warning("No se pudo publicar en Redis: %s", exc)
