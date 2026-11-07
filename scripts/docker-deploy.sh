#!/bin/sh
# Envoltorio de docker compose con el fichero de secretos de despliegue.
#
# Uso:
#   scripts/docker-deploy.sh up -d --build backend frontend
#   scripts/docker-deploy.sh logs -f backend
#
# El fichero por defecto es ~/.config/financial-tools/deploy.env (chmod 600)
# y NO se versiona. Puedes sobreescribirlo con FINANCIAL_ENV_FILE.
set -eu

ENV_FILE="${FINANCIAL_ENV_FILE:-$HOME/.config/financial-tools/deploy.env}"
if [ ! -f "$ENV_FILE" ]; then
    echo "Falta $ENV_FILE. Copia deploy.env.example y rellena DATABASE_URL/SESSION_SECRET." >&2
    exit 1
fi

exec docker compose --env-file "$ENV_FILE" "$@"
