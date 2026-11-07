# Variables de entorno del despliegue

`deploy.env` vive **fuera del repo**, por defecto en:

```text
~/.config/financial-tools/deploy.env
```

Se carga con:

```bash
scripts/docker-deploy.sh up -d --build backend import-worker frontend
```

El fichero debe tener permisos `600`. `deploy.env.example` es la plantilla
limpia; no contiene secretos.

## 1. Mínimo para arrancar

| Variable | Obligatoria | Uso |
|---|---:|---|
| `DATABASE_URL` | Sí | PostgreSQL real. Se normaliza a `psycopg` v3. |
| `ENV` | Sí | `production` en Docker. |
| `SESSION_SECRET` | Sí | Secreto aleatorio de ≥32 caracteres. |
| `COOKIE_SECURE` | Sí | `false` para HTTP en LAN; `true` con HTTPS. |
| `CORS_ORIGINS` | Recomendada | Orígenes del frontend separados por comas. |
| `SESSION_TTL_DAYS` | No | Default `7`. |

## 2. IA / agentes

| Variable | Obligatoria | Uso |
|---|---:|---|
| `OPENCODE_API_KEY` | Sí para el agente documental | Clave `oc_sk_...` de OpenCode Go. |
| `OPENCODE_MODEL` | No | Default `deepseek-v4.1-flash`. |
| `OPENCODE_FALLBACK_MODELS` | No | Lista separada por comas. |
| `TYPESAFE_API_KEY` | Sí para Jev | Clave de TypeSafe. |
| `JEV_MODEL` | No | Default `jev-latest`. |
| `JEV_MAX_CALLS_PER_RUN` | No | Default `50`. |
| `JEV_REFERENCE_MAX` | No | Default `40`; tope de precedentes por lote. |
| `OCR_LANG` | No | Default `spa+eng`; idioma de Tesseract. |
| `OCR_DPI` | No | Default `250`; render de PDF escaneado. |
| `IMPORT_QUEUE_MODE` | No | `worker` en Docker; `inline` para pruebas locales. |
| `LLM_API_KEY` | Transitoria | Fallback de clasificación actual; retirar cuando Jev cubra todo. |
| `LLM_MODEL` | Transitoria | Default `gpt-4.1-nano` en el compose actual. |

### Ajuste fino opcional

`OPENCODE_BASE_URL`, `OPENCODE_TIMEOUT`, `OPENCODE_MAX_RETRIES`,
`OPENCODE_BACKOFF`, `OPENCODE_MIN_ALLOWANCE_PCT`, `JEV_BASE_URL`,
`JEV_TIMEOUT`, `JEV_MAX_RETRIES`, `JEV_BACKOFF`, `JEV_REFERENCE_MAX`,
`OCR_LANG`, `OCR_DPI`, `IMPORT_WORKER_POLL_SECONDS`.

La extracción de imágenes/PDF escaneado usa OCR local (`tesseract-ocr` y
`tesseract-ocr-spa` se instalan en la imagen). El modelo de texto sigue siendo
`OPENCODE_MODEL=deepseek-v4.1-flash`; no se usa visión de Luna como primaria.

Los defaults del `docker-compose.yml` son válidos; solo se cambian si hace
falta diagnosticar latencia, cuota o reintentos. Muchos de estos parámetros
(modelo, contexto, lote, OCR) se pueden cambiar en caliente desde **Ajustes →
Modelos**; ver [`MODEL_SETTINGS.md`](./MODEL_SETTINGS.md).

## 3. Admin automático (opcional)

| Variable | Uso |
|---|---|
| `ADMIN_EMAIL` | Si se define junto con un hash, el entrypoint crea/actualiza el admin. |
| `ADMIN_PASSWORD_HASH` | Hash Argon2id; nunca la contraseña en claro. |

No es necesario para el día a día: el admin ya existe en PostgreSQL. Para
crear/cambiar el admin manualmente:

```bash
scripts/docker-deploy.sh exec -it -e ADMIN_EMAIL=tu@email.com backend \
  python -m scripts.create_admin
```

`ADMIN_PASSWORD` solo se usa como variable puntual del script; no debe quedar
en `deploy.env`.

## 4. Lo que NO va en `deploy.env`

| Variable | Motivo |
|---|---|
| `DATA_DIR` | `docker-compose.yml` lo fija en `/data/files`. |
| `OPENCODE_SESSION_ID` | Se genera por documento/importación. |
| `OPENAI_API_KEY` | Solo se usa si se mantiene el fallback LLM; preferir `LLM_API_KEY`. |
| `ADMIN_PASSWORD` | Solo para el script, no para el contenedor. |

## 5. Aplicar cambios

```bash
# 1. Editar sin exponer secretos
chmod 600 ~/.config/financial-tools/deploy.env

# 2. Validar la interpolación (no imprime valores sensibles)
scripts/docker-deploy.sh config >/tmp/ft_compose.yml

# 3. Recrear backend, worker y frontend
scripts/docker-deploy.sh up -d --force-recreate backend import-worker frontend

# 4. Comprobar salud y claves configuradas
curl -s http://localhost:3000/api/v3/health | python -m json.tool
```

El health devuelve `opencode_configured` y `typesafe_configured` como booleanos;
nunca muestra las claves.

## 6. Comprobación rápida de claves

Sin imprimir valores:

```bash
awk -F= '/^(OPENCODE_API_KEY|TYPESAFE_API_KEY|LLM_API_KEY)=/{print $1, (length($2) ? "set" : "EMPTY")}' \
  ~/.config/financial-tools/deploy.env
```
