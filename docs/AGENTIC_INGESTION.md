# Ingesta agéntica de extractos

> **Estado:** fases A (CSV/TSV), B (XLSX), C (PDF con texto y conciliación de
> saldos) y D (imágenes/PDF escaneado con OCR) implementadas. La importación se
> ejecuta en un worker persistente. El pipeline de producción usa
> `agentic_statement` y no tiene dispatcher de parsers por banco. Queda
> pendiente el golden set amplio y afinar la calidad de OCR/PDF.
>
> **Decisión:** agente de extracción con contrato estricto y validación
> determinista. El parser antiguo de Trade Republic queda solo como fixture de
> tests; no se usa en producción.
>
> **Estado de configuración (2026-10-31):** `OPENCODE_API_KEY` y
> `TYPESAFE_API_KEY` configuradas y verificadas con llamadas reales
> (`deepseek-v4.1-flash` y `jev-1.14.0`).

## 1. Problema

El registro actual (`src/ingest/registry.py`) prueba parsers hardcodeados y el
único activo es `TradeRepublicCsvParser`. Cualquier extracto de otro banco o en
PDF falla antes de llegar a normalización. Mantener un parser por banco no
escala: cada formato, idioma, separador decimal, convención de signo y layout
exige código y tests nuevos.

El `DocumentIntakeAgent` de `src/ai/document_agent.py` ya tiene las piezas
deterministas (probe, extracción de texto/tablas, allowlist, conciliación y
validación del `DocumentEnvelope`), pero no está conectado a la importación ni
llama a OpenCode Go.

## 2. Principios

1. **El agente interpreta; el código valida.** El modelo no decide si un
   movimiento es válido ni auto-aprueba nada.
2. **Nada de una llamada por fila.** Para ficheros estructurados el agente
   infiere el mapping con una muestra; el resto se transforma en Python.
3. **Evidencia obligatoria.** Cada fila debe poder señalar página, tabla,
   `raw_text` o `evidence_id`. Sin evidencia, la fila no se acepta.
4. **Sin parser por banco en producción.** Si OpenCode Go no está configurado
   o falla, el import devuelve un error explícito; no se auto-aprueba nada. El
   parser de Trade Republic queda solo como fixture de tests.
5. **Nunca auto-aprobar un documento que no cuadra.** Diferencias de balance,
   fechas inválidas, importes no parseables o baja confianza van a revisión.
6. **Privacidad.** Se redactan IBAN/nombres/direcciones antes de enviar texto
   al modelo cuando sea posible; se prefiere un modelo Go con 0 días de
   retención (`deepseek-v4.1-flash`).

## 3. Arquitectura propuesta

```
Archivo
  │
  ├─ FileProbe (MIME, tamaño, páginas, cifrado)
  │
  ├─ Extractor local
  │    ├─ CSV/TSV: cabecera + muestra + filas
  │    ├─ XLSX: hojas/celdas (openpyxl)
  │    ├─ PDF: texto/tablas (pdfplumber)
  │    ├─ PDF escaneado: render de páginas (pypdfium2/pdfplumber) → imagen
  │    └─ Imagen: bytes → imagen
  │
  ├─ StatementAgent (OpenCode Go, JSON Schema estricto)
  │    ├─ bank / account / period / balances
  │    ├─ column mapping
  │    └─ rows normalizadas + evidencia + confidence
  │
  ├─ Validador determinista
  │    ├─ fechas, Decimal, moneda y signo
  │    ├─ Σ importes == cierre − apertura
  │    ├─ dedup L1/L2/L3 y solapamiento
  │    └─ cuenta destino / transferencias internas
  │
  ├─ process_import (persistencia actual)
  │
  └─ needs_review si algo falla
```

### 3.1 Componentes

| Componente | Responsabilidad |
|---|---|
| `DocumentIntakeAgent` | Probe, extracción de texto/tablas, render, validación de envelope. Se reutiliza. |
| `AgenticStatementExtractor` (nuevo) | Habla con OpenCode Go, valida el JSON y devuelve un `StatementDraft`. |
| `StatementDraft` / `StatementMapping` / `StatementRow` (nuevos) | Contrato Pydantic entre agente y código. |
| `AgenticParser` (nuevo adaptador) | Implementa la interfaz de ingesta y se registra como fuente `agentic_statement`. |
| `process_import` | Sigue siendo el orquestador de raw rows, dedup, cuentas, movimientos, clasificación y activos. |

### 3.2 Contrato del agente

El agente devuelve un único objeto validado con Pydantic (no texto libre):

```json
{
  "document_type": "bank_statement",
  "bank": "revolut",
  "account": {"iban_masked": "ES18...8491", "name": "Revolut"},
  "period": {"start": "2026-01-01", "end": "2026-06-30"},
  "balances": {"opening": 1000.0, "closing": 1200.0, "currency": "EUR"},
  "mapping": {
    "date_column": "Completed Date",
    "amount_column": "Amount",
    "description_column": "Description",
    "merchant_column": "Merchant",
    "currency_column": "Currency",
    "date_format": "dd/mm/yyyy",
    "decimal_separator": ",",
    "thousands_separator": ".",
    "sign_convention": "signed",
    "confidence": 0.97
  },
  "rows": [
    {
      "value_date": "2026-01-09",
      "amount": "-38.06",
      "currency": "EUR",
      "description": "AHORRAMAS",
      "merchant": "AHORRAMAS",
      "kind_hint": "gasto",
      "balance_after": null,
      "raw_text": "09/01/2026 AHORRAMAS -38,06",
      "page": 1,
      "confidence": 0.98
    }
  ],
  "issues": [],
  "confidence": {"overall": 0.96, "extraction": 0.98, "account": 0.95}
}
```

Reglas del contrato:

- `amount` siempre con signo. La convención se declara en `mapping`.
- `value_date` en ISO 8601; el agente declara el formato de entrada.
- `rows` no puede contener filas inventadas: deben tener `raw_text`, `page` o
  `evidence_id`.
- `mapping` solo aplica a fuentes tabulares. Para PDF/imagen, `rows` es la
  salida principal.
- `confidence` es una señal; el validador no la usa como única condición.

## 4. Flujo por formato

### 4.1 CSV / TSV

1. `DocumentIntakeAgent` lee la cabecera y 20–30 filas de muestra.
2. El agente devuelve `StatementMapping` y metadatos del banco.
3. Python aplica el mapping a **todas** las filas, no el LLM.
4. Se validan fechas/importes/saldos y se generan `NormalizedEvent`.

Coste: normalmente **1 llamada por importación**, no una por movimiento.

### 4.2 XLSX

Igual que CSV, pero la extracción local usa `openpyxl` y conserva el nombre de
la hoja y la fila como evidencia. Soporta varias hojas, fórmulas con valor
cacheado y validación de saldo corriente.

### 4.3 PDF con capa de texto/tablas

1. `pdfplumber` extrae texto y tablas por página.
2. Si hay tablas, se usa el camino de mapping tabular.
3. Si no hay tablas pero sí texto, el agente recibe el texto de cada página y
   devuelve filas normalizadas.
4. Se guarda página y `raw_text` como evidencia.

### 4.3.1 Secciones, divisas y snapshots (2026-11-03)

- Las páginas PDF se clasifican por cabecera en `main`, `reversed`,
  `secondary_product` o `portfolio_snapshot`.
- Cada fila hereda la divisa de su sección; no se asume EUR.
- Revertidas, Pockets/Depósito secundarios y secciones vacías no generan
  movimientos de la cuenta principal, pero quedan resumidas en metadata.
- La conciliación agrupa eventos por divisa. El saldo principal se compara solo
  con eventos de su moneda.
- El límite de páginas PDF es 120 para soportar extractos Trade de 50 páginas.
- Los snapshots de patrimonio se detectan localmente y se persisten como
  `portfolio_snapshots`; no pasan por el clasificador ni crean movimientos.
- Los snapshots de apertura conservan cantidad, fecha y coste solo si el
  documento lo declara. Nunca se usa el precio de valoración como coste real.

### 4.4 PDF escaneado / imágenes

1. Se renderiza la página a PNG con `pypdfium2` a `OCR_DPI` (250 por defecto).
2. Tesseract (`spa+eng`) hace OCR local; **no se usa un modelo de visión como
   primario**.
3. El texto OCR se envía a DeepSeek V4.1 Flash con el mismo esquema de filas.
4. El import queda `needs_review` siempre: el OCR puede confundir decimales o
   fechas.
5. Si no hay texto OCR: error explícito y revisión manual.

## 5. Validación determinista

Antes de crear movimientos:

- `value_date` parseable y dentro del periodo declarado.
- `amount` con `Decimal`, moneda de 3 letras y signo coherente.
- `Σ amounts` frente a `closing - opening` con tolerancia 0,01.
- Filas duplicadas dentro del documento y solapamiento con imports previos.
- `transaction_id` si existe; fingerprint si no.
- Cuenta propietaria: la elegida en la importación (`account_id`). El extractor
  devuelve `bank`, `account_name`, `account_iban` y `product`; se validan contra
  la cuenta seleccionada. Un IBAN de otra cuenta conocida o no registrado deja
  el import en `needs_review` sin crear movimientos (`account_match`).
- Si no hay cuentas activas, el import no crea una cuenta genérica: el agente
  propone banco/IBAN/producto/saldo y el usuario confirma la creación en el
  formulario del detalle. Después se reprocesa automáticamente.
- Con varias cuentas activas, el resolvedor busca IBAN/perfil/candidato único;
  `account_id` solo es un override. Una identidad ambigua o nueva requiere
  confirmación atómica.
- Saldo inicial: si el documento trae `opening_balance` con fecha, se aplica a
  una cuenta sin historial o se concilia. La fecha queda en
  `source_files.balance_start_date`.
- Pockets/Depósito no se crean como cuentas. Las secciones secundarias y
  Revertidas se conservan como evidencia y no crean movimientos.
- Transferencias internas: solo si el IBAN/patrón coincide con una cuenta
  propia activa; las dos patas se enlazan en `movement_links` cuando ambas se
  han importado.
- Activos: compra/venta/aporte solo si hay símbolo, cantidad y precio; los
  dividendos pueden no traer precio y se registran con precio 0.

Si algo falla:

- El import se guarda con `status='needs_review'`.
- Las filas válidas pueden persistirse, pero no se auto-aprueban.
- La UI muestra incidencias y evidencia; el usuario decide.

## 6. Persistencia y trazabilidad

Se reutiliza el modelo actual:

- `source_files.source = 'agentic_statement'`.
- `source_files.parser_version = 'agentic-v1'` (el modelo queda en metadata).
- `raw_rows.payload` guarda la fila original o el JSON de evidencia.
- `normalized_events` y `financial_movements` se crean como hoy.
- `source_files.error` guarda el error fatal si no se pudo extraer.
- Las incidencias no fatales se exponen en el detalle de importación.

Fase posterior (si hace falta): tabla `document_evidence` con crops/hash/bbox; no
es necesaria para el primer MVP porque `raw_rows` + `units` ya permiten auditar.

## 7. UI

La pantalla de importación acepta CSV/TSV/XLSX/PDF/imágenes y muestra estado de
cola, resumen, saldos, incidencias y filas dudosas. El selector de cuenta del
extracto sigue siendo explícito.

## 8. Fases de implementación

| Fase | Alcance | Criterio de salida |
|---|---|---|
| A | CSV/TSV genérico: mapping agéntico + transformación determinista | ✅ Import real y tests; sin parser nuevo |
| B | XLSX (OFX/QIF pendientes) | ✅ XLSX multi-hoja y saldo; OFX/QIF aún no |
| C | PDF con texto/tablas + conciliación de saldos | ✅ Filas por página y descuadre detectado; falta afinar recall |
| D | PDF escaneado/imágenes | ✅ OCR local + DeepSeek; `needs_review` obligatorio |
| E | Retirada del parser TR y del registry | ✅ Sin registry/parser en producción; el fichero TR queda como fixture de tests |

## 8.1 Estado implementado (2026-10-31)

- **CSV/TSV:** `AgenticStatementExtractor` infiere el mapping con una muestra y
  aplica la transformación a todas las filas en Python. Probado con el CSV real
  de Trade Republic: **585/585 filas**, incluidos los 51 `FREE_RECEIPT` sin
  importe (como `aporte_activo`). El import completo en SQLite genera 116
  transferencias internas con las cuentas de ejemplo.
- **PDF con texto:** extracción por página con `pdfplumber` y llamadas en
  paralelo (4 workers). Probado con el PDF real de Revolut (6 páginas): ~78–80
  movimientos, periodo y banco detectados, en ~3 minutos.
- **XLSX:** lector `openpyxl` con soporte de varias hojas, fórmulas con valor
  cacheado, mapping por hoja y validación de saldo corriente. Probado con un
  libro real generado y con el agente real.
- **Imágenes/PDF escaneado:** OCR local con Tesseract (`spa+eng`) y
  `pypdfium2`; el texto OCR se interpreta con DeepSeek V4.1 Flash. No se usa
  un modelo de visión como primario. Los imports con OCR quedan siempre en
  `needs_review`.
- **Conciliación:** los PDFs se validan contra `saldo final - inicial` y los
  CSV/XLSX contra la columna de saldo corriente cuando existe. Si no cuadra,
  el import queda en `needs_review` y no se auto-aprueba.
- **Cola:** la API encola el fichero y devuelve `queued`; un worker persistente
  (`src/import_worker.py`) lo procesa. El PDF ya no bloquea la petición HTTP.
- **API:** subida real de un CSV genérico con cabeceras `Fecha;Importe;Concepto`
  a una BD temporal: 201, cola → parsed, 3 movimientos, cuenta asignada.
- **Jev:** clasificación real por lotes; primera tanda sin precedentes, luego
  crece 10/20/... hasta el tope configurable (`JEV_REFERENCE_MAX=40`). Probado
  con aceptación real de un lote y uso de 2 referencias en el siguiente.
- **Tests:** 163 tests backend en verde antes de la última iteración de OCR;
  frontend typecheck/lint/build en verde.

Limitaciones conocidas de esta iteración:

- El OCR de imágenes puede confundir separadores decimales; por eso todo
  import con OCR se marca `needs_review`.
- El PDF de Revolut detecta el descuadre de saldo (78 filas frente al extracto),
  pero la extracción de filas aún puede omitir movimientos. La conciliación lo
  bloquea; falta golden set para medir recall.
- El parser `trade_republic.py` solo se conserva como fixture de tests; no hay
  `registry.py` ni detección por banco en producción.
- Falta un golden set de 20–30 documentos de varios bancos.

## 9. Golden set y aceptación

Harness: `python -m scripts.eval_agentic golden/manifest.json`. Compara filas,
suma, saldos y conciliación. El manifest actual cubre Trade Republic CSV/PDF y
Revolut; faltan 20–30 documentos reales para cerrar la cobertura.

Antes de retirar el parser actual:

- 20–30 documentos etiquetados manualmente (tipo, banco, filas, importes,
  fechas y saldos).
- Métricas: filas detectadas, precision/recall, error de importe, error de
  fecha, conciliación de balance, campos críticos y tasa de revisión.
- Criterio mínimo propuesto: 100 % de filas con evidencia, 0 filas inventadas,
  conciliación correcta en todos los documentos con saldos, y tasa de revisión
  humana < 10 % en los formatos soportados.
- Cualquier documento no soportado debe fallar de forma explícita, nunca
  inventar movimientos.

## 9.6 Clasificación Jev por lotes

La primera tanda no envía precedentes. Cada lote que el usuario acepta añade
ejemplos a `state.precedents`; el bloque crece hasta `JEV_REFERENCE_MAX=40` y
después se seleccionan los ejemplos más similares al movimiento actual. Solo
se usan clasificaciones `origen='user'` (aprobadas), nunca sugerencias de Jev
sin revisar.

- `POST /api/v3/classify/batch` procesa un máximo de 50 movimientos, por
  defecto 10.
- La UI de Movimientos muestra el lote, la categoría sugerida y los botones
  para aceptar/corregir. Aceptar actualiza memoria y referencias.
- Las decisiones con confianza ≥ `auto_approve_threshold` (0,95 por defecto)
  se autoaprueban; solo quedan para revisar las de confianza inferior.
- Las reglas y la memoria se evalúan antes de llamar a Jev; los aciertos
  deterministas de confianza ≥ umbral también se autoaprueban.
- `prompt_version='jev-classify-2.0'` y `reference_count` quedan en la
  explicación/traza.
- Jev no guarda contexto entre llamadas: el contexto es el array que enviamos
  en cada `state`.

## 10. Seguridad y coste

- El texto del documento es **dato no confiable**: no se ejecutan instrucciones
  del PDF ni tool calls sugeridos por el documento.
- Allowlist de herramientas y límites de tamaño/páginas/tokens/iteraciones.
- Modelo por defecto: `deepseek-v4.1-flash` (0 días de retención); fallback
  dentro de OpenCode Go.
- Para CSV/XLSX, una llamada de mapping; para PDF, una llamada por página o
  bloque, no por fila.
- Se registra `usage.opencode.allowance` y el coste por importación.
- No se envían PDFs/imágenes a Jev: Jev solo recibe hechos estructurados y
  redactados para clasificar.

## 11. Variables de entorno necesarias

### Obligatorias para el agente

| Variable | Uso |
|---|---|
| `OPENCODE_API_KEY` | Cliente documental y agente de extracción |
| `TYPESAFE_API_KEY` | Decisor Jev |
| `OPENCODE_MODEL` | `deepseek-v4.1-flash` por defecto |
| `JEV_MODEL` | `jev-latest` por defecto |
| `OCR_LANG` | `spa+eng` |
| `OCR_DPI` | `250` |
| `IMPORT_QUEUE_MODE` | `worker` en Docker |

### Recomendadas

| Variable | Default |
|---|---|
| `OPENCODE_FALLBACK_MODELS` | `glm-5.3-flash,qwen3.8-flash,mimo-v2.6-flash,gpt-6-luna` |
| `JEV_MODEL` | `jev-latest` |
| `JEV_MAX_CALLS_PER_RUN` | `50` |

### Opcionales de ajuste

`OPENCODE_BASE_URL`, `OPENCODE_TIMEOUT`, `OPENCODE_MAX_RETRIES`,
`OPENCODE_BACKOFF`, `OPENCODE_MIN_ALLOWANCE_PCT`, `JEV_BASE_URL`,
`JEV_TIMEOUT`, `JEV_MAX_RETRIES`, `JEV_BACKOFF`.

`LLM_API_KEY`/`LLM_MODEL` siguen siendo el fallback de clasificación actual;
se pueden retirar cuando Jev cubra todo el pipeline. No se deben poner en
`deploy.env`: `DATA_DIR` (lo fija Docker) ni `OPENCODE_SESSION_ID` (se genera
por documento).

## 12. Decisiones cerradas / pendientes

1. ✅ Agente único en producción; el parser TR solo queda como fixture de tests.
2. ✅ CSV/TSV/XLSX/PDF texto/OCR implementados por fases.
3. ⏳ Golden set: faltan 20–30 documentos reales de varios bancos.
4. ✅ Escaneos con OCR local + DeepSeek; no se usa visión de Luna como primaria.

## 13. Referencias

- `src/ai/document_agent.py` — probe, extracción, validación y allowlist.
- `src/ai/schemas.py` — `DocumentEnvelope` y contratos Pydantic.
- `src/ai/opencode_go.py` — cliente HTTP, JSON Schema y fallback.
- `src/ingest/agentic.py` — extractor agéntico.
- `src/import_worker.py` — worker de la cola de importaciones.
- `src/ingest/trade_republic.py` — fixture legacy de tests.
- `docs/PLAN_2026-10-31.md` §5.9 y F4 — diseño original del agente documental.
