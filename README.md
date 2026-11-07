# financial-tools

Panel personal de finanzas: ingesta de extractos, deduplicación, clasificación
determinista + Jev, cartera y una UI nueva. El estado operativo actual está en
este README y en [`docs/IMPLEMENTATION_STATUS.md`](docs/IMPLEMENTATION_STATUS.md);
la guía para agentes y el protocolo de obtención de contexto están en
[`AGENTS.md`](AGENTS.md). El plan de evolución histórico queda en
[`docs/PLAN_2026-10-31.md`](docs/PLAN_2026-10-31.md) solo como referencia.

## Estado actual

- **Backend v2/v3**: SQLAlchemy 2, Alembic, FastAPI, PostgreSQL-first
  (`psycopg` v3) y SQLite para dev/tests.
- **Ingesta agéntica**: CSV/TSV, XLSX, PDF con texto y OCR de imágenes/PDF
  escaneado; validación de fechas/importes/saldos y cola persistente con
  `import-worker`. Sin parser por banco en producción. Los PDF se dividen por
  secciones/divisa, ignoran Revertidas y Pockets/Depósito secundarios, y los
  snapshots de patrimonio se guardan como valoraciones sin crear compras.
- **Clasificación**: reglas MCC/merchant + memoria + Jev; lotes configurables
  con precedentes crecientes y aprobación humana. El import actual tiene
  **535 movimientos**, **327 clasificaciones vigentes** y **208 pendientes**;
  las reglas base están sin sembrar.
- **Taxonomía**: dos niveles (raíz + subcategoría plana), `Otros` por defecto y
  herencia obligatoria de `tratamiento`/`excluir_kpis`. Migración actual:
  `v3_013_import_portfolio`. Ver “Taxonomía y KPIs”.
- **KPIs**: transferencias internas y compras/ventas de inversión se excluyen
  por categoría y por `kind`; dividendos e intereses cuentan como ingreso. El
  saveback en activo se clasifica en `Inversiones › Cashback` y no infla los
  ingresos.
- **Auth**: login email/password, Argon2id, sesiones opacas en PostgreSQL,
  CSRF, rate limit y cookies seguras. Perfil editable (nombre, email y
  contraseña) desde **Ajustes → General/Seguridad**. Sin 2FA por ahora. La app
  es **single-user**: no hay registro público ni taxonomía por usuario.
- **Ajustes de modelos**: contexto de Jev, lote, límite de llamadas, modelo
  documental/fallback y OCR editables desde **Ajustes → Modelos**
  ([`docs/MODEL_SETTINGS.md`](docs/MODEL_SETTINGS.md)).
- **Frontend nuevo**: `frontend-v2/` (Next.js 16 + React 19 + Tailwind 4 +
  TanStack Query), con login, dashboard, movimientos, importaciones, cuentas,
  cartera y ajustes. El `frontend/` legacy se retiró en la limpieza 2026-11-04;
el Docker   construye `frontend-v2/`.
- **IA**: cliente Python directo de OpenCode Go (`deepseek-v4.1-flash` por
  defecto, fallback dentro de Go) y cliente Jev; sin OpenRouter y sin agente
  OpenCode embebido.

### Datos actuales (2026-11-04)

| Elemento | Valor |
|---|---:|
| Movimientos | **0** (vaciado 2026-11-04 para reimportar) |
| Importaciones | **0** |
| Cuentas | **1** (Trade Republic; Revolut pendiente) |
| Categorías | **41 (35 activas)** |
| Reglas / memoria | **0 / 0** |
| Clasificaciones vigentes | **0** |
| Pendientes de clasificar | **0** |
| Activos / operaciones / posiciones | **0 / 0 / 0** |
| Migración | **`v3_013_import_portfolio`** |

## Taxonomía y KPIs (estado 2026-11-02)

### Estructura

La taxonomía tiene **dos niveles**:

```text
Categoría raíz
└── Subcategoría
```

No se permiten nietos. Cada raíz activa tiene una subcategoría `Otros` por
defecto. `classification.categoria_id` apunta siempre a la hoja asignable: la
subcategoría si existe, o la raíz si no tiene hijas.

### Por qué Transferencias e Inversiones no cuentan en KPIs

- **Transferencias** tiene `tratamiento=transferencia`.
- **Inversiones** tiene `tratamiento=inversion`.

La API fuerza `excluir_kpis=true` para ambos tratamientos. No es un descuido:
una transferencia entre cuentas propias no es ingreso/gasto, y una compra o
venta de inversión no es gasto/ingreso corriente. Contarlas distorsionaría el
ahorro y el flujo de caja.

Además, los KPIs excluyen por `kind`:

- `transferencia_interna`
- `inversion_compra`
- `inversion_venta`
- `aporte_activo`

Así una clasificación antigua o manual no puede inflar los KPIs.

### Categorías actuales de Inversiones

```text
Inversiones
├── Compras
├── Ventas          ← antes Ingresos › Beneficios
├── Aportaciones
├── Cashback        ← saveback en activo
└── Otros
```

`Ingresos › Cashback` se conserva para cashback fiat manual. `Dividendos` e
`Intereses` siguen en `Ingresos` porque se perciben en líquido.

### Protecciones actuales

- La API rechaza categorías con más de dos niveles.
- Una subcategoría no puede tener un tratamiento distinto de su raíz.
- La UI bloquea tratamiento/exclusión en subcategorías y avisa de que se edita
  en la raíz.
- Con tratamiento `transferencia`/`inversión`, el checkbox “Excluir de KPIs”
  está deshabilitado y marcado.
- Al cambiar una raíz a `Normal`, la exclusión se desmarca automáticamente; se
  puede volver a marcar si se quiere excluir una categoría normal.
- `scripts/docker-deploy.sh` aplica las migraciones antes de arrancar.

### Límites conocidos

- La app es **single-user**: `categorias` no tiene `user_id`; si se añaden más
  usuarios, todos comparten la taxonomía.
- No hay registro público; los usuarios se crean con `scripts.create_admin`.
- Las categorías de sistema (`Transferencias`, `Inversiones`) **no están
  completamente bloqueadas**: hoy se pueden renombrar, cambiar a `Normal` o
  quitarles `system_key`. El clasificador determinista busca por nombre/path,
  no por `system_key`, así que renombrarlas puede romper el mapping.
- Un usuario podría crear una raíz nueva llamada `Transferencias` o
  `Inversiones` con tratamiento `Normal`. Las transferencias internas y las
  inversiones seguirían excluidas por `kind`, pero una transferencia externa
  registrada como `gasto`/`ingreso` y clasificada a mano ahí sí podría contar.
- Quedan **208 movimientos pendientes** de clasificación en el import actual.

La solución recomendada para una apertura a más usuarios es bloquear las
categorías de sistema, mapear por `system_key` y añadir `user_id` a la
taxonomía con una semilla por usuario.

## Quick start (dev, SQLite)

```bash
cp -n .env.example .env
# Edita al menos SESSION_SECRET y, si usas IA, TYPESAFE_API_KEY/OPENCODE_API_KEY

source .venv/bin/activate
alembic upgrade head
# Opcional: reglas base con los paths actuales.
python -m scripts.seed_reimport_rules
# Las cuentas son explícitas: créalas en /accounts o al importar el primer extracto.

# Crea el admin (pide la contraseña; no la guarda en claro)
ADMIN_EMAIL=tu@email.com python -m scripts.create_admin

# Importa el CSV de ejemplo sobre una copia o sobre la BD local
uvicorn src.api:app --reload --port 8001

# Frontend
cd frontend-v2
npm install
BACKEND_URL=http://localhost:8001 npm run dev
```

Abre `http://localhost:3000`. Sin sesión, cualquier ruta redirige a `/login`;
la API real devuelve `401` en `/api/v3/*` salvo login/health.

## Importar un extracto

```bash
curl -b cookies.txt -c cookies.txt \
  -F "files=@/ruta/a/tu/extracto.csv" \
  http://localhost:8001/api/v3/imports
```

`account_id` es opcional. Sin él, cada fichero resuelve su cuenta por IBAN,
perfil documental aprobado o candidato único de banco/producto. Una identidad
nueva o ambigua queda en revisión y se confirma con
`POST /api/v3/imports/{id}/confirm-account`.

- La extracción es agéntica: OpenCode Go (DeepSeek V4.1 Flash por defecto)
  infiere el formato/columnas y el código valida fechas, importes, signo,
  cuentas, saldo y dedup. No hay parser por banco en producción.
- Formatos: CSV/TSV, XLSX, PDF con texto y PDF escaneado/imágenes mediante
  OCR local (Tesseract) + DeepSeek; los imports con OCR quedan en revisión.
- La API responde `queued`; un worker persistente procesa el fichero. La UI
  actualiza el estado automáticamente.
- Interfaz `/imports` (2026-11-04): zona de subida (sube al soltar), bandeja
  **«Pendiente de tu aprobación»** y gestor de archivos (en cola con posición,
  procesando con tiempo, esperando aprobación, importado, error; descartar y
  reintentar). Cada import expone `pending_action` (`create_account`,
  `confirm_account`, `unsupported_product`, `review_movements`) con la cuenta
  propuesta (nombre, IBAN, tipo, broker, saldo inicial). Hasta aprobarla no se
  crean movimientos.
- Al dejar un extracto en revisión se guarda su extracción
  (`DATA_DIR/<hash>.extraction.pkl`); al aprobar la cuenta el worker la reutiliza
  sin volver a llamar al modelo. `reprocess` la descarta y re-extrae.
- La cuenta se detecta por documento. La API acepta `account_id` como override
  multipart, pero ya no es obligatorio con varias cuentas activas.
- Un fichero ya importado se devuelve como idempotente (`duplicate=true`), no
  como error.
- El informe incluye filas, nuevas, vistas, duplicados, pendientes y
  reconciliación.
- La cola de duplicados L3 compara **solo movimientos de ficheros distintos**.
  Dos compras legítimas iguales del mismo día en el mismo extracto no se
  marcan como duplicado; el solapamiento entre enero-junio y junio-octubre sí.
- La normalización conserva el IBAN de `description_raw` antes de redactar,
  asigna cuenta origen/destino y auto-aprueba transferencias internas.
- El saldo de una cuenta es su saldo inicial + movimientos, calculado por
  divisa; no se abona automáticamente la cuenta destino de una transferencia
  interna.
- En Movimientos hay clasificación asistida por Jev en lotes configurables.
  Las decisiones con confianza ≥ umbral (95 % por defecto) se autoaprueban y
  desaparecen de la cola de revisión; solo se muestran las dudosas. Las
  aceptadas son precedentes del siguiente lote (hasta el contexto configurado).
- Las cuentas admiten **saldo inicial + fecha**: el saldo solo suma movimientos
  desde esa fecha. Se edita en la tarjeta de cada cuenta.
- El dashboard tiene selector de periodo: todo, mes actual, mes anterior,
  últimos 3 meses, año o rango personalizado; actualiza resumen, cashflow y
  desglose por categoría.
- En CSV de broker, el movimiento de efectivo usa `amount + fee + tax`; el
  evento conserva el bruto para la cartera.
- Los PDF se segmentan por divisa y producto. Revertidas y patas secundarias
  de Pockets/Depósito no crean movimientos de la cuenta principal.
- Los extractos de patrimonio (`Patrimonio neto.pdf`, valores y cripto) se
  importan como snapshots valorados. No crean compras ni efectivo. Las
  aperturas explícitas conservan coste si el documento lo trae.
- La cartera reconstruye posiciones por FIFO, separa coste conocido,
  desconocido y estimado, y concilia contra el último snapshot. Un coste
  desconocido deja el P&L incompleto; no se sustituye por el precio de mercado.

## Docker (despliegue actual)

El compose usa PostgreSQL externo y secretos fuera del repo:

```bash
# Una sola vez: crea ~/.config/financial-tools/deploy.env (chmod 600)
mkdir -p ~/.config/financial-tools
cp deploy.env.example ~/.config/financial-tools/deploy.env
chmod 600 ~/.config/financial-tools/deploy.env
nano ~/.config/financial-tools/deploy.env

# Reconstruir/recrear backend, worker y frontend
scripts/docker-deploy.sh up -d --build backend import-worker frontend
```

`scripts/docker-deploy.sh` lee `~/.config/financial-tools/deploy.env` y ejecuta
`docker compose --env-file ...`. El entrypoint aplica migraciones antes de
arrancar. El frontend queda en `http://<host>:3000`; el worker procesa la cola
de importaciones en segundo plano.

- Variables del despliegue: [`docs/DEPLOY_ENV.md`](docs/DEPLOY_ENV.md).
- Diseño de la ingesta agéntica: [`docs/AGENTIC_INGESTION.md`](docs/AGENTIC_INGESTION.md).
- Reglas base documentadas: [`docs/CLASSIFICATION_RULES.md`](docs/CLASSIFICATION_RULES.md).
- Golden set inicial: [`golden/manifest.json`](golden/manifest.json);
  ejecutable con `python -m scripts.eval_agentic golden/manifest.json`.

### Admin

No hay usuario seed. Para crear/cambiar el admin:

```bash
scripts/docker-deploy.sh exec -it -e ADMIN_EMAIL=tu@email.com backend \
  python -m scripts.create_admin
```

El admin se crea con `scripts.create_admin` o se actualiza con
`scripts/set_password`. La contraseña inicial se guarda fuera del repo en
`~/.config/financial-tools/admin_password` (chmod 600). El nombre y el email de
acceso se editan en **Ajustes → General → Perfil**. Si cambias el email y tienes
`ADMIN_EMAIL` configurado en Docker, actualízalo o elimínalo para que el
entrypoint no vuelva a crear el usuario antiguo al arrancar.

## PostgreSQL (producción)

```bash
export DATABASE_URL='postgresql+psycopg://usuario:password@host:5432/financial'
alembic upgrade head
```

Antes de tocar producción: backup `pg_dump`, ensayo en una BD sombra y
verificación de conteos (ver `AGENTS.md` §3.4 y §5).

`init_db()` no hace `create_all` en producción: el entrypoint de Docker ejecuta
`alembic upgrade head` y falla rápido si la migración no es válida.

## Tests

```bash
source .venv/bin/activate
pytest -q
python -m compileall -q src scripts

cd frontend-v2
npm run typecheck
npm run lint
npm run build
```

Cobertura actual: **236 tests** backend (auth, migraciones, ingesta agéntica,
dedup, reglas, memoria, Jev/OpenCode Go, API v3 y taxonomía de dos niveles) y
build/lint/typecheck del frontend.

## Estructura

```
src/
  api.py                 # app FastAPI + routers legacy/v3
  api_v3.py              # auth y health v3
  api_v3_data.py         # cuentas, analytics, cartera, imports v3
  auth/                  # Argon2id, sesiones, cookies, CSRF, rate limit
  classify/              # reglas, memoria, pipeline, Jev, referencias por lote
  db/session.py          # engine/session PostgreSQL-first
  ingest/agentic.py      # extractor agéntico CSV/TSV/XLSX/PDF/OCR (OpenCode Go)
  ingest/account_resolver.py  # cuenta automática por IBAN/perfil/evidencia
  ingest/portfolio_snapshot.py # snapshots de patrimonio sin movimientos
  portfolio_service.py   # FIFO, aperturas, coste y conciliación de cartera
  fx.py                  # FX histórico estricto y conversión EUR
  import_worker.py       # worker de la cola persistente de importaciones
  ingest/text.py         # fechas, importes, IBAN, fingerprint
  ingest/                # resolución de cuentas; parser TR solo fixture tests
  ingest_service.py      # import transaccional + dedup
  ai/                    # OpenCode Go, Jev, OCR, schemas, DocumentEnvelope
  models.py              # v1 legacy + v2 + auth/evidencia
alembic/versions/        # baseline v1, v2, v3
scripts/                 # admin, reglas, reset, reimport, eval, entrypoint
frontend-v2/             # UI (el Docker usa esta carpeta)
golden/                  # manifest del golden set; extractos en golden/files/ (ignorado)
docs/                    # plan, estado, API, runbook
```

## Revisión 2026-11-04 (bugs corregidos)

- **Seguridad**: eliminadas las rutas legacy sin autenticación (`/api/documents`,
  `/api/pockets`, `/api/config`, `/api/v2/*`, `/api/imports/*`…). El rewrite de
  Next.js proxya todo `/api/*`, así que eran accesibles sin login. Solo queda
  `/api/v3` (sesión + CSRF).
- **Ingesta**: el extractor conserva el tipo del banco (`CASH_BUY`,
  `CASH_TRANSFER_DIRECT_DEBIT_INBOUND`, `CASH_CARD_PAYMENT`…). Antes todo era
  `AGENTIC_*`: no se neteaban comisiones/impuestos (26 movimientos en
  producción, −41,51 €) y las domiciliaciones con IBAN se clasificaban como
  `Transferencias`.
- `EXCHANGE` → `cambio_divisa`; inferencia de kind por palabra completa
  (`Taxi`≠impuesto, `Coffee`≠comisión, `Pinterest`≠interés); detección de
  banco por palabra (`ING`≠`TRADING`); separadores decimales del mapping,
  signo final y códigos de divisa; columnas `original_amount`/`fx_rate`;
  precio derivado del importe si falta; cadena de saldos en orden descendente.
- **Dedup**: L2 (fingerprint) limitado a la cuenta del extracto; L3 exige
  mismo signo, cuenta y divisa (las dos patas de un traspaso ya no son
  “duplicados”). Confirmar un duplicado (`mismo`) marca el movimiento nuevo
  como `duplicado`: sale de KPIs, saldos y cartera.
- **Conciliación**: el enlace de transferencias internas ya no enlaza por
  importe solo salvo par único entre movimientos de tipo transferencia/tarjeta,
  y nunca toca compras/ventas/dividendos. “Reaplicar patrones” ya no ejecuta
  `backfill_accounts` (reasignaba todos los movimientos a la cuenta broker).
- Reprocesar un import que ya creó movimientos se rechaza (antes duplicaba
  `raw_rows` y, con extracción LLM, movimientos). Un import sin cuenta resuelta
  nunca cae en “la primera cuenta”.
- **KPIs**: importes con signo (un reembolso con kind `gasto` reduce gasto),
  `fee`/`impuesto` cuentan como gasto y el cashflow incluye dividendos e
  intereses igual que el resumen.
- **Cartera**: dividendos = bruto − retención (antes solo la retención);
  conciliación de efectivo solo con las cuentas del snapshot; la ficha de
  activo usa el mismo FIFO que el resumen; % de P&L sobre el coste con P&L.
- **Frontend**: fuera de demo/desarrollo ya no se muestran datos ficticios
  cuando la API falla o tarda; se evitan ids de categorías/cuentas mock.
- **Transferencias siempre en revisión**: ninguna transferencia (propia, pago
  a terceros o Bizum) se autoaprueba (`src/classify/review_policy.py`). Los
  traspasos con cuenta propia resuelta llevan `Transferencias › …` propuesta;
  las de terceros quedan sin categoría. Solo reglas del usuario o decisiones
  manuales las aprueban. Las domiciliaciones y cambios de divisa no cuentan
  como transferencia.
- **Grafana retirado** (estaba expuesto con acceso anónimo en `:3003`).

## Decisiones y límites

- **Jev** decide sobre hechos estructurados; nunca ve PDFs ni imágenes.
- **OpenCode Go** se llama por HTTP desde Python; no hay `opencode serve` ni
  sidecar Node.
- El LLM generativo es fallback; reglas + memoria + broker facts cubren la
  mayoría. `TYPESAFE_API_KEY` activa Jev; sin clave se usa el LLM actual.
- Los ficheros importados viven en `DATA_DIR` (`data/files` por defecto), no en
  la BD.
- Datos personales (DB, CSV, PDFs, `.env`) están en `.gitignore`; no deben
  publicarse.
- Faltan pruebas automatizadas contra PostgreSQL real; el runbook cubre el
  ensayo y la validación manual.
- La app es single-user y la taxonomía es global. No hay aislamiento por
  usuario ni permisos de admin para editar categorías.
- Las categorías de sistema no están bloqueadas frente a renombrado o cambio de
  tratamiento; ver “Límites conocidos” en la sección de Taxonomía y KPIs.

## Documentación

- [`AGENTS.md`](AGENTS.md) — guía operativa actual y protocolo de contexto para agentes.
- [`docs/IMPLEMENTATION_STATUS.md`](docs/IMPLEMENTATION_STATUS.md) — estado y workstreams.
- [`docs/REIMPORT_RUNBOOK.md`](docs/REIMPORT_RUNBOOK.md) — reimportación real, backups y estado de cuentas.
- [`docs/API_V3.md`](docs/API_V3.md) — contrato de API.
- [`docs/AGENTIC_INGESTION.md`](docs/AGENTIC_INGESTION.md) — ingesta agéntica.
- [`docs/MODEL_SETTINGS.md`](docs/MODEL_SETTINGS.md) — modelos, Jev, OCR y límites.
- [`docs/PLAN_2026-10-31.md`](docs/PLAN_2026-10-31.md) — plan histórico; no es el estado actual.
