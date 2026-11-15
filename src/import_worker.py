"""Worker de importaciones: procesa la cola persistente de ``source_files``.

La API solo guarda el fichero y crea una fila ``queued``. Este proceso se
ejecuta como servicio independiente en Docker para que una extracción de PDF
de varios minutos no bloquee la petición HTTP.

En ``TENANT_MODE=per_user`` la cola está en la BD central (``central_jobs``,
ver :mod:`src.jobs`). El worker genera al arrancar un par X25519 efímero y
publica la clave pública; los usuarios le sellan su DEK (``key_leases``). La
privada solo vive en RAM: tras un reinicio, los trabajos de usuarios con
cifrado quedan ``waiting_unlock`` hasta su siguiente petición autenticada.
"""

from __future__ import annotations

import logging
import os
import signal
import time
from datetime import datetime, timedelta

from . import jobs as _jobs  # noqa: F401 — registra los listeners de cola
from . import storage
from .auth import keys as key_ops
from .config import get_settings
from .db.session import _session, central_session
from .db.tenant import TenantContext, registry, use_tenant
from .ingest_service import process_import
from .models import CentralJob, KeyLease, SourceFile, User, WorkerKey

logger = logging.getLogger("financial.import_worker")
POLL_SECONDS = float(os.getenv("IMPORT_WORKER_POLL_SECONDS", "2"))
STALE_MINUTES = int(os.getenv("IMPORT_WORKER_STALE_MINUTES", "30"))
_stop = False


def _handle_stop(*_args) -> None:
    global _stop
    _stop = True


def reset_stale_jobs() -> int:
    """Devuelve a la cola los trabajos que quedaron a medias por un reinicio."""
    cutoff = datetime.utcnow() - timedelta(minutes=STALE_MINUTES)
    with _session() as session:
        jobs = (
            session.query(SourceFile)
            .filter(
                SourceFile.status == "processing",
                SourceFile.started_at.isnot(None),
                SourceFile.started_at < cutoff,
            )
            .all()
        )
        for job in jobs:
            job.status = "queued"
            job.queued_at = datetime.utcnow()
            job.started_at = None
            job.error = "Reintentado tras reinicio del worker"
        return len(jobs)


def claim_next_job() -> int | None:
    """Reclama atómicamente el siguiente trabajo pendiente."""
    with _session() as session:
        query = (
            session.query(SourceFile)
            .filter(SourceFile.status == "queued")
            .order_by(SourceFile.queued_at, SourceFile.id)
        )
        if session.bind is not None and session.bind.dialect.name == "postgresql":
            query = query.with_for_update(skip_locked=True)
        job = query.first()
        if job is None:
            return None
        job.status = "processing"
        job.started_at = datetime.utcnow()
        job.attempts = (job.attempts or 0) + 1
        job.error = None
        return job.id


def process_job(job_id: int) -> None:
    with _session() as session:
        job = session.query(SourceFile).filter_by(id=job_id).first()
        if job is None:
            return
        path = job.storage_path
        filename = job.filename
        account_id = job.account_id
    if not path or not os.path.exists(path):
        raise FileNotFoundError(f"Fichero original no disponible: {path}")
    with storage.plaintext_path(path) as readable:
        process_import(
            readable,
            force=True,
            original_filename=filename,
            account_id=account_id,
            source_file_id=job_id,
            reuse_extraction=True,
        )


def mark_failed(job_id: int, exc: BaseException) -> None:
    with _session() as session:
        job = session.query(SourceFile).filter_by(id=job_id).first()
        if job is None:
            return
        job.status = "failed"
        job.finished_at = datetime.utcnow()
        job.parseado_en = datetime.utcnow()
        job.error = f"{type(exc).__name__}: {exc}"[:4000]


def run_single_bot_once() -> bool:
    """Modo single: los bots se programan en la cola central (misma BD)."""
    from .auth.tenancy import SINGLE_TENANT_ID

    claimed = claim_central_job(("bot_run",))
    if claimed is None:
        return False
    job_id, user_id, _kind, ref_id = claimed
    try:
        with use_tenant(TenantContext(user_id=user_id, tenant_id=SINGLE_TENANT_ID)):
            _run_bot(job_id, ref_id)
    except Exception as exc:
        logger.exception("Bot %s falló: %s", ref_id, exc)
        finish_central_job(job_id, "failed", error=f"{type(exc).__name__}: {exc}")
    return True


def run_once() -> bool:
    job_id = claim_next_job()
    if job_id is None:
        return run_single_bot_once()
    logger.info("Procesando importación %s", job_id)
    try:
        process_job(job_id)
    except Exception as exc:  # el worker no debe morir por un documento raro
        logger.exception("Importación %s falló: %s", job_id, exc)
        mark_failed(job_id, exc)
    else:
        logger.info("Importación %s terminada", job_id)
    return True


# ── Modo per_user: cola central + concesiones de clave ───────────────────────

HEARTBEAT_SECONDS = 30
LOCK_MINUTES = STALE_MINUTES
RETRY_SECONDS = 5


class WorkerIdentity:
    """Par X25519 efímero del proceso. La privada nunca sale de la RAM."""

    def __init__(self) -> None:
        import secrets

        self.id = secrets.token_hex(8)
        self._private, self.public_b64 = key_ops.generate_worker_keypair()
        self._last_beat = 0.0

    def heartbeat(self, *, force: bool = False) -> None:
        now_mono = time.monotonic()
        if not force and now_mono - self._last_beat < HEARTBEAT_SECONDS:
            return
        now = datetime.utcnow()
        with central_session() as db:
            row = db.query(WorkerKey).filter_by(id=self.id).first()
            if row is None:
                db.add(
                    WorkerKey(
                        id=self.id, public_key=self.public_b64, created_at=now, last_seen_at=now
                    )
                )
            else:
                row.last_seen_at = now
            # Claves de workers muertos: sus concesiones ya no sirven a nadie.
            cutoff = now - timedelta(hours=1)
            dead = [w.id for w in db.query(WorkerKey).filter(WorkerKey.last_seen_at < cutoff)]
            if dead:
                db.query(KeyLease).filter(KeyLease.worker_key_id.in_(dead)).delete(
                    synchronize_session=False
                )
                db.query(WorkerKey).filter(WorkerKey.id.in_(dead)).delete(
                    synchronize_session=False
                )
        self._last_beat = now_mono

    def unseal(self, user_id: int, purposes: tuple[str, ...]) -> bytes | None:
        now = datetime.utcnow()
        with central_session() as db:
            leases = (
                db.query(KeyLease)
                .filter(
                    KeyLease.user_id == user_id,
                    KeyLease.worker_key_id == self.id,
                    KeyLease.purpose.in_(purposes),
                    KeyLease.expires_at > now,
                )
                .all()
            )
            sealed = [(lease.purpose, lease.sealed_dek) for lease in leases]
        for purpose, blob in sealed:
            try:
                return key_ops.open_sealed(user_id, purpose, blob, self._private)
            except key_ops.KeyUnwrapError:
                continue
        return None

    def forget(self) -> None:
        with central_session() as db:
            db.query(KeyLease).filter(KeyLease.worker_key_id == self.id).delete(
                synchronize_session=False
            )
            db.query(WorkerKey).filter_by(id=self.id).delete(synchronize_session=False)


def reset_stale_central_jobs(now: datetime | None = None) -> int:
    now = now or datetime.utcnow()
    with central_session() as db:
        stale = (
            db.query(CentralJob)
            .filter(CentralJob.status == "processing", CentralJob.locked_until < now)
            .all()
        )
        for job in stale:
            job.status = "queued"
            job.locked_until = None
            job.error = "Reintentado tras reinicio del worker"
        return len(stale)


def claim_central_job(kinds: tuple[str, ...] = ("import",)) -> tuple[int, int, str, int | None] | None:
    now = datetime.utcnow()
    with central_session() as db:
        query = (
            db.query(CentralJob)
            .filter(
                CentralJob.status == "queued",
                CentralJob.kind.in_(kinds),
                CentralJob.run_at <= now,
            )
            .order_by(CentralJob.run_at, CentralJob.id)
        )
        if db.bind is not None and db.bind.dialect.name == "postgresql":
            query = query.with_for_update(skip_locked=True)
        job = query.first()
        if job is None:
            return None
        job.status = "processing"
        job.attempts = (job.attempts or 0) + 1
        job.locked_until = now + timedelta(minutes=LOCK_MINUTES)
        job.error = None
        return job.id, job.user_id, job.kind, job.ref_id


def finish_central_job(
    job_id: int, status: str, *, error: str | None = None, retry_in: float | None = None
) -> None:
    now = datetime.utcnow()
    with central_session() as db:
        job = db.query(CentralJob).filter_by(id=job_id).first()
        if job is None:
            return
        job.status = status
        job.error = (error or None) and error[:4000]
        job.locked_until = None
        if status in {"done", "failed"}:
            job.finished_at = now
        if retry_in is not None:
            job.run_at = now + timedelta(seconds=retry_in)


def tenant_context_for(
    identity: WorkerIdentity, user_id: int, purposes: tuple[str, ...]
) -> TenantContext | None:
    """Contexto del tenant con la DEK de la concesión; ``None`` si no hay."""
    settings = get_settings()
    with central_session() as db:
        user = db.query(User).filter_by(id=user_id).first()
        if user is None or user.disabled or not user.tenant_id:
            return None
        tenant_id = user.tenant_id
    key = None
    if settings.tenant_encryption:
        key = identity.unseal(user_id, purposes)
        if key is None:
            return None
    return TenantContext(user_id=user_id, tenant_id=tenant_id, key=key)


def _claim_tenant_import(source_file_id: int) -> bool:
    with _session() as session:
        sf = session.query(SourceFile).filter_by(id=source_file_id).first()
        if sf is None or sf.status not in {"queued", "processing"}:
            return False
        sf.status = "processing"
        sf.started_at = datetime.utcnow()
        sf.attempts = (sf.attempts or 0) + 1
        sf.error = None
        return True


def _run_bot(job_id: int, bot_id: int | None) -> None:
    import asyncio

    from .agent.bots import execute_bot

    if bot_id is None:
        finish_central_job(job_id, "done", error="Sin bot")
        return
    result = asyncio.run(execute_bot(bot_id))
    status = result.get("status")
    if status == "missing":
        finish_central_job(job_id, "done", error="El bot ya no existe")
    elif status in {"completed", "interrupted"}:
        finish_central_job(job_id, "done")
    else:
        finish_central_job(job_id, "failed", error=(result.get("error") or "Error")[:500])


def run_central_once(identity: WorkerIdentity) -> bool:
    identity.heartbeat()
    claimed = claim_central_job(("import", "bot_run"))
    if claimed is None:
        registry.close_idle()
        return False
    job_id, user_id, kind, ref_id = claimed
    ctx = tenant_context_for(identity, user_id, ("import", "automation"))
    if ctx is None:
        # Sin clave en RAM: el usuario la volverá a conceder al entrar.
        finish_central_job(job_id, "waiting_unlock", error="Esperando a que el usuario inicie sesión")
        return True
    logger.info("Procesando %s %s del usuario %s", kind, ref_id, user_id)
    if kind == "bot_run":
        try:
            with use_tenant(ctx):
                _run_bot(job_id, ref_id)
        except Exception as exc:
            logger.exception("Bot %s falló: %s", ref_id, exc)
            finish_central_job(job_id, "failed", error=f"{type(exc).__name__}: {exc}")
        return True
    try:
        with use_tenant(ctx):
            if ref_id is None or not _claim_tenant_import(ref_id):
                finish_central_job(job_id, "done", error="Importación ya no pendiente")
                return True
            try:
                process_job(ref_id)
            except Exception as exc:
                logger.exception("Importación %s falló: %s", ref_id, exc)
                mark_failed(ref_id, exc)
                finish_central_job(job_id, "failed", error=f"{type(exc).__name__}")
                return True
    except Exception as exc:  # BD del tenant inaccesible, etc.
        logger.exception("Trabajo %s falló: %s", job_id, exc)
        finish_central_job(job_id, "failed", error=f"{type(exc).__name__}: {exc}")
        return True
    finish_central_job(job_id, "done")
    return True


def main_per_user() -> None:
    identity = WorkerIdentity()
    identity.heartbeat(force=True)
    reset = reset_stale_central_jobs()
    if reset:
        logger.info("%s trabajos obsoletos devueltos a la cola", reset)
    logger.info("Worker multi-tenant arrancado (id=%s, poll=%ss)", identity.id, POLL_SECONDS)
    try:
        while not _stop:
            if not run_central_once(identity):
                time.sleep(POLL_SECONDS)
    finally:
        identity.forget()
        registry.close_all()
    logger.info("Worker de importaciones detenido")


def main() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    signal.signal(signal.SIGTERM, _handle_stop)
    signal.signal(signal.SIGINT, _handle_stop)
    if get_settings().per_user:
        main_per_user()
        return
    reset = reset_stale_jobs()
    if reset:
        logger.info("%s trabajos obsoletos devueltos a la cola", reset)
    logger.info("Worker de importaciones arrancado (poll=%ss)", POLL_SECONDS)
    while not _stop:
        if not run_once():
            time.sleep(POLL_SECONDS)
    logger.info("Worker de importaciones detenido")


if __name__ == "__main__":
    main()
