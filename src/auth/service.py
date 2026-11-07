"""Lógica de autenticación y sesiones (sin dependencias de FastAPI)."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import or_
from sqlalchemy.orm import Session as OrmSession
from sqlalchemy.orm import joinedload

from ..models import LoginAttempt, Session, User
from .passwords import dummy_verify, verify_password
from .tokens import generate_session_token, hash_session_token

LOGIN_RATE_LIMIT = 5
LOGIN_RATE_WINDOW_SECONDS = 60
SESSION_ROTATION_SECONDS = 24 * 60 * 60


def normalise_email(email: str | None) -> str:
    return (email or "").strip().lower()


def normalise_name(name: str | None) -> str | None:
    """Normaliza el nombre visible: recorta y convierte vacío en ``None``."""
    value = (name or "").strip()
    return value or None


def get_user_by_email(session: OrmSession, email: str | None) -> User | None:
    normalised = normalise_email(email)
    if not normalised:
        return None
    return session.query(User).filter(User.email == normalised).first()


def get_user(session: OrmSession, user_id: int) -> User | None:
    return session.query(User).filter(User.id == user_id).first()


def create_user(
    session: OrmSession,
    *,
    email: str,
    password_hash: str,
    name: str | None = None,
    role: str = "admin",
    disabled: bool = False,
) -> User:
    user = User(
        email=normalise_email(email),
        name=normalise_name(name),
        password_hash=password_hash,
        role=role,
        disabled=disabled,
        created_at=datetime.utcnow(),
    )
    session.add(user)
    session.flush()
    return user


def upsert_admin(
    session: OrmSession,
    *,
    email: str,
    password_hash: str | None,
    role: str = "admin",
) -> tuple[User, bool]:
    """Crea o actualiza el admin. Devuelve ``(user, created)``.

    Si el usuario ya existe y ``password_hash`` es ``None`` no se toca la
    contraseña; así el script es idempotente.
    """
    normalised = normalise_email(email)
    user = get_user_by_email(session, normalised)
    if user is None:
        if not password_hash:
            raise ValueError("Se necesita una contraseña o hash para crear el admin")
        return create_user(
            session, email=normalised, password_hash=password_hash, role=role
        ), True

    user.role = role
    user.disabled = False
    if password_hash:
        user.password_hash = password_hash
    session.flush()
    return user, False


def set_user_password(session: OrmSession, user: User, password_hash: str) -> None:
    user.password_hash = password_hash
    session.flush()


def authenticate(session: OrmSession, email: str | None, password: str) -> User | None:
    """Autentica sin revelar si el email existe o está deshabilitado."""
    user = get_user_by_email(session, email)
    if user is None or user.disabled:
        # Mismo coste que una verificación real.
        dummy_verify(password)
        return None
    if not verify_password(user.password_hash, password):
        return None
    return user


def record_login_attempt(
    session: OrmSession, *, email: str | None, ip: str | None, ok: bool
) -> LoginAttempt:
    attempt = LoginAttempt(
        email=normalise_email(email) or None,
        ip=ip,
        ok=ok,
        created_at=datetime.utcnow(),
    )
    session.add(attempt)
    return attempt


def recent_failed_attempts(
    session: OrmSession,
    *,
    email: str | None,
    ip: str | None,
    now: datetime | None = None,
    window_seconds: int = LOGIN_RATE_WINDOW_SECONDS,
) -> list[LoginAttempt]:
    now = now or datetime.utcnow()
    cutoff = now - timedelta(seconds=window_seconds)
    query = session.query(LoginAttempt).filter(
        LoginAttempt.ok.is_(False), LoginAttempt.created_at >= cutoff
    )
    conditions = []
    normalised = normalise_email(email)
    if normalised:
        conditions.append(LoginAttempt.email == normalised)
    if ip:
        conditions.append(LoginAttempt.ip == ip)
    if not conditions:
        return []
    return (
        query.filter(or_(*conditions))
        .order_by(LoginAttempt.created_at.asc())
        .all()
    )


def login_retry_after(
    session: OrmSession,
    *,
    email: str | None,
    ip: str | None,
    now: datetime | None = None,
) -> int | None:
    """Segundos de bloqueo si se superó el límite; ``None`` si se permite."""
    now = now or datetime.utcnow()
    attempts = recent_failed_attempts(session, email=email, ip=ip, now=now)
    if len(attempts) < LOGIN_RATE_LIMIT:
        return None
    oldest = attempts[0].created_at
    elapsed = (now - oldest).total_seconds()
    return max(1, int(LOGIN_RATE_WINDOW_SECONDS - elapsed))


def create_session(
    session: OrmSession,
    *,
    user: User,
    ttl_days: int,
    ip: str | None = None,
    user_agent: str | None = None,
    now: datetime | None = None,
) -> tuple[str, Session]:
    now = now or datetime.utcnow()
    token = generate_session_token()
    row = Session(
        user_id=user.id,
        token_hash=hash_session_token(token),
        created_at=now,
        expires_at=now + timedelta(days=ttl_days),
        last_seen_at=now,
        ip=ip,
        user_agent=(user_agent or "")[:500] or None,
    )
    session.add(row)
    session.flush()
    return token, row


def get_valid_session(
    session: OrmSession, token: str | None, *, now: datetime | None = None
) -> Session | None:
    if not token:
        return None
    now = now or datetime.utcnow()
    row = (
        session.query(Session)
        .options(joinedload(Session.user))
        .filter(Session.token_hash == hash_session_token(token))
        .first()
    )
    if row is None or row.revoked_at is not None:
        return None
    if row.expires_at is None or row.expires_at <= now:
        return None
    if row.user is None or row.user.disabled:
        return None
    return row


def touch_session(
    session: OrmSession,
    row: Session,
    *,
    ttl_days: int,
    now: datetime | None = None,
    rotation_seconds: int = SESSION_ROTATION_SECONDS,
) -> str | None:
    """Actualiza ``last_seen_at`` y rota el token cada ``rotation_seconds``.

    Devuelve el token nuevo si hubo rotación; ``None`` si no cambió.
    """
    now = now or datetime.utcnow()
    row.last_seen_at = now
    issued_at = row.created_at or now
    if (now - issued_at).total_seconds() < rotation_seconds:
        # No forzar flush: la dependencia get_db hará commit al terminar la
        # petición. En SQLite un flush aquí mantendría un lock de escritura
        # mientras el endpoint abre otra sesión para mutar el movimiento.
        return None

    new_token = generate_session_token()
    row.token_hash = hash_session_token(new_token)
    row.created_at = now
    row.expires_at = now + timedelta(days=ttl_days)
    # El commit lo hace la dependencia; el token ya está en memoria y la
    # cookie se actualiza en la respuesta.
    return new_token


def revoke_session(
    session: OrmSession, row: Session, *, now: datetime | None = None
) -> None:
    if row.revoked_at is None:
        row.revoked_at = now or datetime.utcnow()
        session.flush()


def revoke_all_sessions(
    session: OrmSession,
    *,
    user_id: int,
    except_session_id: int | None = None,
    now: datetime | None = None,
) -> int:
    now = now or datetime.utcnow()
    query = session.query(Session).filter(
        Session.user_id == user_id, Session.revoked_at.is_(None)
    )
    if except_session_id is not None:
        query = query.filter(Session.id != except_session_id)
    count = 0
    for row in query.all():
        row.revoked_at = now
        count += 1
    session.flush()
    return count


def session_remaining_seconds(row: Session, *, now: datetime | None = None) -> int:
    now = now or datetime.utcnow()
    if row.expires_at is None:
        return 0
    return max(0, int((row.expires_at - now).total_seconds()))
