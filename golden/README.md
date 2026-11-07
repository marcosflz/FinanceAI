# Golden set de ingesta

`manifest.json` contiene las expectativas mínimas por documento. El script
`scripts/eval_agentic.py` extrae cada fichero y compara filas, suma, saldo
inicial/final y conciliación.

```bash
source .venv/bin/activate
python -m scripts.eval_agentic golden/manifest.json
```

Para añadir un banco:

1. Copia el extracto anonimizado en `golden/files/` (no lo subas al repo si
   contiene datos personales).
2. Añade un caso a `manifest.json` con `path`, `expected_rows`,
   `expected_total`, `opening_balance`, `closing_balance` y
   `require_reconciliation`.
3. Ejecuta el evaluador y revisa las diferencias antes de dar por bueno el
   formato.

El objetivo es 20–30 documentos de varios bancos. Mientras no existan, el
golden set actual solo cubre Trade Republic y Revolut.
