# Runbook de reimportación limpia (2026-11-01)

> Estado: **ejecutado en producción** el 2026-11-01.
> Backup previo: `~/financial-tools-backups/financial_pre_reimport_20261101_205916.dump`.
> Backup posterior: `~/financial-tools-backups/financial_post_reimport_20261101_213025.dump`.
> Snapshot de referencia: `~/financial-tools-reimport/20261101/snapshot_reference.json`.
> Ficheros originales: `~/financial-tools-reimport/20261101/files/`.

## 1. Resultado

| Elemento | Resultado |
|---|---:|
| Migración del reimport | `v3_010_reimport_accounts` |
| Migración actual | `v3_013_import_portfolio` |
| Movimientos | **916** (585 + 331; 204 vistos en solape) |
| Importaciones | 2 |
| Cuentas | TR + Revolut Cuenta Corriente + Revolut Cuenta Conjunta |
| Clasificaciones vigentes | **916** |
| Pendientes de clasificar | **0** |
| Clasificaciones en raíz | **0** |
| Activos / operaciones / posiciones | **16 / 222 / 16** |
| Saldo Trade Republic | **14.152,20 €** |
| Reglas de clasificación | **121** |
| Etiquetas | Korea 2026, Fijo, Variable, **Ahorro** |
| `movement_links` internos | 0 (aún no se ha importado el lado Revolut) |
| Transferencias internas TR | **87** (70 + 17), todas con cuenta destino |
| Categorías de transferencia | Revolut 87 · Otros 178 · Bizum 1 |

La cuenta **Revolut Cuenta Conjunta** se creó sin IBAN. Se completará
automáticamente cuando se importe su extracto: el extractor detecta el IBAN y
el validador lo guarda en la cuenta seleccionada.

## 1.1 Estado actual (2026-11-02)

La limpieza inicial dejó la base en 0 movimientos/0 cuentas. Después se
importó `transactions_2026-05-01_2026-10-31.csv` de Trade Republic y la
taxonomía ya está migrada:

| Elemento | Valor |
|---|---:|
| Movimientos / importaciones / activos | **535 / 1 / 14** |
| Cuentas | **1** (Trade Republic) |
| Categorías | **41 (35 activas tras `v3_011/v3_012`)** |
| Etiquetas / grupos | **4 / 2** |
| Usuarios | **1** |
| Reglas / memoria | **0 / 0** |
| Clasificaciones vigentes / pendientes | **327 / 208** |
| Transferencias | 183 en `Transferencias › Otros` (falta importar Revolut para enlazar) |

Backups:
`~/financial-tools-backups/financial_pre_clean_reupload_20261101_215425.dump`,
`~/financial-tools-backups/financial_pre_taxonomy_20261102_131047.dump` y
`~/financial-tools-backups/financial_post_taxonomy_20261102_132942.dump`.

El flujo actual (2026-11-03) es: subir extractos sin cuenta → cada fichero
resuelve por IBAN, perfil aprobado o candidato único → solo una identidad nueva
o ambigua queda en `needs_review` → `confirm-account` crea/asigna la cuenta y
reencola en una transacción → los siguientes extractos de esa cuenta entran
automáticamente. Los snapshots de patrimonio se importan como valoraciones y
nunca crean compras.

`v3_013_import_portfolio` añade saldos por divisa, snapshots,
aperturas y FX. Antes de aplicarla en producción: backup, ensayo en PostgreSQL
sombra y verificación de cuentas, movimientos, activos y snapshots.

## 2. Qué se conservó y qué se borró

Se conservaron:

- usuarios, sesiones y login;
- categorías, etiquetas, grupos, subtipos y `app_config`;
- la cuenta Trade Republic, su IBAN y su saldo inicial (`11.375,93 €` /
  2026-01-01);
- los ficheros originales, copiados fuera del volumen antes del reset.

Se borraron y reconstruyeron:

- movimientos, eventos, filas crudas e importaciones;
- clasificaciones, memoria y reglas;
- activos, operaciones y snapshots de posición;
- pockets y tablas legacy.

**No se reaplicaron** las 901 clasificaciones humanas antiguas: el plan decidió
empezar de cero. El snapshot sirve solo para auditoría/comparación.

## 3. Secuencia ejecutada

```bash
# 1. Copia de seguridad y ficheros
pg_dump -Fc ... > ~/financial-tools-backups/financial_pre_reimport_20261101_205916.dump
docker cp financial-tools-backend:/data/files/. \
  ~/financial-tools-reimport/20261101/files/

# 2. Parada de servicios
scripts/docker-deploy.sh stop backend import-worker frontend

# 3. Migración + reset (el entrypoint aplica Alembic)
scripts/docker-deploy.sh run --rm --no-deps backend \
  python -m scripts.reset_v2 --yes --keep-accounts \
  --keep-account-balances --no-rules

# 4. Cuentas y reglas
scripts/docker-deploy.sh run --rm --no-deps backend \
  python -m scripts.bootstrap_reimport_accounts
scripts/docker-deploy.sh run --rm --no-deps backend \
  python -m scripts.seed_reimport_rules

# 5. Importación de los dos CSV de Trade Republic
scripts/docker-deploy.sh run --rm --no-deps backend \
  python -m scripts.reimport_files --manifest /data/reimport/manifest.json

# 6. Verificación
scripts/docker-deploy.sh run --rm --no-deps backend \
  python -m scripts.verify_reimport \
  --expected-tr-movements 916 --expected-assets 16 \
  --expected-asset-transactions 222

# 7. Arranque
scripts/docker-deploy.sh up -d backend import-worker frontend
```

## 4. Atribución de cuenta

Cada importación guarda:

- `source_files.account_id`: cuenta elegida;
- `normalized_events.source_account_id`: cuenta del evento;
- `financial_movements.account_id`: cuenta del movimiento;
- `financial_movements.account_destino_id`: cuenta propia destino, si es
  transferencia interna;
- `source_files.extraction_meta.detected`: banco, titular, IBAN y producto
  detectados;
- `source_files.extraction_meta.account_match`: `match`, `match_weak`,
  `unknown`, `warning`, `mismatch`, `new_account` o `unsupported_product`.

Reglas:

- Con más de una cuenta activa, `account_id` es obligatorio.
- Si el IBAN detectado pertenece a otra cuenta conocida: **no se importa**;
  queda `needs_review` y se puede corregir con
  `PATCH /api/v3/imports/{id}/account`.
- Si el IBAN no existe y la cuenta seleccionada no tiene IBAN, se acepta como
  `match_weak` y se completa el IBAN de la cuenta.
- Si el extracto no identifica banco/IBAN, se usa la cuenta seleccionada y se
  marca aviso (`unknown`).
- Pockets/Depósito no se crean como cuentas. El extractor separa las secciones:
  Cuenta principal se importa; Revertidas y patas secundarias se registran como
  evidencia y no como movimientos.

## 5. Saldo inicial

- Si el extracto trae saldo inicial y la cuenta no tiene movimientos ni saldo
  inicial, se aplica automáticamente con la fecha del extracto.
- Si la cuenta ya tiene historial, se concilia contra
  `balance_inicial + Σ movimientos anteriores`; si no cuadra, `needs_review`.
- Si el extracto no trae saldo inicial (Trade Republic CSV), se conserva el
  saldo actual de la cuenta.
- `source_files.balance_start_date` solo se rellena cuando hay saldo inicial.

## 6. Importar Revolut (pendiente)

### Arranque desde cero

Si no hay ninguna cuenta activa:

1. Sube el extracto sin seleccionar cuenta.
2. El agente extrae banco, titular, IBAN, producto y saldo inicial.
3. No se crea ninguna cuenta genérica ni se inventan movimientos: el import
   queda en `needs_review` con `account_match.status = new_account`.
4. En el detalle de `/imports/{id}` aparece el formulario
   **“Configurar la cuenta del extracto”**, con los datos detectados
   precargados.
5. Confirma una cuenta existente o crea la detectada. Al guardar, el import
   vuelve a la cola y se reprocesa automáticamente.
6. A partir de ahí, los siguientes extractos del mismo IBAN se asignan solos y
   las transferencias internas se enlazan al terminar cada importación.

### Importar cuentas existentes

1. Exportar preferentemente **CSV** de la Cuenta Corriente y de la Cuenta
   Conjunta. Si se usa PDF, separar las secciones de Cuenta, Pockets y Depósito.
2. En `/imports`, seleccionar explícitamente la cuenta:
   - `Revolut Cuenta Corriente`;
   - `Revolut Cuenta Conjunta` (la primera importación completa su IBAN).
3. Subir el extracto. Revisar en el detalle:
   - cuenta seleccionada vs detectada;
   - saldo inicial/final y fecha;
   - conciliación;
   - incidencias.
4. Si aparece `needs_review` por cuenta:
   - corregir la cuenta en el detalle y reprocesar;
   - o crear la cuenta detectada y reimportar.
5. **El enlace es automático** al procesar el segundo extracto: `process_import`
   ejecuta `link_internal_transfers` al final y crea los `movement_links` de las
   patas TR ↔ Revolut. El script manual solo es necesario para reparar datos
   históricos o tras cambiar patrones/IBAN:
   ```bash
   scripts/docker-deploy.sh run --rm --no-deps backend \
     python -m scripts.link_internal_transfers
   ```
6. Revisar los traspasos a Pockets/Depósito: se clasifican como
   `Transferencias › Otros` + etiqueta `Ahorro`, sin contarse como gasto.

## 7. Verificación y rollback

Comprobaciones mínimas:

- `financial_movements.account_id IS NULL` = 0;
- `source_files.account_id IS NULL` = 0;
- una sola clasificación vigente por movimiento;
- 0 clasificaciones en raíz;
- saldo TR = 14.152,20 €;
- activos 16 / operaciones 222 / posiciones 16;
- transferencias internas con `account_destino_id`;
- dedup sin candidatos entre patas internas.

Rollback:

```bash
scripts/docker-deploy.sh stop backend import-worker frontend
pg_restore --clean --if-exists --no-owner --no-acl -d "$DATABASE_URL" \
  ~/financial-tools-backups/financial_pre_reimport_20261101_205916.dump
# restaurar /data/files desde ~/financial-tools-reimport/20261101/files
scripts/docker-deploy.sh up -d backend import-worker frontend
```

Las imágenes anteriores quedaron etiquetadas como
`financial-tools-backend:pre-reimport-20261101` y
`financial-tools-frontend:pre-reimport-20261101`.

## 8. Decisiones pendientes

- `DIGI`: `Servicios › Otros` por ahora.
- `Bizum`: la regla genérica solo aplica cuando la descripción contiene
  “Bizum”; las transferencias a personas sin esa palabra quedan en
  `Transferencias › Otros`.
- `Aportes netos`: el resumen ya devuelve `transferencias_netas` /
  `aportes_netos`; falta exponerlo en el dashboard si se quiere.
- Pockets/Depósito: no son cuentas; etiqueta `Ahorro` propuesta.
