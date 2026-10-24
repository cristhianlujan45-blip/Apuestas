"""football-data.co.uk: resultados, estadísticas y cuotas históricas (gratuito).

Fuente real usada para entrenar y validar los modelos de fútbol. Incluye
tiros, tiros al arco, córners, faltas, tarjetas y cuotas de casas
internacionales (apertura y cierre). Las cuotas de esta fuente son de casas
NO autorizadas en Colombia: se usan exclusivamente como referencia de
mercado y para backtesting, nunca para recomendar apuestas.

Términos: https://www.football-data.co.uk/ (uso libre citando la fuente).
"""

from __future__ import annotations

import io
import logging
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import pandas as pd

from ..config import DATA_DIR, get_settings

log = logging.getLogger(__name__)

CACHE_DIR = DATA_DIR / "raw" / "football_data"

LEAGUE_NAMES = {
    "E0": ("Premier League", "Inglaterra"), "E1": ("Championship", "Inglaterra"),
    "E2": ("League One", "Inglaterra"), "SC0": ("Premiership", "Escocia"),
    "SP1": ("LaLiga", "España"), "SP2": ("LaLiga 2", "España"), "I1": ("Serie A", "Italia"),
    "I2": ("Serie B", "Italia"), "D1": ("Bundesliga", "Alemania"), "D2": ("2. Bundesliga", "Alemania"),
    "F1": ("Ligue 1", "Francia"), "F2": ("Ligue 2", "Francia"), "N1": ("Eredivisie", "Países Bajos"),
    "B1": ("Pro League", "Bélgica"), "P1": ("Primeira Liga", "Portugal"), "T1": ("Süper Lig", "Turquía"),
    "G1": ("Super League", "Grecia"),
    "ARG": ("Liga Profesional", "Argentina"), "BRA": ("Serie A", "Brasil"), "MEX": ("Liga MX", "México"),
    "USA": ("MLS", "Estados Unidos"), "CHN": ("Super League", "China"), "JPN": ("J1 League", "Japón"),
}

UK_TZ = ZoneInfo("Europe/London")


def _get(url: str, cache: Path | None, max_age_hours: float) -> str:
    if cache is not None and cache.exists() and (time.time() - cache.stat().st_mtime) < max_age_hours * 3600:
        return cache.read_text(encoding="utf-8-sig", errors="replace")
    with httpx.Client(follow_redirects=True, timeout=60) as client:
        r = client.get(url)
        r.raise_for_status()
        text = r.content.decode("utf-8-sig", errors="replace")
    if cache is not None:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(text, encoding="utf-8")
    return text


def _parse_dt(date: str, time_: str | None) -> datetime | None:
    if not isinstance(date, str) or not date:
        return None
    for fmt in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            d = datetime.strptime(date.strip(), fmt)
            break
        except ValueError:
            continue
    else:
        return None
    if isinstance(time_, str) and ":" in time_:
        h, m = time_.strip().split(":")[:2]
        d = d.replace(hour=int(h), minute=int(m))
    else:
        d = d.replace(hour=15)
    return d.replace(tzinfo=UK_TZ).astimezone(ZoneInfo("UTC"))


def _num(df: pd.DataFrame, col: str) -> pd.Series:
    if col in df.columns:
        return pd.to_numeric(df[col], errors="coerce")
    return pd.Series([float("nan")] * len(df), index=df.index)


def _first(df: pd.DataFrame, cols: list[str]) -> pd.Series:
    out = pd.Series([float("nan")] * len(df), index=df.index)
    for c in cols:
        out = out.fillna(_num(df, c))
    return out


def normalize(raw: pd.DataFrame, league: str, season: str | None = None) -> pd.DataFrame:
    """Convierte las columnas de football-data al esquema interno."""
    df = raw.copy()
    df.columns = [c.strip() for c in df.columns]
    if "HomeTeam" not in df.columns and "Home" in df.columns:  # ligas "new"
        df = df.rename(columns={"Home": "HomeTeam", "Away": "AwayTeam", "HG": "FTHG", "AG": "FTAG", "Res": "FTR"})
    df = df.dropna(subset=["HomeTeam", "AwayTeam"])
    out = pd.DataFrame({
        "date": [_parse_dt(d, t) for d, t in zip(df.get("Date"), df.get("Time", [None] * len(df)))],
        "league": league,
        "season": season,
        "home": df["HomeTeam"].astype(str).str.strip(),
        "away": df["AwayTeam"].astype(str).str.strip(),
        "hg": _num(df, "FTHG"), "ag": _num(df, "FTAG"),
        "hthg": _num(df, "HTHG"), "htag": _num(df, "HTAG"),
        "hs": _num(df, "HS"), "as": _num(df, "AS"),
        "hst": _num(df, "HST"), "ast": _num(df, "AST"),
        "hc": _num(df, "HC"), "ac": _num(df, "AC"),
        "hf": _num(df, "HF"), "af": _num(df, "AF"),
        "hy": _num(df, "HY"), "ay": _num(df, "AY"),
        "hr": _num(df, "HR"), "ar": _num(df, "AR"),
        "referee": df["Referee"].astype(str).str.strip() if "Referee" in df.columns else None,
        # Cuotas previas (recogidas antes del cierre) – referencia internacional
        "odds_h": _first(df, ["AvgH", "BbAvH", "B365H", "PSH"]),
        "odds_d": _first(df, ["AvgD", "BbAvD", "B365D", "PSD"]),
        "odds_a": _first(df, ["AvgA", "BbAvA", "B365A", "PSA"]),
        "max_h": _first(df, ["MaxH", "BbMxH"]), "max_d": _first(df, ["MaxD", "BbMxD"]),
        "max_a": _first(df, ["MaxA", "BbMxA"]),
        "ps_h": _num(df, "PSH"), "ps_d": _num(df, "PSD"), "ps_a": _num(df, "PSA"),
        # Cierre
        "close_h": _first(df, ["AvgCH", "PSCH", "B365CH"]),
        "close_d": _first(df, ["AvgCD", "PSCD", "B365CD"]),
        "close_a": _first(df, ["AvgCA", "PSCA", "B365CA"]),
        "psc_h": _num(df, "PSCH"), "psc_d": _num(df, "PSCD"), "psc_a": _num(df, "PSCA"),
        "o25": _first(df, ["Avg>2.5", "BbAv>2.5", "B365>2.5"]),
        "u25": _first(df, ["Avg<2.5", "BbAv<2.5", "B365<2.5"]),
        "ah_line": _first(df, ["AHh", "BbAHh"]),
        "ah_h": _first(df, ["AvgAHH", "BbAvAHH", "B365AHH"]),
        "ah_a": _first(df, ["AvgAHA", "BbAvAHA", "B365AHA"]),
    })
    out["hcards"] = out["hy"] + out["hr"]
    out["acards"] = out["ay"] + out["ar"]
    if season is None and "Season" in df.columns:
        out["season"] = df["Season"].astype(str).values
    out = out.dropna(subset=["date"])
    out["match_id"] = (out["league"] + ":" + out["date"].astype(str) + ":" + out["home"] + ":" + out["away"])
    return out.reset_index(drop=True)


class FootballDataUK:
    name = "football_data_uk"

    def __init__(self, base_url: str | None = None):
        self.base_url = (base_url or get_settings().football_data_uk_base_url).rstrip("/")

    def season(self, league: str, season: str, max_age_hours: float = 12) -> pd.DataFrame:
        url = f"{self.base_url}/mmz4281/{season}/{league}.csv"
        cache = CACHE_DIR / f"{league}_{season}.csv"
        # Temporadas antiguas no cambian: caché larga
        current = season >= "2627"
        text = _get(url, cache, max_age_hours if current else 24 * 365)
        raw = pd.read_csv(io.StringIO(text), on_bad_lines="skip")
        return normalize(raw, league, season)

    def extra_league(self, code: str, max_age_hours: float = 12) -> pd.DataFrame:
        url = f"{self.base_url}/new/{code}.csv"
        text = _get(url, CACHE_DIR / f"new_{code}.csv", max_age_hours)
        raw = pd.read_csv(io.StringIO(text), on_bad_lines="skip")
        return normalize(raw, code)

    def history(self, leagues: list[str], seasons: list[str], extra: list[str] | None = None,
                min_season_extra: int = 2022) -> pd.DataFrame:
        frames = []
        for lg in leagues:
            for s in seasons:
                try:
                    frames.append(self.season(lg, s))
                except httpx.HTTPError as exc:
                    log.warning("football-data %s %s: %s", lg, s, exc)
        for code in extra or []:
            try:
                d = self.extra_league(code)
                frames.append(d[pd.to_datetime(d["date"]).dt.year >= min_season_extra])
            except httpx.HTTPError as exc:
                log.warning("football-data new/%s: %s", code, exc)
        if not frames:
            return pd.DataFrame()
        df = pd.concat(frames, ignore_index=True).sort_values("date")
        return df.drop_duplicates("match_id").reset_index(drop=True)

    def fixtures(self, max_age_hours: float = 3) -> pd.DataFrame:
        """Próximos partidos publicados (ligas principales y extra)."""
        frames = []
        for url, name, multi in (
            (f"{self.base_url}/fixtures.csv", "fixtures.csv", False),
            (f"{self.base_url}/new_league_fixtures.csv", "new_league_fixtures.csv", True),
        ):
            try:
                text = _get(url, CACHE_DIR / name, max_age_hours)
            except httpx.HTTPError as exc:
                log.warning("football-data fixtures %s: %s", url, exc)
                continue
            raw = pd.read_csv(io.StringIO(text), on_bad_lines="skip")
            raw.columns = [c.strip() for c in raw.columns]
            if multi:
                country_to_code = {v[1]: k for k, v in LEAGUE_NAMES.items() if len(k) == 3}
                spanish = {"Argentina": "Argentina", "Brazil": "Brasil", "Mexico": "México", "USA": "Estados Unidos",
                           "China": "China", "Japan": "Japón"}
                for country, grp in raw.groupby("Country"):
                    code = country_to_code.get(spanish.get(country, country))
                    if code:
                        frames.append(normalize(grp, code))
            else:
                for div, grp in raw.groupby("Div"):
                    frames.append(normalize(grp, str(div)))
        if not frames:
            return pd.DataFrame()
        return pd.concat(frames, ignore_index=True).sort_values("date").reset_index(drop=True)
