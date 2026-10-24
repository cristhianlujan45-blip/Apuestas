"""Configuración central de la plataforma.

Todas las claves externas son opcionales: si una integración no tiene clave,
el módulo correspondiente se desactiva y la API lo informa explícitamente
(nunca se sustituyen datos reales por datos inventados).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT_DIR / "data"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(ROOT_DIR / ".env", ROOT_DIR / "backend" / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Apuestas Intel CO"
    environment: str = "development"
    timezone: str = "America/Bogota"

    # Base de datos y caché
    database_url: str = f"sqlite:///{DATA_DIR / 'apuestas.db'}"
    redis_url: str | None = None

    # Seguridad
    jwt_secret: str = Field(default="dev-only-change-me", min_length=8)
    jwt_expire_minutes: int = 60 * 12
    cors_origins: str = "http://localhost:3000"
    min_age: int = 18

    # Proveedores de cuotas
    odds_api_net_key: str | None = None
    odds_api_net_base_url: str = "https://api.odds-api.net/v1"
    the_odds_api_key: str | None = None
    the_odds_api_base_url: str = "https://api.the-odds-api.com/v4"

    # Proveedores de estadísticas
    api_football_key: str | None = None
    api_football_base_url: str = "https://v3.football.api-sports.io"
    api_basketball_key: str | None = None
    api_basketball_base_url: str = "https://v1.basketball.api-sports.io"
    football_data_org_key: str | None = None
    football_data_uk_base_url: str = "https://www.football-data.co.uk"
    statsbomb_open_data_url: str = "https://raw.githubusercontent.com/statsbomb/open-data/master/data"

    # Asistente (opcional). El LLM solo enruta a herramientas y redacta;
    # nunca genera probabilidades.
    anthropic_api_key: str | None = None
    assistant_model: str = "claude-opus-5-5"

    # Motor
    monte_carlo_samples: int = 20000
    odds_stale_after_seconds: int = 900
    live_odds_stale_after_seconds: int = 60
    live_poll_seconds: int = 30
    prematch_poll_seconds: int = 600

    # Ligas de football-data.co.uk usadas para entrenamiento histórico
    football_data_leagues: str = "E0,E1,SP1,I1,D1,F1,N1,P1,B1,T1,SC0"
    football_data_extra_leagues: str = "ARG,BRA,MEX,USA"
    football_data_seasons: str = "2223,2324,2425,2526,2627"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


@lru_cache
def get_settings() -> Settings:
    return Settings()
