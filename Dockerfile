# =============================================================================
# financial-tools — Multi-stage Dockerfile
#
# Stages (used by docker-compose --target):
#   backend   → Python / FastAPI / uvicorn on port 8001
#   frontend  → Next.js standalone on port 3000
#
# Build args:
#   BACKEND_URL  URL the Next.js server-side rewrite uses to reach the API.
#
# Runtime env (backend):
#   DATABASE_URL     PostgreSQL: postgresql+psycopg://user:pass@host:5432/db
#   DATA_DIR         default /data/files (volumen persistente)
#   SESSION_SECRET   obligatorio en producción
# =============================================================================

# ── Stage 1: Build Next.js frontend ──────────────────────────────────────────
FROM node:20-slim AS frontend-build

WORKDIR /build
COPY frontend-v2/package*.json ./
RUN npm ci
COPY frontend-v2/ ./

# BACKEND_URL is baked into the Next.js rewrite at build time.
ARG BACKEND_URL=http://backend:8001
ENV BACKEND_URL=$BACKEND_URL
ENV NEXT_PUBLIC_API_URL=""

RUN npm run build


# ── Stage 2: Backend runtime ──────────────────────────────────────────────────
FROM python:3.12-slim AS backend

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        tesseract-ocr-spa \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir \
    "fastapi>=0.115" \
    "uvicorn[standard]>=0.34" \
    "openai>=1.0" \
    "python-dotenv>=1.0" \
    "sqlalchemy>=2.0" \
    "alembic>=1.18" \
    "python-multipart>=0.0.18" \
    "yfinance>=1.0.0" \
    "psycopg[binary]>=3.2" \
    "argon2-cffi>=23" \
    "pydantic-settings>=2" \
    "httpx>=0.28" \
    "pdfplumber>=0.11" \
    "openpyxl>=3.1" \
    "pypdfium2>=4.30" \
    "pytesseract>=0.3.13" \
    "Pillow>=10.0"

COPY src/ ./src/
COPY alembic/ ./alembic/
COPY alembic.ini ./alembic.ini
COPY scripts/ ./scripts/

RUN chmod +x /app/scripts/docker-entrypoint.sh \
    && mkdir -p /data/files

ENV ENV=production \
    DATA_DIR=/data/files

VOLUME ["/data"]

EXPOSE 8001

HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8001/api/v3/health', timeout=3)"]

ENTRYPOINT ["/app/scripts/docker-entrypoint.sh"]
CMD ["python", "-m", "uvicorn", "src.api:app", "--host", "0.0.0.0", "--port", "8001"]


# ── Stage 3: Frontend runtime ─────────────────────────────────────────────────
FROM node:20-slim AS frontend

WORKDIR /app

# Copy the standalone build output (includes trimmed node_modules + server.js)
COPY --from=frontend-build /build/.next/standalone/ ./
# Static assets must sit next to server.js. frontend-v2 no tiene public/
# propio (los iconos viven en src/app), así que no se copia esa carpeta.
COPY --from=frontend-build /build/.next/static/ ./.next/static/

ENV NODE_ENV=production \
    PORT=3000 \
    HOSTNAME=0.0.0.0

EXPOSE 3000
CMD ["node", "server.js"]
