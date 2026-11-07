"""Prueba el extractor agéntico sin tocar la base de datos.

Uso:
    python -m scripts.agentic_extract docs/extracto.pdf
    python -m scripts.agentic_extract docs/extracto.csv --json
"""

from __future__ import annotations

import argparse
import json

from src.ingest.agentic import AgenticStatementExtractor


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", help="CSV/TSV/PDF a analizar")
    parser.add_argument("--json", action="store_true", help="Imprime eventos JSON")
    parser.add_argument("--pdf-workers", type=int, default=4)
    args = parser.parse_args()

    with AgenticStatementExtractor(pdf_workers=args.pdf_workers) as extractor:
        statement = extractor.extract(args.path)

    print(f"source={statement.source} parser={statement.parser_version}")
    print(
        f"bank={statement.bank} account={statement.account_name} "
        f"iban={statement.account_iban}"
    )
    print(f"period={statement.period_start}..{statement.period_end}")
    print(f"rows={len(statement.raw_rows)} events={len(statement.events)}")
    if statement.issues:
        print("issues:")
        for issue in statement.issues:
            print(f"  - {issue}")
    for event in statement.events[:10]:
        print(
            event["value_date"],
            event["amount"],
            event["kind"],
            (event.get("description_clean") or "")[:90],
        )
    if args.json:
        print(
            json.dumps(
                {
                    "metadata": statement.metadata,
                    "events": [
                        {key: str(value) for key, value in event.items()}
                        for event in statement.events
                    ],
                },
                ensure_ascii=False,
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
