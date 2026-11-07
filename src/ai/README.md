# Capa de IA (`src/ai`)

Clientes Python directos para los dos cerebros del proyecto:

- **OpenCode Go** (`opencode_go.py`): modelos documentales por HTTP, sin
  `opencode serve`, sin Node y sin OpenRouter.
- **Jev / TypeSafe** (`jev.py`): decisor tipado con probabilidades calibradas.

Alrededor de ellos:

- `decision.py`: `DecisionOrchestrator`, umbrales del plan y cache por
  `SHA-256(state + questions)`.
- `schemas.py`: contratos Pydantic v2 (`LLMResult`, `Usage`, `Allowance`,
  `DecisionQuestion`, `DecisionResult`, `DocumentEnvelope`).
- `document_agent.py`: esqueleto determinista del agente documental (`FileProbe`,
  allowlist de tools, validación de evidencia y conciliación de balance).

> **Configuración:** esta capa lee `os.getenv` con defaults para no bloquear F3/F4.
> Queda pendiente integrar estas variables en `src/config.py` (pydantic-settings)
> para validarlas al arrancar. No se ha modificado `src/config.py`.

## Variables de entorno

### OpenCode Go

| Variable | Default | Uso |
|---|---|---|
| `OPENCODE_API_KEY` | — | API key `oc_sk_...` (obligatoria para llamar) |
| `OPENCODE_BASE_URL` | `https://opencode.ai/inference/go` | Base de la Inference API |
| `OPENCODE_MODEL` | `deepseek-v4.1-flash` | Modelo principal (0 días de retención) |
| `OPENCODE_FALLBACK_MODELS` | `glm-5.3-flash,qwen3.8-flash,mimo-v2.6-flash,gpt-6-luna` | Fallback ordenado (coma-separado) |
| `OPENCODE_TIMEOUT` | `60` | Timeout HTTP en segundos |
| `OPENCODE_MAX_RETRIES` | `3` | Reintentos adicionales por modelo |
| `OPENCODE_BACKOFF` | `0.5` | Base del backoff exponencial (segundos) |
| `OPENCODE_MIN_ALLOWANCE_PCT` | `20` | % restante bajo el que se prueba el fallback |
| `OPENCODE_SESSION_ID` | UUID aleatorio | `x-opencode-session` estable por import/documento |

### Jev / TypeSafe

| Variable | Default | Uso |
|---|---|---|
| `TYPESAFE_API_KEY` | — | API key de TypeSafe (obligatoria para llamar) |
| `JEV_MODEL` | `jev-latest` | Modelo del decisor |
| `JEV_BASE_URL` | `https://api.typesafe.ai/v1/systemone` | Endpoint |
| `JEV_TIMEOUT` | `5` | Timeout HTTP en segundos |
| `JEV_MAX_RETRIES` | `2` | Reintentos adicionales (429/5xx/timeout) |
| `JEV_BACKOFF` | `0.5` | Base del backoff exponencial |

## Ejemplos

### OpenCode Go con JSON Schema y fallback

```python
from pydantic import BaseModel

from src.ai.opencode_go import OpenCodeGoClient


class ExtractedRow(BaseModel):
    value_date: str
    amount: float
    description: str


with OpenCodeGoClient() as client:
    result = client.complete(
        messages=[
            {"role": "system", "content": "Extrae la fila del extracto."},
            {"role": "user", "content": "09/01/2026 AHORRAMAS -38,06"},
        ],
        schema=ExtractedRow,
        # session_id="import-42"  # estable durante todo el documento
    )

print(result.parsed)                 # ExtractedRow validado con Pydantic
print(result.model)                  # modelo que respondió (puede ser fallback)
print(result.usage.cost_usd)         # coste reportado por Go
print(result.allowance.remaining_ratio)
```

`client.chat(...)` fuerza Chat Completions y `client.responses(...)` fuerza la
Responses API. `complete(...)` enruta por familia: `deepseek-*`/`glm-*`/`qwen*`
→ Chat; `gpt-*`/`grok-*`/`muse-*` → Responses. Los stubs `anthropic()` y
`google()` lanzan `NotImplementedError` hasta F4.

### Decisiones con Jev

```python
from src.ai.decision import DecisionOrchestrator
from src.ai.jev import JevProvider
from src.ai.schemas import DecisionQuestion

questions = {
    "kind": DecisionQuestion.choice(
        "¿Qué tipo de movimiento es?",
        {"gasto": "Dinero que sale", "ingreso": "Dinero que entra"},
    ),
    "categoria": DecisionQuestion.choice(
        "¿Qué categoría es?",
        {"Alimentación": "Supermercado", "Otros": "Ninguna"},
    ),
    "es_transferencia_interna": DecisionQuestion.noul(
        "¿Es una transferencia entre cuentas propias?"
    ),
}

state = {
    "merchant": "AHORRAMAS",
    "amount": "-38.06",
    "currency": "EUR",
    "mcc": "5411",
    "rule_hits": ["MCC 5411 → Alimentación"],
    "precedents": [{"merchant": "AHORRAMAS", "categoria": "Alimentación"}],
}

orchestrator = DecisionOrchestrator(JevProvider())
result = orchestrator.decide(state, questions, risk="normal")

print(result.needs_review)  # True si no alcanza los umbrales del plan
print(result.confidence)    # mínima confianza efectiva
print(result.explanation)   # por qué se acepta o va a revisión
```

Los umbrales por defecto (en `Thresholds`) son los del plan: categoría
`≥0.90` y margen top-2 `≥0.15`; transferencia `≥0.95`; duplicado `≥0.90`;
revisión por debajo de `0.75` (o `0.70`/`0.80` según la política). En preguntas
`noul`, `confidence` es `|2p-1|` pero el umbral se aplica a
`answers[q]["decision_strength"]` (`max(p, 1-p)`), porque el plan expresa esos
umbrales como probabilidad. Para tests o para inyectar otro decisor, implementa
el `DecisionProvider` Protocol (`name` + `ask(state, questions, timeout=...)`).

### Agente documental

`DocumentIntakeAgent` sigue siendo la capa determinista (probe, texto/tablas,
allowlist, conciliación). La extracción semántica y las llamadas a OpenCode Go
están en `src/ingest/agentic.py`:

```python
from src.ingest.agentic import AgenticStatementExtractor

with AgenticStatementExtractor() as extractor:
    statement = extractor.extract("docs/transactions.csv")
print(len(statement.events), statement.parser_version)
```

Para CSV/TSV/XLSX el agente infiere el mapping y el código transforma todas
las filas. Para PDF con texto extrae filas por página en paralelo y concilia
saldos. Para imágenes/PDF escaneados se aplica OCR local (Tesseract) y el texto
se interpreta con DeepSeek; no se usa visión de Luna como primaria. Los imports
con OCR quedan en `needs_review`. La cola persistente vive en
`src/import_worker.py`.

## Tests

```bash
source .venv/bin/activate
pytest -q src/tests/test_ai_opencode_go.py src/tests/test_ai_jev.py src/tests/test_ai_decision.py
```

Los tests usan `httpx.MockTransport`: **cero llamadas de red**. No se necesita
ninguna API key real.

## Privacidad y coste

- El `state` que va a Jev debe ir redactado (merchant, MCC, importe, descripción
  limpia); nunca PDFs ni imágenes.
- DeepSeek V4.1 Flash, GLM-5.3-Flash, Qwen3.8 Flash y MiMo tienen 0 días de
  retención; GPT-6 Luna retiene 30 días y es solo fallback.
- El cliente lee `usage.opencode.allowance` y `billing_source` en cada
  respuesta. Si el proveedor expone `remaining/limit` (o cabeceras equivalentes)
  y queda menos del 20 %, prueba el siguiente modelo de la cadena.
- Ni las API keys ni el `state` completo se escriben en logs o mensajes de error.
