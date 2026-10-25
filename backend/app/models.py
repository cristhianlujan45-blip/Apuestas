"""Esquema relacional.

Diseñado para PostgreSQL/TimescaleDB en producción y SQLite en desarrollo.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base

JSONType = JSON().with_variant(JSONB(), "postgresql")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Operator(Base):
    __tablename__ = "operators"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128))
    legal_name: Mapped[str | None] = mapped_column(String(256))
    domains: Mapped[list] = mapped_column(JSONType, default=list)
    contract: Mapped[str | None] = mapped_column(String(32))
    # authorized | not_in_current_list | reference_only | suspended
    status: Mapped[str] = mapped_column(String(32), index=True)
    capabilities: Mapped[dict] = mapped_column(JSONType, default=dict)
    feed_keys: Mapped[dict] = mapped_column(JSONType, default=dict)
    source_url: Mapped[str | None] = mapped_column(String(512))
    verified_at: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    @property
    def is_authorized(self) -> bool:
        return self.status == "authorized"


class Competition(Base):
    __tablename__ = "competitions"
    __table_args__ = (UniqueConstraint("sport", "name", "country"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sport: Mapped[str] = mapped_column(String(32), index=True)
    name: Mapped[str] = mapped_column(String(128))
    country: Mapped[str | None] = mapped_column(String(64))
    external_ids: Mapped[dict] = mapped_column(JSONType, default=dict)


class Participant(Base):
    """Equipo o jugador."""

    __tablename__ = "participants"
    __table_args__ = (UniqueConstraint("sport", "normalized_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sport: Mapped[str] = mapped_column(String(32), index=True)
    name: Mapped[str] = mapped_column(String(128))
    normalized_name: Mapped[str] = mapped_column(String(128), index=True)
    aliases: Mapped[list] = mapped_column(JSONType, default=list)
    external_ids: Mapped[dict] = mapped_column(JSONType, default=dict)


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (
        UniqueConstraint("sport", "home_id", "away_id", "start_time"),
        Index("ix_events_status_start", "status", "start_time"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sport: Mapped[str] = mapped_column(String(32), index=True)
    competition_id: Mapped[int | None] = mapped_column(ForeignKey("competitions.id"))
    home_id: Mapped[int] = mapped_column(ForeignKey("participants.id"))
    away_id: Mapped[int] = mapped_column(ForeignKey("participants.id"))
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    # scheduled | live | finished | postponed | cancelled
    status: Mapped[str] = mapped_column(String(16), default="scheduled")
    home_score: Mapped[int | None] = mapped_column(Integer)
    away_score: Mapped[int | None] = mapped_column(Integer)
    minute: Mapped[int | None] = mapped_column(Integer)
    surface: Mapped[str | None] = mapped_column(String(16))  # tenis
    best_of: Mapped[int | None] = mapped_column(Integer)  # tenis / voleibol
    result_detail: Mapped[dict] = mapped_column(JSONType, default=dict)
    external_ids: Mapped[dict] = mapped_column(JSONType, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    competition: Mapped[Competition | None] = relationship()
    home: Mapped[Participant] = relationship(foreign_keys=[home_id])
    away: Mapped[Participant] = relationship(foreign_keys=[away_id])

    @property
    def label(self) -> str:
        return f"{self.home.name} vs {self.away.name}"


class EventStats(Base):
    """Estadísticas de un evento (finales o capturas en directo)."""

    __tablename__ = "event_stats"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"), index=True)
    provider: Mapped[str] = mapped_column(String(32))
    is_final: Mapped[bool] = mapped_column(Boolean, default=False)
    minute: Mapped[int | None] = mapped_column(Integer)
    stats: Mapped[dict] = mapped_column(JSONType, default=dict)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class OddsQuote(Base):
    """Serie temporal de cuotas. Clave compuesta compatible con hypertables."""

    __tablename__ = "odds_quotes"
    __table_args__ = (
        Index("ix_odds_lookup", "event_id", "market_key", "selection", "line_key", "operator_key"),
    )

    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"), primary_key=True)
    operator_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    market_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    selection: Mapped[str] = mapped_column(String(64), primary_key=True)
    line_key: Mapped[str] = mapped_column(String(16), primary_key=True, default="")
    period: Mapped[str] = mapped_column(String(16), primary_key=True, default="ft")
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    line: Mapped[float | None] = mapped_column(Float)
    odds: Mapped[float] = mapped_column(Float)
    is_available: Mapped[bool] = mapped_column(Boolean, default=True)
    is_live: Mapped[bool] = mapped_column(Boolean, default=False)
    player: Mapped[str | None] = mapped_column(String(128))
    # odds_api_net | the_odds_api | football_data_uk | manual | csv_import
    source: Mapped[str] = mapped_column(String(32))
    provider_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ModelVersion(Base):
    __tablename__ = "model_versions"
    __table_args__ = (UniqueConstraint("name", "version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), index=True)
    sport: Mapped[str] = mapped_column(String(32))
    version: Mapped[str] = mapped_column(String(64))
    params: Mapped[dict] = mapped_column(JSONType, default=dict)
    metrics: Mapped[dict] = mapped_column(JSONType, default=dict)
    trained_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    trained_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # candidate | champion | retired
    status: Mapped[str] = mapped_column(String(16), default="candidate")
    artifact_path: Mapped[str | None] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Prediction(Base):
    """Predicción inmutable. Encadenada por hash para detectar manipulación."""

    __tablename__ = "predictions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"), index=True)
    model_name: Mapped[str] = mapped_column(String(64), index=True)
    model_version: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(16), default="prematch")  # prematch | live | backtest
    minute: Mapped[int | None] = mapped_column(Integer)
    payload: Mapped[dict] = mapped_column(JSONType)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64), unique=True)

    event: Mapped[Event] = relationship()


class ValidationRun(Base):
    __tablename__ = "validation_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    model_name: Mapped[str] = mapped_column(String(64), index=True)
    model_version: Mapped[str] = mapped_column(String(64))
    sport: Mapped[str] = mapped_column(String(32))
    scope: Mapped[str] = mapped_column(String(128))
    period_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    period_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    n: Mapped[int] = mapped_column(Integer)
    metrics: Mapped[dict] = mapped_column(JSONType)
    folds: Mapped[list] = mapped_column(JSONType, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(256), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(128))
    birthdate: Mapped[date] = mapped_column(Date)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    accepted_terms_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class UserLimits(Base):
    __tablename__ = "user_limits"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    daily_stake_cop: Mapped[float | None] = mapped_column(Float)
    weekly_stake_cop: Mapped[float | None] = mapped_column(Float)
    monthly_stake_cop: Mapped[float | None] = mapped_column(Float)
    session_minutes: Mapped[int | None] = mapped_column(Integer)
    self_excluded_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Los aumentos de límite se aplican tras un periodo de enfriamiento.
    pending_changes: Mapped[dict] = mapped_column(JSONType, default=dict)
    pending_effective_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Parlay(Base):
    __tablename__ = "parlays"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    request: Mapped[dict] = mapped_column(JSONType)
    label: Mapped[str] = mapped_column(String(8))
    mode: Mapped[str] = mapped_column(String(16))
    operator_key: Mapped[str] = mapped_column(String(64))
    total_odds: Mapped[float] = mapped_column(Float)
    joint_probability: Mapped[float] = mapped_column(Float)
    expected_value: Mapped[float] = mapped_column(Float)
    legs: Mapped[list] = mapped_column(JSONType)
    validation: Mapped[dict] = mapped_column(JSONType)
    # open | won | lost | void | partial_void
    status: Mapped[str] = mapped_column(String(16), default="open")
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    hash: Mapped[str] = mapped_column(String(64))


class UserBet(Base):
    """Registro manual de apuestas que el usuario colocó por su cuenta.

    La plataforma nunca coloca apuestas; este registro solo alimenta los
    límites personales y el seguimiento de resultados.
    """

    __tablename__ = "user_bets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    parlay_id: Mapped[int | None] = mapped_column(ForeignKey("parlays.id"))
    operator_key: Mapped[str] = mapped_column(String(64))
    description: Mapped[str] = mapped_column(Text)
    stake_cop: Mapped[float] = mapped_column(Float)
    odds: Mapped[float] = mapped_column(Float)
    placed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    result: Mapped[str | None] = mapped_column(String(16))  # won | lost | void
    payout_cop: Mapped[float | None] = mapped_column(Float)


class AgentBet(Base):
    """Apuesta SIMULADA del agente: se registra antes del partido y no se puede cambiar.

    Los campos de la recomendación entran en una cadena de hash; los de liquidación se
    rellenan después. Sirve para medir si el agente gana antes de arriesgar dinero real.
    """

    __tablename__ = "agent_bets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"), index=True)
    selection_key: Mapped[str] = mapped_column(String(128))
    selection_label: Mapped[str] = mapped_column(Text)
    operator_key: Mapped[str] = mapped_column(String(64))
    odds: Mapped[float] = mapped_column(Float)
    p_est: Mapped[float] = mapped_column(Float)
    edge: Mapped[float] = mapped_column(Float)
    stake_cop: Mapped[float] = mapped_column(Float)
    bankroll_before: Mapped[float] = mapped_column(Float)
    policy_version: Mapped[str] = mapped_column(String(64))
    source: Mapped[str] = mapped_column(String(32))
    reason: Mapped[str] = mapped_column(Text)
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64), unique=True)
    # Liquidación
    result: Mapped[str | None] = mapped_column(String(16))  # won | lost | void | half_won | half_lost
    payout_cop: Mapped[float | None] = mapped_column(Float)
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    clv: Mapped[float | None] = mapped_column(Float)

    event: Mapped[Event] = relationship()


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(64), index=True)
    severity: Mapped[str] = mapped_column(String(16))  # info | warning | critical
    message: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict] = mapped_column(JSONType, default=dict)
    acknowledged: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class IngestionLog(Base):
    __tablename__ = "ingestion_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(32), index=True)
    kind: Mapped[str] = mapped_column(String(64))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), default="running")
    count: Mapped[int] = mapped_column(Integer, default=0)
    detail: Mapped[dict] = mapped_column(JSONType, default=dict)
