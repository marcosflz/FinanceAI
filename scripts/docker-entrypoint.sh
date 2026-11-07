#!/bin/sh
# Entrypoint del backend: aplica migraciones y arranca el proceso.
# Fail-fast: si Alembic falla (BD inaccesible, revisión inconsistente), el
# contenedor no arranca. No imprime secretos.
set -eu

: "${DATA_DIR:=/data/files}"
export DATA_DIR
mkdir -p "$DATA_DIR"

# Normaliza URLs PostgreSQL al driver psycopg v3 antes de Alembic.
if [ -n "${DATABASE_URL:-}" ]; then
    case "$DATABASE_URL" in
        postgres://*)
            DATABASE_URL="postgresql+psycopg://${DATABASE_URL#postgres://}"
            export DATABASE_URL
            ;;
        postgresql://*)
            DATABASE_URL="postgresql+psycopg://${DATABASE_URL#postgresql://}"
            export DATABASE_URL
            ;;
    esac
fi

echo "[entrypoint] Aplicando migraciones de Alembic..."
python -m alembic upgrade head
echo "[entrypoint] Migraciones aplicadas."

# Seed opcional e idempotente del admin (solo si hay credencial configurada).
if [ -n "${ADMIN_EMAIL:-}" ] && \
   { [ -n "${ADMIN_PASSWORD_HASH:-}" ] || [ -n "${ADMIN_PASSWORD:-}" ]; }; then
    echo "[entrypoint] Asegurando admin ${ADMIN_EMAIL}..."
    python -m scripts.create_admin
fi

echo "[entrypoint] Arrancando: $*"
exec "$@"
