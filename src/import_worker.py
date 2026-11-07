"""Worker de importaciones: procesa la cola persistente de ``source_files``.

La API solo guarda el fichero y crea una fila ``queued``. Este proceso se
ejecuta como servicio independiente en Docker para que una extracción de PDF
de varios minutos no bloquee la petición HTTP.
"""

from __future__ import annotations

import logging
import os
import signal
import time
from datetime import datetime, timedelta

from .db.session import _session
from .ingest_service import process_import
from .models import SourceFile

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
    process_import(
        path,
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


def run_once() -> bool:
    job_id = claim_next_job()
    if job_id is None:
        return False
    logger.info("Procesando importación %s", job_id)
    try:
        process_job(job_id)
    except Exception as exc:  # el worker no debe morir por un documento raro
        logger.exception("Importación %s falló: %s", job_id, exc)
        mark_failed(job_id, exc)
    else:
        logger.info("Importación %s terminada", job_id)
    return True


def main() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    signal.signal(signal.SIGTERM, _handle_stop)
    signal.signal(signal.SIGINT, _handle_stop)
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
