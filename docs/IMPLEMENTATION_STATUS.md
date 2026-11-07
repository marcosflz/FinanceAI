# Implementación del plan 2026-10-31

Plan canónico copiado al repo: [`PLAN_2026-10-31.md`](./PLAN_2026-10-31.md).
Estado global: **F0–F5 implementadas y verificadas en local; F6/F7 parciales**.

## Nueva interfaz de importación 2026-11-04

- `/imports` simplificado: subida directa, bandeja de aprobación y gestor de
  archivos. El formulario de cuenta del detalle usa el mismo componente
  (`pending-action-card.tsx`).
- `GET /imports` añade `pending_action`, `size_bytes` y `queue_position`
  (aditivos). Nombre propuesto sin repetir banco (antes «Trade Republic Trade
  Republic») y con pista del nombre del fichero (conjunta/personal).
- `DELETE /imports/{id}` descarta ficheros sin datos generados.
- `reprocess` con worker reencola en vez de bloquear la petición.
- Caché de extracción en cuarentena: aprobar una cuenta ya no repite la
  extracción agéntica (≈4–5 min en un PDF de Revolut).
- Sin migración.

## Revisión de bugs y limpieza 2026-11-04

Implementado en local (sin desplegar; producción sin tocar):

- Seguridad: fuera las rutas legacy sin auth (`src/api.py` solo monta v3);
  eliminados `src/database.py`, `src/app.py`; helpers vivos en `src/db/lookups.py`.
- Ingesta: `broker_type` conserva el código del banco (neteo de comisiones,
  domiciliaciones ≠ traspaso, tarjetas); `EXCHANGE`→`cambio_divisa`; kinds por
  palabra completa; banco por palabra; separadores decimales del mapping;
  columnas de importe original/FX; precio derivado; saldos en orden inverso.
- Dedup L2 por cuenta; L3 con mismo signo/cuenta/divisa; resolución `mismo`
  marca `estado='duplicado'` y lo saca de KPIs/saldos/cartera.
- Transferencias internas: sin enlaces solo por importe salvo par único de tipo
  transferencia/tarjeta; nunca kinds de inversión. `reapply-patterns` seguro
  (`reapply_account_patterns`).
- Reprocesado bloqueado si el import ya tiene movimientos; sin cuenta resuelta
  no se importa.
- KPIs con signo y `fee`/`impuesto`; cashflow coherente con el resumen.
- Cartera: dividendos brutos − retención, efectivo conciliado solo con cuentas
  del snapshot, ficha de activo con FIFO.
- Frontend: sin datos mock fuera de demo/desarrollo; badge `duplicado`;
  errores de reprocesado visibles.
- Limpieza: `frontend/` legacy, scripts históricos, `MIGRATION_RUNBOOK.md`,
  `DESIGN_SYSTEM.md`, copias SQLite y `testing.ipynb` archivados en
  `~/financial-tools-backups/repo-cleanup-20261104/`; extractos personales de
  `docs/` movidos a `golden/files/` (ignorado). `src/dedup.py` reutiliza el
  fingerprint de `src/ingest/text.py`.
- Tests: **274 backend** (+38 en `test_review_fixes.py`), typecheck, lint y
  build correctos.

Pendiente de decisión/operación:

- Datos ya importados en producción: 26 movimientos sin netear (−41,51 €) y
  `broker_type` `AGENTIC_*`; requiere script de reparación con backup.
- ✅ Resuelto: todas las transferencias quedan en revisión; las de terceros
  sin categoría propuesta. Grafana retirado del compose.
- Producción: movimientos vaciados el 2026-11-04 (con backup) para que el
  usuario reimporte manualmente.

## Remate de importación y cartera 2026-11-03

Implementado en local:

- Resolución automática de cuenta sin `account_id`: IBAN, perfil previamente
  aprobado o candidato único; nueva/ambigua queda en revisión.
- `POST /imports/{id}/confirm-account` atómico y formulario frontend de una
  sola confirmación.
- PDF por secciones y divisa; Revertidas y productos secundarios no generan
  movimientos. Límite de 120 páginas para el extracto Trade de 50.
- Efectivo Trade neto (`amount + fee + tax`) sin alterar el bruto de cartera.
- Saldos por cuenta/divisa, `amount_eur`, FX histórico estricto y KPIs sin
  mezclar monedas.
- Conversiones `cambio_divisa` y enlaces internos con importe original
  multidivisa.
- Snapshots de patrimonio y aperturas (`v3_013`), parser local de Patrimonio,
  valores y cripto.
- Motor FIFO, coste conocido/desconocido, P&L parcial y reconciliación contra
  snapshot.
- `/portfolio/summary` usa valor de mercado del snapshot y `/portfolio/history`
  devuelve la serie real de snapshots.

Verificación local: **236 tests backend**, migración `v3_013` sobre SQLite,
`compileall`, typecheck, lint y build frontend correctos.

## Reimportación limpia 2026-11-01

Ejecutada en producción con backup previo
`~/financial-tools-backups/financial_pre_reimport_20261101_205916.dump` y
runbook [`REIMPORT_RUNBOOK.md`](./REIMPORT_RUNBOOK.md).

| Elemento | Resultado |
|---|---:|
| Migración del reimport | `v3_010_reimport_accounts` |
| Migración actual | `v3_013_import_portfolio` |
| Movimientos | **916** |
| Importaciones | 2 CSV de Trade Republic |
| Clasificaciones vigentes | **916** |
| Pendientes | **0** |
| Activos / operaciones / posiciones | **16 / 222 / 16** |
| Saldo Trade Republic | **14.152,20 €** |
| Cuentas | TR + Revolut Cuenta Corriente + Revolut Cuenta Conjunta |
| Reglas | **121** |
| Transferencias internas TR | **87** (sin lado Revolut importado aún) |

- Se conservaron usuarios, categorías, etiquetas, subtipos, `app_config` y la
  cuenta TR con su saldo inicial.
- No se reaplicaron las 901 clasificaciones humanas anteriores: la clasificación
  se reconstruyó desde cero con reglas + heurísticas del broker.
- Se creó `Transferencias › Revolut` y `Transferencias › Bizum`; la raíz
  histórica `Revolut` quedó archivada.
- El resumen y el cashflow excluyen transferencias/inversiones; el resumen
  devuelve `transferencias_netas` / `aportes_netos`.
- La pestaña Transferencias filtra por `tratamiento='transferencia'`, no solo por
  `kind='transferencia_interna'`.
- La importación valida IBAN/banco/producto detectado contra la cuenta
  seleccionada; con varias cuentas activas `account_id` es obligatorio.
- Si no hay cuentas, el import no crea una cuenta genérica: el agente propone
  banco/IBAN/producto/saldo y el usuario confirma desde el formulario del
  detalle; después se reprocesa automáticamente.
- El enlace de transferencias internas se ejecuta al final de cada importación;
  el script `link_internal_transfers` queda solo como reparación manual.
- El saldo inicial del extracto se aplica o concilia automáticamente.
- Las cuentas Revolut están creadas; falta importar sus extractos y completar el
  IBAN de la conjunta. Pockets/Depósito no son cuentas en esta fase.

### Estado actual (2026-11-02)

Después de la limpieza, el usuario subió un extracto de Trade Republic
(`transactions_2026-05-01_2026-10-31.csv`). El estado real es:

| Elemento | Valor |
|---|---:|
| Movimientos / importaciones / activos | **535 / 1 / 14** |
| Cuentas | **1** (Trade Republic) |
| Categorías | **41 (35 activas tras `v3_011/v3_012`)** |
| Etiquetas / grupos | **4 / 2** |
| Usuarios | **1** |
| Reglas / memoria | **0 / 0** |
| Clasificaciones vigentes / pendientes | **327 / 208** |

Se conservaron expresamente las categorías creadas, etiquetas, subtipos,
`app_config` y usuarios. Las clasificaciones deterministas ya importadas se
reclasificaron con `v3_012` (`Compras`, `Aportaciones`, `Cashback` de
Inversiones). El siguiente paso es revisar los 208 pendientes normales.
Backups: `~/financial-tools-backups/financial_pre_clean_reupload_20261101_215425.dump`,
`~/financial-tools-backups/financial_pre_taxonomy_20261102_131047.dump` y
`~/financial-tools-backups/financial_post_taxonomy_20261102_132942.dump`.

### Taxonomía de dos niveles 2026-11-02

- Migraciones `v3_011_two_level_taxonomy` y
  `v3_012_reclass_inv_cashback`.
- La jerarquía queda limitada a **raíz + subcategoría plana**; la API rechaza
  nietos y el árbol de Ajustes solo permite añadir hijas a una raíz.
- Las subcategorías heredan `tratamiento` y `excluir_kpis`; no se pueden cambiar
  de forma independiente.
- Al cambiar una raíz de `transferencia`/`inversión` a `Normal`, se desmarca
  automáticamente `Excluir de KPIs`; si se quiere mantener excluida, se puede
  volver a marcar. En subcategorías el control está deshabilitado y se edita en
  la raíz.
- `Ingresos › Beneficios` se mueve y renombra a `Inversiones › Ventas`.
- `Inversiones` incorpora `Compras`, `Ventas`, `Aportaciones`, `Cashback` y
  `Otros`.
- `Cashback` queda duplicado: `Inversiones › Cashback` es el destino
  determinista del saveback en activo; `Ingresos › Cashback` queda para
  cashback fiat manual.
- La bandeja `/movements` muestra dos columnas (`Categoría` y `Subcategoría`) y
  los filtros permiten raíz/subcategoría; el detalle de importación también
  separa ambas.
- Los KPIs excluyen por `kind` las compras/ventas de inversión y las
  transferencias internas, además de por tratamiento de categoría.
- Tests: 197 pasan y el frontend pasa `typecheck`.
- Migración `v3_012_reclass_inv_cashback`: reasigna clasificaciones
  deterministas ya importadas (`Inversiones › Otros` → Compras/Aportaciones y
  `cashback` → Inversiones › Cashback) sin pisar decisiones humanas.

## Línea base (antes de tocar código)

| Elemento | Estado |
|---|---|
| BD local | SQLite `financial.db`, 585 movimientos v2, 152 legacy, 407 pendientes |
| Revisión Alembic local | `bda3fcb75c3f`; `alembic upgrade head` fallaba en `v2_002` |
| Migraciones | `v2_002` y `v2_003` reparadas; upgrade probado en copia `/tmp` hasta `3e7a1d9f8c5c` |
| PostgreSQL | Producción externa vía `DATABASE_URL`; sin credenciales en `.env` |
| Tests | `pytest` pasa 23 tests existentes (solo `market`); cobertura v2 casi nula |
| Frontend | `frontend/` existente; se construye el nuevo en `frontend-v2/` |

## Workstreams

| Workstream | Alcance | Archivos principales | Estado |
|---|---|---|---|
| Backend F0 | Config, PostgreSQL pool, modelos, migración v3, auth, Docker | `src/config.py`, `src/db/session.py`, `src/models.py`, `src/auth/`, `src/api_v3.py`, `alembic/versions/` | Completado |
| Perfil editable 2026-11-01 | Nombre visible, cambio de email con contraseña actual y cambio de contraseña | `src/models.py`, `src/api_v3.py`, `alembic/versions/v3_005_user_profile.py`, `frontend-v2/src/components/settings/general-section.tsx` | Completado |
| Taxonomía 2026-11-01 | Árbol de categorías editable, tipología gasto/ingreso, nodos compartidos, grupos de etiquetas y CRUD en Ajustes | `alembic/versions/v3_006_taxonomy_tree_tags.py`, `src/models.py`, `src/api_v3_data.py`, `frontend-v2/src/components/settings/categories-section.tsx`, `category-tree.tsx`, `tag-taxonomy.tsx`, `taxonomy-editors.tsx` | Completado |
| Subcategorías por defecto 2026-11-01 | `Otros` obligatorio en cada raíz, `Beneficios` con Cashback/Intereses/Beneficios/Dividendos, paths únicos y resolución automática de padre a `Otros` | `alembic/versions/v3_007_default_subcategories.py`, `src/taxonomy.py`, `src/classify/*`, `scripts/apply_default_subcategories.py` | Completado |
| Taxonomía de dos niveles 2026-11-02 | Raíz + subcategoría plana, herencia de tratamiento, Ventas/Compras/Aportaciones/Cashback en Inversiones, dos columnas en revisión | `alembic/versions/v3_011_two_level_taxonomy.py`, `src/taxonomy.py`, `src/api_v3_data.py`, `src/v2_api.py`, `frontend-v2/src/components/movements/` | Completado |
| Ingesta F1–F2 | Cuentas/IBAN, `account_id`, transferencias, dedup, reglas, rendimiento | `src/ingest*`, `src/classify/*`, `src/dedup.py`, `src/imports_api.py`, `scripts/seed_accounts.py` | Completado (import 585 ≈ 1 s) |
| Cuentas explícitas 2026-10-31 | Cuenta elegida al importar, borrado/archivado y restauración, saldo por extracto | `src/ingest_service.py`, `src/api_v3_data.py`, `frontend-v2/src/components/accounts/`, `frontend-v2/src/components/imports/` | Completado |
| Ingesta agéntica (F4) | Agente documental + validación determinista; CSV/TSV/XLSX/PDF texto/OCR; cola worker | `src/ai/`, `src/ingest/agentic.py`, `src/ingest/text.py`, `src/import_worker.py`, `docs/AGENTIC_INGESTION.md` | Fases A–D, golden set pendiente |
| IA F3–F4 | Cliente OpenCode Go, Jev, esquemas y orquestador | `src/ai/`, `src/classify/decider.py` | Completado (clientes + integración Jev) |
| Frontend F5 | Scaffold nuevo, login, shell, pantallas base | `frontend-v2/` | Completado (build/lint/typecheck OK) |
| Integración/QA | Revisión, migración real, backfill, tests E2E, docs | repo completo | Completado en local |

## Resultado local (2026-10-31)

| Métrica | Resultado |
|---|---:|
| Tests backend | **179 passed** |
| Frontend | typecheck/lint/build OK (10 rutas) |
| Migración local | `v3_009_income_children` (head) |
| Movimientos | **916 (2 imports reales)** |
| `account_id` NULL | **0** |
| Transferencias internas | **0 (solo 1 cuenta activa)** |
| Movimientos sin categoría | **129** |
| Pendientes de aprobación | **127** (la mayoría sin categoría; Jev puede resolverlos) |
| Reglas | **0 (sin sembrar; documentadas en `CLASSIFICATION_RULES.md`)** |
| Import 585 filas (prueba anterior) | **≈0,9–1,1 s** |
| Reimport idempotente | probado en temp DB: 0 nuevos / 585 vistos |
| API v3 | auth, movimientos, imports, cuentas, analytics, cartera, reglas, dedup |
| Servidor local probado | frontend 18010 → rewrite → backend 8010 |
| **PostgreSQL producción** | **v3_009; 916 movs; 37 categorías (10 raíces activas, 10 `Otros` por defecto); 2 grupos de etiquetas; 0 reglas; 1 cuenta activa; 1 usuario** |
| Docker desplegado | backend + frontend + `import-worker`; UI en `:3000` |
| Login real | `admin@example.com` verificado vía `:3000/api/v3/auth/login` |

## Decisiones ya cerradas

- Decisor: **Jev** (`POST https://api.typesafe.ai/v1/systemone`, `jev-latest`).
- Documentos: **DeepSeek V4.1 Flash** por defecto; fallback dentro de OpenCode Go.
- Sin OpenRouter, sin agente OpenCode embebido, sin Laya.
- Auth email/password; sin 2FA por ahora.
- PostgreSQL es el despliegue real; SQLite solo dev/tests.
- Frontend nuevo, no se reutiliza el diseño actual.
- Las cuentas son **explícitas**: se elige la cuenta al importar el extracto.
  No se crean cuentas de contrapartes automáticamente. El saldo de una cuenta
  es saldo inicial + movimientos propios; la cuenta destino de una transferencia
  interna no recibe abono hasta importar su extracto.
- `DELETE /accounts/{id}` borra si no hay historial; si lo hay, archiva y se
  puede restaurar con `PATCH {activo:true}`.

## Integración realizada

1. ✅ Revisión de los cuatro workstreams e integración de imports/choques.
2. ✅ `pytest` 163, `compileall`, migración sobre copia y build del frontend.
3. ✅ Migración y backfill aplicados a `financial.db` local (con backup):
   - 585 movimientos con `account_id`;
   - 122 transferencias internas;
   - 0 movimientos sin categoría;
   - reimport idempotente;
   - clasificación sin `NameError`.
4. ✅ Auth: 401 sin sesión, login/logout, CSRF, rate limit, cookies; probado con TestClient y servidor real.
5. ✅ `frontend-v2` conectado al backend (rewrite `/api`) y validado por HTTP.
6. ✅ PostgreSQL real: migración `v3_003_asset_tx_tipo`; import real de 585 filas reparado tras ampliar `asset_transactions.tipo`.
7. ✅ Admin creado (`admin@example.com`) y login real verificado en `:3000`.
8. ✅ `frontend/` legacy archivado fuera del repo (2026-11-04).
9. ⏳ F6: posiciones de apertura/FIFO completo; F7: CI/E2E/backups/observabilidad.
10. ✅ Cuentas: la cuenta del extracto se elige al importar; borrado seguro
    (archivado si hay historial) y restauración; sin auto-seed de contrapartes.
11. ✅ Ingesta agéntica CSV/TSV/XLSX + PDF texto + OCR imágenes/escaneos;
    sin registry/parser por banco en producción. Probado con CSV real TR
    (585 filas), XLSX real, PDF Revolut (6 páginas), API real y Jev.
12. ✅ Cola de importación persistente (`source_files` queued/processing y
    worker Docker) y conciliación de saldos PDF/CSV/XLSX.
13. ✅ Clasificación por lotes Jev con referencias crecientes (0 → 10 → 20…,
    tope `JEV_REFERENCE_MAX=40`).
14. ✅ Ajustes de modelos en caliente: contexto Jev, tamaño de lote, límite
    de llamadas, umbral de autoaprobación (95 % por defecto), modelo
    OpenCode/fallback y OCR. Ver [`MODEL_SETTINGS.md`](./MODEL_SETTINGS.md).
15. ✅ Cuentas con saldo inicial + fecha; el saldo solo suma movimientos desde
    la fecha indicada.
15. ✅ Dedup L3 solo entre ficheros importados distintos; los repetidos
    legítimos del mismo extracto ya no aparecen en la cola de duplicados.
    Los movimientos autoaprobados no se muestran en las colas de revisión.
16. ✅ Selector de periodo del dashboard (mes, mes anterior, 3 meses, año y
    rango personalizado) conectado a resumen, cashflow y categorías.
17. ⏳ Golden set de 20–30 documentos y ajuste fino de OCR/PDF. Ver
    [`AGENTIC_INGESTION.md`](./AGENTIC_INGESTION.md).
18. ✅ Taxonomía base: árbol editable con `parent_id`, tipología
    gasto/ingreso/ambos, tratamiento normal/transferencia/inversión;
    Transferencias, Inversiones y Otros son nodos compartidos. Etiquetas
    agrupadas (`Recurrencia`, `Viajes`) y CRUD completo en Ajustes.
19. ✅ Reasignación de taxonomía con preview (`scripts/reassign_taxonomy.py`):
    - 10 cashback de `Salario` → `Otros ingresos › Cashback`.
    - 4 movimientos de `Alimentación` → `Alimentación › Alimentación general`.
    - 4 entradas de memoria actualizadas; las clasificaciones anteriores quedan
      versionadas con `vigente=false`. `Revolut` sigue pendiente.
20. ✅ Reorganización 2026-11-01 (`scripts/reorganize_taxonomy.py`):
    - `Alimentación` pasa a colgar de `Compras`.
    - `Bares y Restaurantes` pasa a colgar de `Ocio`.
    - 94 movimientos de `Supermercado` y `Alimentación general` → `Alimentación`;
      30 memorias actualizadas.
    - `Supermercado` y `Alimentación general` quedan archivadas; la UI las oculta
      salvo que se active «Ver archivadas».
21. ✅ Subcategorías por defecto (`v3_007` + `scripts/apply_default_subcategories.py`):
    - Cada raíz activa tiene una hija `Otros` con `es_default=true`.
    - `Beneficios` agrupa Cashback (10), Intereses (10), Beneficios por venta (10)
      y Dividendos (11); `Otros` queda como fallback.
    - 717 clasificaciones movidas de raíces a hojas: 686 a `Otros` y 31 a
      `Beneficios` (11 dividendos, 10 intereses, 10 ventas). Las raíces quedan
      sin clasificaciones directas.
    - La API redirige cualquier asignación a una raíz hacia su `Otros`; el
      frontend solo ofrece hojas asignables en los selectores de movimiento.
22. ✅ Ingresos final (`v3_008` + `v3_009_income_children`):
    - Nueva raíz `Ingresos` con `Otros` por defecto.
    - `Salario` renombrado a `Nómina`.
    - `Cashback`, `Intereses`, `Beneficios` y `Dividendos` cuelgan directamente
      de `Ingresos`.
    - La agrupadora intermedia `Beneficios` y su `Otros` se eliminaron; la hoja
      `Beneficios` (venta de activo) queda directamente en `Ingresos`.
23. ✅ Taxonomía de dos niveles (`v3_011_two_level_taxonomy`):
    - `Ingresos › Beneficios` pasa a `Inversiones › Ventas`.
    - `Inversiones` incluye `Compras`, `Ventas`, `Aportaciones`, `Cashback` y
      `Otros`; `Cashback` también se conserva en `Ingresos` para fiat.
    - Se aplanan los nodos de tercer nivel y se propaga el tratamiento a las
      subcategorías.
    - `/movements` y `/imports/{id}` muestran `Categoría` + `Subcategoría`.
    - El antiguo `Otros` de Nómina queda archivado: Nómina es una hoja.

## Comandos útiles

```bash
source .venv/bin/activate
python -m pytest -q
python -m compileall -q src

# Migración sobre copia, nunca sobre financial.db directamente
cp financial.db /tmp/ft_migration_test.db
DATABASE_URL=sqlite:////tmp/ft_migration_test.db alembic upgrade head

# Import de prueba sobre copia
cp financial.db /tmp/ft_import_test.db
DATABASE_URL=sqlite:////tmp/ft_import_test.db python -m scripts.seed_accounts
```

## Bloqueos / pendientes operativos

- **PostgreSQL producción**: migrado a `v3_005_user_profile`; 916 movimientos en 2 imports. Backup previo al perfil: `/tmp/financial_pg_backup_profile_20261101_133248.dump` (419 KB); backups anteriores al import: `/tmp/financial_pg_backup_20261031_183301.dump` (307 KB) y `/tmp/financial_pg_backup_20261031_200530.dump` (414 KB). Falta probar restore y automatizar backups.
- **Admin**: creado `admin@example.com`; contraseña aleatoria en `~/.config/financial-tools/admin_password` (chmod 600). Cambiar por el email/clave definitivos.
- **Secretos de despliegue**: `~/.config/financial-tools/deploy.env` (chmod 600), fuera del repo. `scripts/docker-deploy.sh` lo usa.
- OpenCode Go y Jev están configurados y verificados con llamadas reales; los tests unitarios siguen usando dobles.
- `frontend-v2` está instalado, compila y ya se sirve en Docker `:3000`; `frontend/` legacy sigue en el repo como referencia y ya no lo usa Docker.
- F6/F7: posiciones de apertura/FIFO completo, E2E Playwright, CI de migración PostgreSQL real, backups automáticos y observabilidad.
