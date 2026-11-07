# AGENTS.md — Guía operativa y protocolo de contexto

> **Fecha:** 2026-11-02  
> **Estado:** guía vigente del proyecto. Sustituye al plan histórico que había
> en este archivo. El plan de octubre queda en
> [`docs/PLAN_2026-10-31.md`](docs/PLAN_2026-10-31.md) solo como referencia
> arquitectónica.

Este documento explica **cómo obtener contexto sin leer medio repositorio**,
cuál es el estado real y qué invariantes no se deben romper.

---

## 0. Lo primero que debe hacer un agente

1. Leer este archivo completo.
2. Leer [`README.md`](README.md), sección “Estado actual”, “Datos actuales” y
   “Taxonomía y KPIs”.
3. Consultar [`docs/IMPLEMENTATION_STATUS.md`](docs/IMPLEMENTATION_STATUS.md)
   para el estado operativo y las migraciones.
4. Para tareas de importación/cuentas, leer
   [`docs/REIMPORT_RUNBOOK.md`](docs/REIMPORT_RUNBOOK.md).
5. Para API/contratos, leer [`docs/API_V3.md`](docs/API_V3.md).
6. Solo después, buscar código.

**No usar `docs/PLAN_2026-10-31.md` como estado actual.** Es historia. Tampoco
hay que releerlo entero para tareas normales.

---

## 1. Estado actual resumido (2026-11-04)

| Elemento | Valor |
|---|---:|
| Movimientos | **0** (vaciado 2026-11-04 para reimportar) |
| Importaciones | **0** |
| Cuentas | **1** (Trade Republic) |
| Categorías | **41 (35 activas)** |
| Clasificaciones vigentes | **0** |
| Pendientes de clasificar | **0** |
| Reglas / memoria | **0 / 0** |
| Activos / operaciones / posiciones | **0 / 0 / 0** |
| Migración actual | **`v3_013_import_portfolio`** |
| Backend | FastAPI + SQLAlchemy 2 + PostgreSQL |
| Frontend | `frontend-v2/` (Next.js) |
| Worker | `import-worker` |
| Auth | single-user, login email/password |

Pendiente operativo:

- Importar extractos de Revolut corriente y conjunta; falta el IBAN de la
  conjunta.
- Revisar los 208 movimientos pendientes.
- La cuenta Trade Republic está sin IBAN y con saldo inicial 0 (el CSV no trae
  saldo de apertura).
- No hay aislamiento de taxonomía por usuario.

---

## 2. Mapa de código

```text
src/
  api.py                 # app FastAPI y routers
  api_v3.py              # auth, health, perfil
  api_v3_data.py         # cuentas, analytics, cartera, imports, taxonomía
  v2_api.py              # movimientos, reglas, dedup, tablas
  imports_api.py         # endpoints legacy de importación
  ingest_service.py      # pipeline de importación y mapping broker
  ingest/agentic.py      # extractor CSV/TSV/XLSX/PDF/OCR
  ingest/accounts.py     # cuentas, IBAN, transferencias internas
  ingest/internal_transfers.py
  classify/              # reglas, memoria, pipeline, Jev, LLM
  taxonomy.py            # dos niveles, resolución raíz→hoja
  models.py              # SQLAlchemy
  db/session.py          # engine/session
  import_worker.py       # worker persistente
  ai/                    # OpenCode Go, Jev, OCR, schemas
alembic/versions/        # migraciones; head actual v3_013_import_portfolio
frontend-v2/             # UI vigente; el Docker usa esta carpeta
scripts/                 # deploy, migraciones, seeds, verificación
docs/                    # estado, API, runbooks, ingesta, modelos
```

---

## 3. Protocolo de obtención de contexto

### 3.1 Primero: grafo del código

El proyecto está indexado en `codebase-memory-mcp` como:

```text
home-marcosflz-.dev-Gitea-financial-tools
```

Usar las herramientas MCP **antes** de grep/glob para buscar código:

1. `search_graph` para localizar funciones, clases, endpoints o variables.
2. `trace_path` para ver quién llama o qué llama.
3. `get_code_snippet` para leer una función concreta.
4. `query_graph` para patrones multi-hop o agregaciones.
5. `get_architecture` para una vista general.

Ejemplos:

```text
search_graph(project="home-marcosflz-.dev-Gitea-financial-tools",
             name_pattern=".*Movement.*")

trace_path(project="home-marcosflz-.dev-Gitea-financial-tools",
           function_name="update_movement",
           direction="inbound")

get_code_snippet(project="home-marcosflz-.dev-Gitea-financial-tools",
                 qualified_name="src.v2_api.update_movement")
```

Si el proyecto no está indexado o la herramienta falla, entonces usar
`grep`/`glob` con patrones acotados.

### 3.2 Después: documentación

Orden recomendado:

1. `README.md` — estado actual, datos y decisiones.
2. `docs/IMPLEMENTATION_STATUS.md` — workstreams y migraciones.
3. `docs/REIMPORT_RUNBOOK.md` — cuentas, backups, imports.
4. `docs/API_V3.md` — contratos.
5. `docs/AGENTIC_INGESTION.md` — extractor y OCR.
6. `docs/MODEL_SETTINGS.md` — Jev/OpenCode/OCR.
7. `docs/CLASSIFICATION_RULES.md` — reglas base.
8. `docs/PLAN_2026-10-31.md` — solo si necesitas historia.

### 3.3 Después: código dirigido

- No leer archivos gigantes completos si `search_graph` puede darte la función.
- Para frontend, buscar el componente y luego leer solo su bloque.
- Para migraciones, mirar `alembic heads` y el archivo de la revisión actual.
- Para una tarea de taxonomía, leer siempre:
  - `src/taxonomy.py`
  - sección de categorías de `src/api_v3_data.py`
  - `frontend-v2/src/components/settings/categories-section.tsx`
  - `frontend-v2/src/components/settings/taxonomy-editors.tsx`
  - tests de taxonomía/API.

### 3.4 Base de datos y producción

- Producción: PostgreSQL; credenciales en
  `~/.config/financial-tools/deploy.env` (nunca imprimir secretos).
- Antes de escribir en producción: backup `pg_dump`.
- Consultas de comprobación: solo lectura (`SELECT`).
- No ejecutar migraciones ni resets sin pedir confirmación explícita.
- Los backups están en `~/financial-tools-backups/`.

### 3.5 Validación

Antes de dar una tarea por terminada:

```bash
source .venv/bin/activate
python -m compileall -q src alembic
pytest -q

cd frontend-v2
npm run typecheck
npm run lint
npm run build
```

Si el cambio toca producción:

```bash
scripts/docker-deploy.sh build backend frontend
scripts/docker-deploy.sh up -d --force-recreate backend import-worker frontend
curl -fsS http://localhost:3000/api/v3/health
```

---

## 4. Invariantes de taxonomía y KPIs

### 4.1 Dos niveles

- Raíz + subcategoría plana.
- No se permiten nietos.
- `classification.categoria_id` apunta a la hoja asignable.
- Una raíz con hijas resuelve a su hija `es_default=true` (`Otros`).
- Cada raíz activa tiene `Otros` por defecto.

### 4.2 Tratamiento

- `tratamiento ∈ {normal, transferencia, inversion}`.
- `transferencia` e `inversion` fuerzan `excluir_kpis=true`.
- Las subcategorías heredan tratamiento y exclusión; no se editan por separado.
- Al cambiar una raíz a `normal` sin enviar `excluir_kpis`, se vuelve a incluir
  en KPIs.

### 4.3 Inversiones e Ingresos

```text
Inversiones
├── Compras
├── Ventas          ← antes Ingresos › Beneficios
├── Aportaciones
├── Cashback        ← saveback en activo
└── Otros

Ingresos
├── Nómina
├── Cashback        ← cashback fiat manual
├── Intereses
├── Dividendos
└── Otros
```

- No reintroducir `Ingresos › Beneficios`.
- `inversion_venta` va a `Inversiones › Ventas`.
- `inversion_compra` va a `Inversiones › Compras`.
- `aporte_activo` va a `Inversiones › Aportaciones`.
- `cashback` va a `Inversiones › Cashback` por defecto.
- `dividendo` e `interes` se quedan en `Ingresos`.

### 4.4 KPIs

`_apply_kpi_filters` excluye:

- categorías con `tratamiento` transferencia/inversión;
- categorías con `excluir_kpis=true`;
- `kind ∈ {transferencia_interna, inversion_compra, inversion_venta, aporte_activo}`.

Además excluye `estado='duplicado'` (par confirmado en la cola de dedup).
Ingresos = `ingreso|dividendo|interes|cashback`; gastos = `gasto|fee|impuesto`,
con signo (un reembolso reduce el gasto).

No cambiar esta lógica sin tests de:
- venta no suma ingresos;
- compra no suma gastos;
- transferencia no suma;
- dividendo/interés sí suma si está en Ingresos;
- cashback en Inversiones no suma.

### 4.5 Seguridad de categorías: límites conocidos

Hoy **no** está implementado:

- bloquear renombrado/cambio de tratamiento de `Transferencias`/`Inversiones`;
- mapping por `system_key` (se usa nombre/path);
- taxonomía por usuario (`categorias` no tiene `user_id`);
- permisos admin para editar categorías;
- reserva de nombres `Transferencias`/`Inversiones`.

Si la tarea es “endurecer” esto, el orden recomendado es:

1. bloquear semántica de categorías de sistema;
2. mapear por `system_key`;
3. decidir single-user vs multi-user;
4. si multi-user, añadir `user_id` y semilla por usuario.

---

### 4.6 Importación automática y cartera

- Sin `account_id`, resolver en este orden: IBAN exacto → perfil aprobado →
  banco/producto único → revisión. Nunca caer en la primera cuenta.
- `POST /imports/{id}/confirm-account` es la vía atómica para cuenta nueva o
  asignación; no separar creación y reencolado.
- CSV de broker: `financial_movements.amount` es efectivo neto
  (`amount + fee + tax`); cartera conserva bruto/comisión/impuesto.
- KPIs y patrimonio agregan `amount_eur`; no sumar monedas originales.
- Snapshots de patrimonio no crean compras ni movimientos de efectivo.
- Operaciones, aperturas y valoraciones son hechos distintos. El precio de un
  snapshot no sustituye al coste de adquisición.
- Coste desconocido → P&L incompleto, nunca cero inventado.
- Una incidencia de efectivo de snapshot no se corrige con ajustes automáticos.
- `broker_type` conserva el código del banco con prefijo (`CASH_BUY`,
  `CASH_CARD_PAYMENT`…); compararlo con `base_broker_type()`.
- Dedup L2 es por cuenta; L3 exige mismo signo, cuenta y divisa.
- Las transferencias nunca se autoaprueban (`review_policy.py`): ingesta,
  enlace de traspasos y clasificador las dejan `pendiente`. Solo se propone
  categoría si la otra cuenta es propia. No quitar este guard.
- El enlace de transferencias internas no usa el importe como única evidencia
  salvo par único entre movimientos de tipo transferencia/tarjeta.

## 5. Bases de datos y migraciones

- Head actual: `v3_013_import_portfolio`.
- `v3_011_two_level_taxonomy`: dos niveles, Inversiones/Ventas/Cashback.
- `v3_012_reclass_inv_cashback`: reclasifica datos ya importados.
- `v3_013_import_portfolio`: saldos por divisa, FX EUR, snapshots de
  patrimonio, aperturas de cartera y trazabilidad de cuenta en operaciones.
- El entrypoint de Docker aplica `alembic upgrade head`.
- Para una migración nueva:
  - `alembic revision -m ...`;
  - probar en SQLite temporal;
  - backup PostgreSQL;
  - aplicar en producción;
  - verificar conteos y `depth > 1 = 0`.

No tocar `financial.db` local si existe; está fuera del flujo actual.

---

## 6. Comandos útiles

```bash
# estado y migraciones
.venv/bin/alembic heads
.venv/bin/alembic current

# tests
.venv/bin/pytest -q
.venv/bin/python -m compileall -q src alembic

# frontend
cd frontend-v2 && npm run typecheck && npm run lint && npm run build

# producción
scripts/docker-deploy.sh build backend frontend
scripts/docker-deploy.sh up -d --force-recreate backend import-worker frontend
curl -fsS http://localhost:3000/api/v3/health
```

---

## 7. Reglas para cambios

- Leer el test más cercano antes de modificar una función.
- Mantener compatibilidad con los endpoints v3; los campos nuevos son aditivos.
- No romper la resolución raíz→hoja ni la herencia de tratamiento.
- No cambiar `Ingresos › Beneficios` por la puerta de atrás.
- Los scripts históricos (`seed_rules`, `apply_default_subcategories`,
  `backfill_accounts`, `seed_accounts`, `migrate_v2`, `reassign_taxonomy`,
  `reorganize_taxonomy`, `clean_same_file_dedup`) y el `frontend/` legacy se
  archivaron fuera del repo el 2026-11-04 en
  `~/financial-tools-backups/repo-cleanup-20261104/`. No reintroducirlos.
- Solo existen rutas `/api/v3` autenticadas. No añadir rutas sin
  `require_user`: el frontend proxya todo `/api/*` al backend.
- Usar `scripts/seed_reimport_rules.py` si hay que sembrar reglas.
- Cualquier cambio de esquema, taxonomía o KPI debe actualizar:
  - `README.md`
  - `docs/IMPLEMENTATION_STATUS.md`
  - `docs/API_V3.md` si cambia contrato
  - tests.
- No commitear `.env`, bases de datos, PDFs/CSV personales ni secretos.

---

## 8. Recetas de contexto por tarea

### “Quiero cambiar la tabla de movimientos”

1. `search_graph` para `MovementsView`, `MovementRows`, `update_movement`.
2. Leer `frontend-v2/src/components/movements/movements-view.tsx`.
3. Leer `category-pair-select.tsx` y `movement-filters.tsx`.
4. Revisar `src/v2_api.py` (`_mov_to_dict`, `update_movement`, `bulk_action`).
5. Tests: `test_api_v3_data.py`, typecheck/build.

### “Quiero tocar categorías/KPIs”

1. `src/taxonomy.py`.
2. `src/api_v3_data.py` (`_validate_category_parent`, create/update,
   `_apply_kpi_filters`).
3. `frontend-v2/src/components/settings/`.
4. Tests de taxonomía, migraciones y KPI.
5. Actualizar README/API_V3.

### “Quiero tocar importación/cuentas”

1. `docs/REIMPORT_RUNBOOK.md` y `docs/AGENTIC_INGESTION.md`.
2. `src/ingest_service.py`, `src/ingest/accounts.py`,
   `src/ingest/internal_transfers.py`.
3. `src/imports_api.py` / `src/api_v3_data.py`.
4. Tests de ingesta/reimportación.
5. No resetear producción sin backup.

### “Quiero tocar el frontend”

1. `search_graph` para el componente.
2. Leer `frontend-v2/src/lib/types.ts` y `api.ts` primero.
3. Respetar `withMock`/`DEMO_MODE` si existe.
4. No usar controles nativos del navegador: `useConfirm()` (no
   `window.confirm`), `Select`/`SelectMenu` (no `<select>`), `DatePicker`/
   `DateRangePicker` (no `type="date"`), `ColorField`, `Segmented` para 2–5
   opciones. Las capas flotantes usan `ui/popover.tsx` (portal, fija).
5. «Importar» vive en la barra superior; no repetirlo en las cabeceras.
6. Typecheck + build.

---

## 9. Definición de terminado

- [ ] Tests backend verdes.
- [ ] `compileall` sin errores.
- [ ] Frontend `typecheck`, `lint` y `build` correctos.
- [ ] Migración probada si aplica.
- [ ] Producción con backup y health check si se despliega.
- [ ] README/estado/API actualizados.
- [ ] No se han expuesto secretos ni datos personales.
