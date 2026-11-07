"""Evalúa el extractor agéntico contra un golden set local.

Uso:
    python -m scripts.eval_agentic golden/manifest.json
    python -m scripts.eval_agentic golden/manifest.json --json

El manifest es una lista de casos. Los ficheros no se versionan si contienen
datos personales; el manifest sí puede versionarse con rutas relativas.
"""

from __future__ import annotations

import argparse
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

from src.ingest.agentic import AgenticStatementExtractor

DEFAULT_TOLERANCE = Decimal("0.01")


def _amount_sum(events: list[dict]) -> Decimal:
    return sum(
        (event.get("amount") or Decimal("0") for event in events),
        Decimal("0"),
    )


def _ok(actual: Decimal | None, expected: Decimal | str | None, tolerance: Decimal) -> bool:
    if expected is None:
        return True
    if actual is None:
        return False
    return abs(actual - Decimal(str(expected))) <= tolerance


def evaluate_case(case: dict[str, Any], extractor: AgenticStatementExtractor) -> dict:
    path = Path(case["path"])
    name = case.get("name") or path.name
    if not path.exists():
        return {"name": name, "path": str(path), "ok": False, "error": "file_missing"}
    tolerance = Decimal(str(case.get("tolerance", DEFAULT_TOLERANCE)))
    try:
        statement = extractor.extract(path)
    except Exception as exc:
        return {
            "name": name,
            "path": str(path),
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
    total = _amount_sum(statement.events)
    row_ok = (
        case.get("expected_rows") is None
        or len(statement.events) == int(case["expected_rows"])
    )
    total_ok = _ok(total, case.get("expected_total"), tolerance)
    opening_ok = _ok(statement.opening_balance, case.get("opening_balance"), tolerance)
    closing_ok = _ok(statement.closing_balance, case.get("closing_balance"), tolerance)
    recon_ok = (
        case.get("require_reconciliation") is not True
        or bool((statement.metadata.get("reconciliation") or {}).get("ok"))
    )
    return {
        "name": name,
        "path": str(path),
        "ok": row_ok and total_ok and opening_ok and closing_ok and recon_ok,
        "rows": len(statement.events),
        "expected_rows": case.get("expected_rows"),
        "total": str(total),
        "expected_total": case.get("expected_total"),
        "opening": str(statement.opening_balance) if statement.opening_balance is not None else None,
        "expected_opening": case.get("opening_balance"),
        "closing": str(statement.closing_balance) if statement.closing_balance is not None else None,
        "expected_closing": case.get("closing_balance"),
        "reconciliation": statement.metadata.get("reconciliation"),
        "issues": statement.issues[:10],
        "checks": {
            "rows": row_ok,
            "total": total_ok,
            "opening": opening_ok,
            "closing": closing_ok,
            "reconciliation": recon_ok,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", help="JSON con la lista de casos")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--pdf-workers", type=int, default=4)
    args = parser.parse_args()

    cases = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    if isinstance(cases, dict):
        cases = cases.get("cases", [])
    with AgenticStatementExtractor(pdf_workers=args.pdf_workers) as extractor:
        results = [evaluate_case(case, extractor) for case in cases]
    summary = {
        "cases": len(results),
        "passed": sum(1 for result in results if result["ok"]),
        "failed": sum(1 for result in results if not result["ok"]),
        "results": results,
    }
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    else:
        for result in results:
            status = "OK" if result["ok"] else "FAIL"
            print(f"[{status}] {result['name']}: {result.get('rows', '?')} filas")
            if not result["ok"]:
                print(f"       checks={result.get('checks')} error={result.get('error')}")
                for issue in result.get("issues", []):
                    print(f"       - {issue}")
        print(f"\n{summary['passed']}/{summary['cases']} casos OK")


if __name__ == "__main__":
    main()
