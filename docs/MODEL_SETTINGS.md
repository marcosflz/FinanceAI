# Ajustes de modelos

En **Ajustes → Modelos** se pueden cambiar parámetros no sensibles sin
reconstruir el contenedor. Se guardan en `app_config` (claves `model.*`) y se
aplican en la siguiente extracción o lote de clasificación.

| Ajuste | Default | Uso |
|---|---:|---|
| `jev_model` | `jev-latest` | Modelo del decisor TypeSafe. |
| `jev_reference_max` | `40` | Máximo de ejemplos aceptados enviados a Jev (el “contexto”). |
| `classification_batch_size` | `10` | Movimientos por lote de revisión. |
| `jev_max_calls_per_run` | `50` | Tope de llamadas a Jev por ejecución. |
| `opencode_model` | `deepseek-v4.1-flash` | Modelo documental primario. |
| `opencode_fallback_models` | lista del entorno | Fallback si el primario falla. |
| `ocr_lang` | `spa+eng` | Idioma de Tesseract. |
| `ocr_dpi` | `250` | Render de PDF escaneado. |
| `auto_approve_threshold` | `0.95` | Confianza mínima Jev para aprobar sin revisión. |

Las API keys (`TYPESAFE_API_KEY`, `OPENCODE_API_KEY`) **no** se guardan aquí:
siguen en `deploy.env`/secretos del servidor.

## API

```http
GET  /api/v3/settings/models
PATCH /api/v3/settings/models
```

Ejemplo:

```bash
curl -X PATCH http://localhost:3000/api/v3/settings/models \
  -H 'Content-Type: application/json' \
  -H "X-CSRF-Token: $CSRF" \
  -b cookies.txt \
  -d '{"jev_reference_max": 30, "classification_batch_size": 8}'
```

Los valores se validan y se recortan a rangos seguros:
`jev_reference_max` 0–200, lote 1–50, llamadas 1–500, OCR DPI 100–400
y umbral de autoaprobación 0–1.

## Backfill de pendientes

Para aplicar el umbral a clasificaciones ya existentes sin reclasificar:

```bash
docker exec financial-tools-backend python -m scripts.auto_approve --dry-run
docker exec financial-tools-backend python -m scripts.auto_approve
```

## Prioridad

`app_config` (si existe) > variable de entorno > default del código. Así se
puede ajustar desde la UI sin tocar `deploy.env`, y el entorno sigue sirviendo
como valor inicial.
