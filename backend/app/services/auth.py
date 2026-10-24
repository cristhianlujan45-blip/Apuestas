"""Usuarios, autenticación JWT, mayoría de edad y límites de juego responsable.

La plataforma NO almacena credenciales de casas de apuestas ni mueve dinero.
Las contraseñas de esta plataforma se guardan con bcrypt.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..models import User, UserBet, UserLimits
from .events import aware

COOLING_OFF_HOURS = 24


def age_on(birthdate: date, today: date | None = None) -> int:
    today = today or date.today()
    return today.year - birthdate.year - ((today.month, today.day) < (birthdate.month, birthdate.day))


def hash_password(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()


def check_password(pw: str, hashed: str) -> bool:
    return bcrypt.checkpw(pw.encode(), hashed.encode())


def register(db: Session, email: str, password: str, birthdate: date, accept_terms: bool) -> User:
    s = get_settings()
    if not accept_terms:
        raise ValueError("Debe aceptar los términos y el aviso de juego responsable")
    if age_on(birthdate) < s.min_age:
        raise ValueError(f"Debe ser mayor de {s.min_age} años para usar la plataforma")
    if len(password) < 8:
        raise ValueError("La contraseña debe tener al menos 8 caracteres")
    email = email.strip().lower()
    if db.scalar(select(User).where(User.email == email)):
        raise ValueError("El correo ya está registrado")
    first = db.scalar(select(func.count(User.id))) == 0
    u = User(email=email, password_hash=hash_password(password), birthdate=birthdate, is_admin=first)
    db.add(u)
    db.flush()
    db.add(UserLimits(user_id=u.id))
    db.commit()
    return u


def token_for(u: User) -> str:
    s = get_settings()
    now = datetime.now(timezone.utc)
    return jwt.encode({"sub": str(u.id), "iat": int(now.timestamp()),
                       "exp": int((now + timedelta(minutes=s.jwt_expire_minutes)).timestamp())},
                      s.jwt_secret, algorithm="HS256")


def login(db: Session, email: str, password: str) -> tuple[User, str]:
    u = db.scalar(select(User).where(User.email == email.strip().lower()))
    if u is None or not check_password(password, u.password_hash):
        raise ValueError("Credenciales inválidas")
    return u, token_for(u)


def _decode(request: Request) -> dict | None:
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        return None
    try:
        return jwt.decode(auth[7:], get_settings().jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None


def optional_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    data = _decode(request)
    if not data:
        return None
    u = db.get(User, int(data["sub"]))
    if u is not None:
        request.state.session_started = datetime.fromtimestamp(data["iat"], tz=timezone.utc)
    return u


def current_user(user: User | None = Depends(optional_user)) -> User:
    if user is None:
        raise HTTPException(401, "Inicie sesión")
    return user


def admin_user(user: User = Depends(current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(403, "Requiere administrador")
    return user


# ---------------------------------------------------------------------------
# Límites personales
# ---------------------------------------------------------------------------

LIMIT_FIELDS = ("daily_stake_cop", "weekly_stake_cop", "monthly_stake_cop", "session_minutes")


def get_limits(db: Session, user: User) -> UserLimits:
    lim = db.get(UserLimits, user.id)
    if lim is None:
        lim = UserLimits(user_id=user.id)
        db.add(lim)
        db.flush()
    # Aplicar cambios pendientes cuyo periodo de enfriamiento ya terminó
    if lim.pending_changes and lim.pending_effective_at and aware(lim.pending_effective_at) <= datetime.now(timezone.utc):
        for k, v in lim.pending_changes.items():
            setattr(lim, k, v)
        lim.pending_changes, lim.pending_effective_at = {}, None
        db.commit()
    return lim


def update_limits(db: Session, user: User, changes: dict) -> dict:
    """Las reducciones se aplican al instante; los aumentos o eliminaciones tras 24 h."""
    lim = get_limits(db, user)
    immediate, delayed = {}, {}
    for k in LIMIT_FIELDS:
        if k not in changes:
            continue
        new, cur = changes[k], getattr(lim, k)
        is_stricter = new is not None and (cur is None or new < cur)
        (immediate if is_stricter else delayed)[k] = new
    for k, v in immediate.items():
        setattr(lim, k, v)
    if delayed:
        lim.pending_changes = {**(lim.pending_changes or {}), **delayed}
        lim.pending_effective_at = datetime.now(timezone.utc) + timedelta(hours=COOLING_OFF_HOURS)
    db.commit()
    return limits_dict(db, user)


def self_exclude(db: Session, user: User, days: int) -> dict:
    if days < 1:
        raise ValueError("La autoexclusión mínima es de 1 día")
    lim = get_limits(db, user)
    until = datetime.now(timezone.utc) + timedelta(days=days)
    if lim.self_excluded_until is None or aware(lim.self_excluded_until) < until:
        lim.self_excluded_until = until  # no se puede acortar
    db.commit()
    return limits_dict(db, user)


def spent(db: Session, user: User, since: datetime) -> float:
    return float(db.scalar(select(func.coalesce(func.sum(UserBet.stake_cop), 0.0))
                           .where(UserBet.user_id == user.id, UserBet.placed_at >= since)) or 0.0)


def limits_dict(db: Session, user: User) -> dict:
    lim = get_limits(db, user)
    now = datetime.now(timezone.utc)
    usage = {"day": spent(db, user, now - timedelta(days=1)), "week": spent(db, user, now - timedelta(days=7)),
             "month": spent(db, user, now - timedelta(days=30))}
    return {
        "daily_stake_cop": lim.daily_stake_cop, "weekly_stake_cop": lim.weekly_stake_cop,
        "monthly_stake_cop": lim.monthly_stake_cop, "session_minutes": lim.session_minutes,
        "self_excluded_until": aware(lim.self_excluded_until).isoformat() if lim.self_excluded_until else None,
        "pending_changes": lim.pending_changes or {},
        "pending_effective_at": aware(lim.pending_effective_at).isoformat() if lim.pending_effective_at else None,
        "usage_cop": usage,
    }


def gate(db: Session, user: User | None, request: Request | None = None) -> dict | None:
    """Devuelve un bloqueo si el usuario está autoexcluido o superó sus límites."""
    if user is None:
        return None
    lim = get_limits(db, user)
    now = datetime.now(timezone.utc)
    if lim.self_excluded_until and aware(lim.self_excluded_until) > now:
        return {"blocked": True, "reason": "self_excluded", "until": aware(lim.self_excluded_until).isoformat(),
                "message": "Autoexclusión activa. Las herramientas de análisis de apuestas están bloqueadas."}
    d = limits_dict(db, user)
    for key, period in (("daily_stake_cop", "day"), ("weekly_stake_cop", "week"), ("monthly_stake_cop", "month")):
        cap = d[key]
        if cap is not None and d["usage_cop"][period] >= cap:
            return {"blocked": True, "reason": f"limit_{period}", "message":
                    f"Alcanzó su límite de gasto ({period}). Las herramientas de combinadas se reactivan cuando "
                    f"el periodo termine."}
    if request is not None and lim.session_minutes and getattr(request.state, "session_started", None):
        mins = (now - request.state.session_started).total_seconds() / 60
        if mins > lim.session_minutes:
            return {"blocked": True, "reason": "session_time",
                    "message": f"Superó su tiempo de sesión de {lim.session_minutes} minutos. Tómese un descanso."}
    return None
