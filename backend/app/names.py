"""Normalización y emparejamiento de nombres de equipos/jugadores entre proveedores."""

from __future__ import annotations

import json
import re
import unicodedata
from difflib import SequenceMatcher
from functools import lru_cache

from .config import DATA_DIR

STOPWORDS = {"fc", "cf", "sc", "ac", "afc", "cd", "ud", "sd", "rc", "club", "de", "the", "fk", "sk", "bk",
             "cp", "ca", "deportivo", "atletico", "athletic", "calcio", "ssc", "as", "ss", "us", "sv",
             "vfb", "vfl", "tsg", "1", "fsv", "bsc", "rb", "ogc", "losc", "stade", "olympique", "real"}


@lru_cache
def aliases() -> dict[str, str]:
    path = DATA_DIR / "aliases.json"
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {normalize(k): v for k, v in raw.items()}


def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def normalize(name: str) -> str:
    s = strip_accents(name).lower()
    s = s.replace("&", " and ").replace("'", "").replace(".", " ")
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def canonical(name: str) -> str:
    """Nombre canónico (aplica alias conocidos)."""
    n = normalize(name)
    return aliases().get(n, name)


def tokens(name: str) -> set[str]:
    return {t for t in normalize(canonical(name)).split() if t not in STOPWORDS}


def similarity(a: str, b: str) -> float:
    na, nb = normalize(canonical(a)), normalize(canonical(b))
    if na == nb:
        return 1.0
    ta, tb = tokens(a), tokens(b)
    jacc = len(ta & tb) / len(ta | tb) if ta and tb else 0.0
    seq = SequenceMatcher(None, " ".join(sorted(ta)) or na, " ".join(sorted(tb)) or nb).ratio()
    contain = 1.0 if (ta and tb and (ta <= tb or tb <= ta)) else 0.0
    return max(jacc, seq * 0.95, 0.9 * contain)


def best_match(name: str, candidates: list[str], threshold: float = 0.72) -> tuple[str | None, float]:
    best, score = None, 0.0
    for c in candidates:
        s = similarity(name, c)
        if s > score:
            best, score = c, s
    return (best, score) if score >= threshold else (None, score)
