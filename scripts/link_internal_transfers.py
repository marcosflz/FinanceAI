"""Enlaza las dos patas de transferencias internas ya importadas.

Uso:
    python -m scripts.link_internal_transfers --dry-run
    python -m scripts.link_internal_transfers
"""

from __future__ import annotations

import argparse
import json

from src.ingest.internal_transfers import link_internal_transfers


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    stats = link_internal_transfers(dry_run=args.dry_run)
    print(json.dumps(stats, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
