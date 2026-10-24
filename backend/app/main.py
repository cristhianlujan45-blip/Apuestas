from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from .api.routes import router
from .config import get_settings
from .db import init_db, session_scope
from .services.live import hub
from .services.operators import sync_operators

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    if s.environment == "production" and (s.jwt_secret.startswith("dev-only") or s.jwt_secret.startswith("cambie")):
        raise RuntimeError("Configure JWT_SECRET con un valor aleatorio largo antes de arrancar en producción")
    init_db()
    with session_scope() as db:
        sync_operators(db)
    hub.start()
    yield


settings = get_settings()
app = FastAPI(title=settings.app_name, version="1.0.0", lifespan=lifespan,
              description="Plataforma de inteligencia deportiva, predicciones y PARLAY AI para Colombia")
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origin_list, allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])
app.include_router(router)


@app.websocket("/ws/live")
async def live_ws(ws: WebSocket) -> None:
    await hub.connect(ws)
    try:
        while True:
            await ws.receive_text()  # mantener viva la conexión (ping del cliente)
    except WebSocketDisconnect:
        hub.disconnect(ws)
