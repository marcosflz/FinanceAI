"""Cola central de trabajos (``TENANT_MODE=per_user``).

Cada tenant sigue marcando sus importaciones como ``source_files.status =
'queued'`` (sin cambios en la lógica de ingesta). Un listener de sesión detecta
esas filas y, **después del commit del tenant**, crea un :class:`CentralJob`
que solo referencia ``(user_id, ref_id)``: la BD central no ve datos
financieros. A la vez se sella la DEK para los workers vivos (concesión
``import``), porque es el único momento en que el usuario está presente.
"""

from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import event
from sqlalchemy.orm import Session as OrmSession

from .config import get_settings
from .db.tenant import current_tenant
from .models import CentralJob, SourceFile, User

logger = logging.getLogger("financial.jobs")
_INFO_KEY = "ft_queued_imports"


def enqueue_central(user_id: int, kind: str, ref_id: int | None) -> int:
    """Crea (o reutiliza) un trabajo central pendiente para ese ``ref_id``."""
    from .db.session import central_session

    with central_session() as db:
        existing = (
            db.query(CentralJob)
            .filter(
                CentralJob.user_id == user_id,
                CentralJob.kind == kind,
                CentralJob.ref_id == ref_id,
                CentralJob.status.in_(("queued", "processing", "waiting_unlock")),
            )
            .first()
        )
        if existing is not None:
            if existing.status == "waiting_unlock":
                existing.status = "queued"
            return existing.id
        job = CentralJob(
            user_id=user_id,
            kind=kind,
            ref_id=ref_id,
            status="queued",
            run_at=datetime.utcnow(),
            created_at=datetime.utcnow(),
        )
        db.add(job)
        db.flush()
        return job.id


def _grant_import_lease(user_id: int, dek: bytes) -> None:
    from datetime import timedelta

    from .auth import tenancy
    from .db.session import central_session

    with central_session() as db:
        user = db.query(User).filter_by(id=user_id).first()
        if user is None:
            return
        tenancy.grant_lease(
            db,
            user,
            dek,
            purpose="import",
            expires_at=datetime.utcnow() + timedelta(hours=tenancy.IMPORT_LEASE_HOURS),
        )


@event.listens_for(OrmSession, "after_flush")
def _collect_queued(session: OrmSession, _flush_context) -> None:
    if not get_settings().per_user or current_tenant() is None:
        return
    for obj in list(session.new) + list(session.dirty):
        if isinstance(obj, SourceFile) and obj.status == "queued" and obj.id is not None:
            session.info.setdefault(_INFO_KEY, set()).add(obj.id)


@event.listens_for(OrmSession, "after_rollback")
def _discard_queued(session: OrmSession) -> None:
    session.info.pop(_INFO_KEY, None)


@event.listens_for(OrmSession, "after_commit")
def _publish_queued(session: OrmSession) -> None:
    ids = session.info.pop(_INFO_KEY, None)
    ctx = current_tenant()
    if not ids or ctx is None:
        return
    if ctx.key is not None:
        _grant_import_lease(ctx.user_id, ctx.key)
    for source_file_id in sorted(ids):
        enqueue_central(ctx.user_id, "import", source_file_id)
