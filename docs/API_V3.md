# API v3 — contrato de integración

Todos los endpoints viven bajo `/api/v3`. Autenticación por cookie de sesión
(`ft_session` en dev, `__Host-ft_session` en producción) y CSRF
(`ft_csrf` + cabecera `X-CSRF-Token`) en métodos mutables.

Respuesta de error homogénea:

```json
{ "code": "string", "message": "string", "details": {} }
```

> **2026-11-04**: las rutas legacy sin autenticación (`/api/documents`,
> `/api/pockets`, `/api/config`, `/api/v2/*`, `/api/imports/*`, `/api/assets`,
> `/api/market/*`…) se eliminaron. Solo existe `/api/v3`. `MovementState`
> admite `duplicado` (solo lo asigna la cola de dedup; `PATCH /movements`
> acepta `pendiente|aprobado|rechazado` y `nota: null` borra la nota).

## Auth

| Método | Ruta | Cuerpo | Respuesta |
|---|---|---|---|
| POST | `/auth/login` | `{email, password, remember?}` | `{user}` + cookies |
| POST | `/auth/logout` | — | `{ok: true}` |
| POST | `/auth/logout-all` | — | `{ok: true, revoked: n}` |
| GET | `/auth/me` | — | `{id, email, name, role}` |
| PATCH | `/auth/profile` | `{name?, email?, current_password?}` | `{id, email, name, role}` |
| POST | `/auth/change-password` | `{current_password, new_password}` | `{ok: true}` |
| GET | `/health` | — | `{status, db, alembic, storage, models}` |

Sin sesión, todo lo demás devuelve `401`.

`PATCH /auth/profile` persiste el nombre visible y permite cambiar el email de
acceso; si el email cambia, `current_password` es obligatorio y se valida
contra Argon2id. La sesión actual sigue siendo válida y el nuevo email se usa
en el siguiente login.

## Movimientos

| Método | Ruta | Notas |
|---|---|---|
| GET | `/movements` | Filtros: `estado,kind,origen,categoria_id,subcategoria_id,subtipo,desde,hasta,account_id,q,sort,page,page_size` |
| GET | `/movements/stats` | `{total,pendientes,aprobados,sin_categoria,duplicados}` |
| GET | `/movements/{id}` | Evento, clasificación vigente, fuentes, vínculos, historial |
| PATCH | `/movements/{id}` | `{estado,merchant,nota,categoria_id,subtipo}` |
| POST | `/movements/bulk` | `{ids, action, categoria_id?, subtipo?}` |
| POST | `/classify-next` | `{limit}` |
| POST | `/classify-job` | Devuelve `{job_id}` |
| GET | `/classify-job/{id}` | Estado, progreso, logs |
| POST | `/classify-job/{id}/cancel` | — |

La clasificación vigente de cada movimiento incluye `categoria_id`,
`categoria_path`, `categoria_raiz_id`, `categoria_raiz_nombre`,
`subcategoria_id` y `subcategoria_nombre`. Para una raíz sin subcategoría, los
campos `subcategoria_*` son `null`. `PATCH /movements/{id}` con una raíz
resuelve automáticamente su hija por defecto.

## Taxonomía

| Método | Ruta | Notas |
|---|---|---|
| GET | `/categories` | Árbol plano con `parent_id`, `root_id`, `root_nombre`, `is_subcategory`, `path`, `depth`, `aplica_a`, `tratamiento`, `es_default`, `assignable`, `usage_count`, `usage_total`, `rule_count` |
| POST | `/categories` | `{nombre,parent_id?,aplica_a,tratamiento,color,excluir_kpis,orden,system_key?,descripcion?,activa?}` |
| PATCH | `/categories/{id}` | Edición de cualquier campo; valida ciclos, tipología padre/hijo y nombres únicos |
| DELETE | `/categories/{id}` | Solo si no tiene hijos, clasificaciones, reglas ni memoria; para categorías usadas se archiva con `activa=false` |
| GET | `/tag-groups` | Grupos con sus etiquetas y contadores de uso; incluye `ungrouped` |
| POST/PATCH/DELETE | `/tag-groups…` | CRUD de grupos; al borrar un grupo sus etiquetas quedan sin grupo |
| GET | `/tags?group_id&q` | Lista plana de etiquetas con uso |
| POST/PATCH/DELETE | `/tags…` | CRUD de etiquetas; no se borra una etiqueta en uso |

`aplica_a` es `gasto`, `ingreso` o `ambos`. `tratamiento` es `normal`,
`transferencia` o `inversion`; transferencias e inversiones quedan excluidas de
los KPIs. Las categorías compartidas aparecen en las dos tipologías con el mismo
ID. La jerarquía está limitada a **dos niveles**: raíz y subcategoría. El
`parent_id` de una subcategoría debe apuntar a una raíz, y una raíz con hijas no
puede colgar de otra categoría.

Las subcategorías heredan `tratamiento` y `excluir_kpis` de su raíz. No se puede
crear una subcategoría con un tratamiento distinto ni editar esos campos en la
hija; al cambiar el tratamiento de la raíz se propaga a sus hijas. Si una raíz
pasa de `transferencia`/`inversion` a `normal` sin enviar `excluir_kpis`, se
vuelve a incluir en KPIs (`excluir_kpis=false`); si se envía explícitamente
`true`, se mantiene excluida.

Los nombres pueden repetirse en raíces distintas; la identidad pública es el
`path` completo (`Compras › Otros`). Una categoría con hijas activas tiene
`assignable=false`: si un cliente intenta asignarle un movimiento directamente,
el backend lo redirige a su hija `es_default=true` (normalmente `Otros`). La API
de movimientos devuelve la clasificación resuelta y los campos derivados
`categoria_raiz_id`, `categoria_raiz_nombre`, `subcategoria_id` y
`subcategoria_nombre`.

Mapping determinista de los hechos del broker:

| Kind | Categoría |
|---|---|
| `inversion_compra` | `Inversiones › Compras` |
| `inversion_venta` | `Inversiones › Ventas` |
| `aporte_activo` | `Inversiones › Aportaciones` |
| `cashback` | `Inversiones › Cashback` (saveback en activo) |
| `dividendo` | `Ingresos › Dividendos` |
| `interes` | `Ingresos › Intereses` |
| `transferencia_interna` | `Transferencias › Otros` / `Revolut` |
| `cambio_divisa` | `Transferencias › Otros`, excluido de KPIs |

`Ingresos › Cashback` queda disponible para cashback fiat manual.

## Importaciones

| Método | Ruta | Notas |
|---|---|---|
| POST | `/imports` | `multipart/form-data`, campo `files`; `account_id` opcional (override). Sin cuenta, cada fichero resuelve por IBAN/perfil/candidato único y responde `queued` o `needs_review` |
| GET | `/imports` | Lista con contadores, estado de cola, cuenta y `account_match` |
| GET | `/imports/{id}` | Detalle; incluye `reconciliation_report`, `detected_account`, `account_match`, `account_balance` e incidencias |
| PATCH | `/imports/{id}/account` | Compatibilidad: corrige la cuenta sin movimientos y devuelve a la cola |
| POST | `/imports/{id}/confirm-account` | Operación atómica `{action:"create",account:{...}}` o `{action:"assign",account_id}`; guarda cuenta y reencola |
| GET | `/imports/{id}/movements` | Filas normalizadas |
| GET | `/imports/{id}/reconciliation` | Sumas y diferencias |
| POST | `/imports/{id}/classify` | Clasifica pendientes del import |
| POST | `/imports/{id}/reprocess` | Re-extrae el fichero original (descarta la extracción guardada). Con worker lo reencola y responde `queued`. `409` si el import ya creó movimientos (evita duplicar filas/movimientos) |
| DELETE | `/imports/{id}` | Descarta un fichero que aún no generó datos (en cola, en revisión o fallido). `409` si se está procesando o ya creó movimientos/operaciones/snapshots |
| POST | `/classify/batch` | Lote Jev: `{limit, import_id?, movement_ids?}`; devuelve sugerencias sin aprobar |

La extracción es agéntica (`source='agentic_statement'`): CSV/TSV, XLSX, PDF
con texto y PDF escaneado/imágenes con OCR. Los imports con OCR o descuadre de
saldo quedan en `needs_review`; no se auto-aprueban. `POST /classify/batch`
usa las clasificaciones aceptadas por el usuario como precedentes crecientes
hasta `JEV_REFERENCE_MAX`.

Cada importación valida la identidad detectada (`bank`, `account_name`,
`account_iban`, `product`) contra la cuenta seleccionada. Los estados son
`match`, `match_weak`, `unknown`, `warning`, `mismatch`, `new_account` y
`unsupported_product`. Un `mismatch` o `new_account` no crea movimientos; deja
el import en `needs_review` para corregir la cuenta. Si no hay ninguna cuenta
activa, se permite subir sin `account_id`; el agente propone la cuenta y el
usuario la confirma desde el formulario del detalle. Los Pockets/Depósito de
Revolut no se crean como cuentas: las secciones principales se importan por
divisa, mientras Revertidas y patas secundarias de Pockets/Depósito se ignoran
con trazabilidad.

Los PDF de patrimonio (`source='portfolio_snapshot'`) generan
`portfolio_snapshots` y `portfolio_snapshot_positions`, no movimientos ni
compras. Un snapshot de apertura explícito puede generar
`asset_opening_positions`; el coste solo queda como conocido si el documento lo
declara.

## Cuentas y transferencias

| Método | Ruta | Notas |
|---|---|---|
| GET | `/accounts` | Balance calculado con movimientos + saldo inicial; `include_inactive=true` incluye archivadas |
| POST | `/accounts` | `{nombre,iban?,alias_patrones,tipo,es_propia,color,balance_inicial,balance_inicial_fecha?}` |
| PATCH | `/accounts/{id}` | Edición, incluido `balance_inicial` y `balance_inicial_fecha`; `activo=true` restaura una archivada |
| DELETE | `/accounts/{id}` | Borra si no tiene historial; si lo tiene, archiva (`mode=archived`) |
| POST | `/accounts/{id}/reapply-patterns` | Re-evalúa IBAN/alias de cuentas propias sobre transferencias/tarjeta y enlaza las patas. Nunca cambia `account_id` ni pisa clasificaciones `user` |
| GET | `/transfers/suggestions` | Pares outbound/inbound propuestos |
| POST | `/transfers/link` | `{outbound_id,inbound_id}` |

Cada cuenta devuelve `balances` por divisa (`currency`, `balance`,
`balance_eur`, ancla y fecha) y `balance_eur` agregado. El campo `balance`
histórico se mantiene como agregado EUR compatible. Nunca se suman importes
originales de divisas distintas.

El saldo de una cuenta es `balance_inicial + Σ movimientos.account_id` desde
`balance_inicial_fecha` (si está definida), calculado por divisa. La
cuenta destino de una transferencia interna **no** recibe un abono artificial:
su saldo se calcula cuando se importa su propio extracto. Así no se duplica
dinero al importar las dos cuentas. Las cuentas archivadas no participan en la
detección de transferencias ni se muestran por defecto.

`source_files.balance_start_date` guarda la fecha del saldo de apertura cuando el
extracto la trae. Si la cuenta no tiene historial ni saldo inicial, el import lo
aplica automáticamente. Si ya tiene historial, se concilia contra
`balance_inicial + Σ movimientos anteriores`; una diferencia > 0,01 € deja el
import en `needs_review`.

## Deduplicación

| Método | Ruta | Notas |
|---|---|---|
| GET | `/dedup-candidates` | Cola pendiente |
| POST | `/dedup-candidates/{id}/resolve` | `{resolution: "mismo"|"distinto"}`. Con `mismo`, `movement_a` (el nuevo) pasa a `estado='duplicado'`, se borran sus operaciones de cartera y deja de contar en KPIs y saldos; responde `duplicate_movement_id` |

## Analytics

Las transferencias (`*_TRANSFER_*`, `TOPUP`, kind `transferencia_interna`;
no domiciliaciones) quedan siempre `pendiente` tras importar o clasificar.

Ingresos = kinds `ingreso|dividendo|interes|cashback`; gastos =
`gasto|fee|impuesto`. Los importes llevan signo (un reembolso con kind `gasto`
reduce el gasto). Resumen, cashflow y by-category usan la misma regla y
excluyen `estado='duplicado'`.

| Método | Ruta | Notas |
|---|---|---|
| GET | `/analytics/summary?desde&hasta` | Ingresos, gastos, ahorro, patrimonio |
| GET | `/analytics/cashflow?months=12` | Serie de flujo; acepta `desde`, `hasta`, `granularity=day\|week\|month\|year` y `all=true` para devolver todos los cubos sin recortar a `months`. Rellena cubos vacíos si hay rango explícito. |
| GET | `/analytics/by-category` | Desglose y delta |
| GET | `/analytics/by-merchant` | Top merchants |
| GET | `/analytics/data-health` | Imports, % auto-clasificado, correcciones, cola |
| GET | `/analytics/daily-density` | Heatmap |

## Cartera

| Método | Ruta | Notas |
|---|---|---|
| GET | `/portfolio` | Alias del resumen para el cliente nuevo |
| GET | `/portfolio/summary` | Posiciones, P&L, asignación |
| GET | `/portfolio/assets/{id}` | Activo + `posicion` del mismo motor FIFO que el resumen (añade `pnl_realizado_completo`, `cobertura_coste`, `dividendos`, `incidencias`) |
| GET | `/portfolio/history` | Serie real de snapshots (`date`, `positions_value`, `cash`, `total`); no inventa puntos |

La cartera se calcula con operaciones + aperturas y se concilia contra el
último snapshot. `valor_actual` procede del precio del snapshot; `coste_total`
solo incluye coste demostrado. `cobertura_coste < 1` deja el P&L incompleto.
Las posiciones cerradas no se muestran como activas. Una diferencia de efectivo
del snapshot se devuelve en `cash_difference` (comparando solo con las cuentas
del snapshot) y nunca se ajusta sola. `dividendos` = bruto del evento − retención.

## Reglas y modelos

| Método | Ruta | Notas |
|---|---|---|
| GET/POST/PATCH/DELETE | `/classification-rules` | CRUD + dry-run |
| GET | `/classification-rules/autolearn` | Preview |
| POST | `/classification-rules/autolearn` | Crear seleccionadas |
| GET | `/models` | Jev/OpenCode Go, allowance, retención |
| POST | `/models/test` | Prueba de conectividad sin exponer claves |

> El frontend nuevo (`frontend-v2/`) consume este contrato. Mientras el backend
> no esté completo, usa mocks/empty states y no inventes datos financieros.

## Ajustes de modelos

| Método | Ruta | Notas |
|---|---|---|
| GET | `/settings/models` | Modelo Jev/OpenCode, contexto, lote, llamadas y OCR; indica si las claves están configuradas |
| PATCH | `/settings/models` | Actualiza solo parámetros no sensibles; valida rangos y persiste en `app_config` |

Las API keys no se envían ni se persisten por esta vía. Prioridad de valores:
`app_config` > entorno > default. Ver [`MODEL_SETTINGS.md`](./MODEL_SETTINGS.md).
