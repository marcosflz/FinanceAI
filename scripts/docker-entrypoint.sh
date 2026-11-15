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

: "${TENANT_MODE:=single}"
if [ "$TENANT_MODE" = "per_user" ] || [ "$TENANT_MODE" = "per-user" ]; then
    # Cada SQLite de usuario se migra al abrirse (necesita su clave); aquí
    # solo la BD central.
    : "${TENANT_DIR:=/data/tenants}"
    export TENANT_DIR
    mkdir -p "$TENANT_DIR"
    echo "[entrypoint] Migrando BD central..."
    python -m alembic -c alembic_central.ini upgrade head
else
    echo "[entrypoint] Aplicando migraciones de Alembic..."
    python -m alembic upgrade head
    python -m alembic -c alembic_central.ini upgrade head
fi
echo "[entrypoint] Migraciones aplicadas."

# Seed opcional e idempotente del admin (solo si hay credencial configurada).
if [ -n "${ADMIN_EMAIL:-}" ] && \
   { [ -n "${ADMIN_PASSWORD_HASH:-}" ] || [ -n "${ADMIN_PASSWORD:-}" ]; }; then
    echo "[entrypoint] Asegurando admin ${ADMIN_EMAIL}..."
    python -m scripts.create_admin
fi

echo "[entrypoint] Arrancando: $*"
exec "$@"
