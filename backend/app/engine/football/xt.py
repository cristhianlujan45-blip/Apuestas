"""Expected Threat (xT, Singh 2018) y Expected Assists (xA) con datos de eventos.

Usa los datos abiertos de StatsBomb (licencia de uso no comercial con
atribución: https://github.com/statsbomb/open-data). El xT se estima por
iteración de valor sobre una rejilla del campo; el xA se calcula sumando el
xG de los tiros generados por cada pase clave.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import httpx
import numpy as np

from ...config import DATA_DIR, get_settings

log = logging.getLogger(__name__)
CACHE = DATA_DIR / "raw" / "statsbomb"
PITCH_X, PITCH_Y = 120.0, 80.0


def _fetch_json(path: str) -> object:
    cache = CACHE / path
    if cache.exists():
        return json.loads(cache.read_text())
    url = f"{get_settings().statsbomb_open_data_url}/{path}"
    with httpx.Client(timeout=60, follow_redirects=True) as c:
        r = c.get(url)
        r.raise_for_status()
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(r.text)
    return r.json()


def competitions() -> list[dict]:
    return _fetch_json("competitions.json")  # type: ignore[return-value]


def matches(competition_id: int, season_id: int) -> list[dict]:
    return _fetch_json(f"matches/{competition_id}/{season_id}.json")  # type: ignore[return-value]


def events(match_id: int) -> list[dict]:
    return _fetch_json(f"events/{match_id}.json")  # type: ignore[return-value]


@dataclass
class XTModel:
    nx: int = 16
    ny: int = 12
    grid: np.ndarray | None = None
    shot_prob: np.ndarray | None = None
    goal_prob: np.ndarray | None = None
    n_events: int = 0

    def _cell(self, x: float, y: float) -> tuple[int, int]:
        i = min(int(x / PITCH_X * self.nx), self.nx - 1)
        j = min(int(y / PITCH_Y * self.ny), self.ny - 1)
        return max(i, 0), max(j, 0)

    def fit(self, event_lists: list[list[dict]], iterations: int = 30) -> "XTModel":
        nx, ny = self.nx, self.ny
        shots = np.zeros((nx, ny))
        goals = np.zeros((nx, ny))
        moves = np.zeros((nx, ny))
        trans = np.zeros((nx, ny, nx, ny))
        for evs in event_lists:
            for e in evs:
                t = e.get("type", {}).get("name")
                loc = e.get("location")
                if not loc:
                    continue
                i, j = self._cell(*loc[:2])
                if t == "Shot":
                    shots[i, j] += 1
                    if e.get("shot", {}).get("outcome", {}).get("name") == "Goal":
                        goals[i, j] += 1
                elif t in ("Pass", "Carry"):
                    moves[i, j] += 1
                    end = (e.get("pass") or e.get("carry") or {}).get("end_location")
                    failed = t == "Pass" and e.get("pass", {}).get("outcome") is not None
                    if end and not failed:
                        k, l = self._cell(*end[:2])
                        trans[i, j, k, l] += 1
                self.n_events += 1
        total = shots + moves
        with np.errstate(divide="ignore", invalid="ignore"):
            s = np.where(total > 0, shots / total, 0)
            m = np.where(total > 0, moves / total, 0)
            g = np.where(shots > 0, goals / shots, 0)
            T = np.where(moves[:, :, None, None] > 0, trans / moves[:, :, None, None], 0)
        xt = np.zeros((nx, ny))
        for _ in range(iterations):
            xt = s * g + m * np.einsum("ijkl,kl->ij", T, xt)
        self.grid, self.shot_prob, self.goal_prob = xt, s, g
        return self

    def value(self, x: float, y: float) -> float:
        i, j = self._cell(x, y)
        return float(self.grid[i, j])

    def action_value(self, start: list[float], end: list[float]) -> float:
        return self.value(*end[:2]) - self.value(*start[:2])


def player_xa_xt(event_lists: list[list[dict]], xt: XTModel) -> list[dict]:
    """xA y xT añadido por jugador."""
    shot_xg: dict[str, float] = {}
    stats: dict[str, dict] = defaultdict(lambda: {"xa": 0.0, "xt_added": 0.0, "key_passes": 0, "team": None,
                                                  "xg": 0.0, "shots": 0})
    for evs in event_lists:
        for e in evs:
            if e.get("type", {}).get("name") == "Shot":
                shot_xg[e["id"]] = float(e.get("shot", {}).get("statsbomb_xg") or 0.0)
        for e in evs:
            t = e.get("type", {}).get("name")
            player = (e.get("player") or {}).get("name")
            if not player:
                continue
            st = stats[player]
            st["team"] = (e.get("team") or {}).get("name")
            if t == "Shot":
                st["xg"] += shot_xg.get(e["id"], 0.0)
                st["shots"] += 1
            if t == "Pass":
                p = e.get("pass", {})
                if p.get("assisted_shot_id"):
                    st["xa"] += shot_xg.get(p["assisted_shot_id"], 0.0)
                    st["key_passes"] += 1
                if p.get("outcome") is None and e.get("location") and p.get("end_location"):
                    st["xt_added"] += xt.action_value(e["location"], p["end_location"])
            elif t == "Carry" and e.get("location") and (e.get("carry") or {}).get("end_location"):
                st["xt_added"] += xt.action_value(e["location"], e["carry"]["end_location"])
    rows = [{"player": k, **v} for k, v in stats.items()]
    return sorted(rows, key=lambda r: r["xt_added"] + r["xa"], reverse=True)


def build_from_open_data(competition_id: int, season_id: int, max_matches: int = 30) -> dict:
    ms = matches(competition_id, season_id)[:max_matches]
    evs = [events(m["match_id"]) for m in ms]
    model = XTModel().fit(evs)
    players = player_xa_xt(evs, model)
    return {
        "competition_id": competition_id, "season_id": season_id, "matches": len(ms),
        "events": model.n_events, "grid": model.grid.tolist(), "players": players[:100],
        "source": "StatsBomb Open Data",
    }


def save(result: dict, path: Path | None = None) -> Path:
    path = path or DATA_DIR / "models" / f"xt_{result['competition_id']}_{result['season_id']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result))
    return path
