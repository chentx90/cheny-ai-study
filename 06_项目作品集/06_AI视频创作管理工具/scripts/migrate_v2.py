from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from ai_video_manager.infrastructure.db import migrate_database, restore_database


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate an AI Video Manager database to V2")
    parser.add_argument("database", type=Path, help="SQLite database path")
    parser.add_argument("--dry-run", action="store_true", help="migrate a temporary copy only")
    parser.add_argument("--restore", type=Path, help="restore the database from this backup")
    args = parser.parse_args()

    if args.restore:
        restore_database(args.database, args.restore)
        print(json.dumps({"restored": str(args.database), "backup": str(args.restore)}, ensure_ascii=False))
        return 0

    result = migrate_database(args.database, dry_run=args.dry_run)
    payload = asdict(result.report)
    payload.update(
        {
            "valid": result.report.valid,
            "dry_run": result.dry_run,
            "database": str(result.database_path),
            "backup": str(result.backup_path) if result.backup_path else None,
        }
    )
    print(json.dumps(payload, ensure_ascii=False))
    return 0 if result.report.valid else 2


if __name__ == "__main__":
    raise SystemExit(main())

