from __future__ import annotations

import sqlite3
import tempfile
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .v2_migrations import V2MigrationReport, migrate_v2


@dataclass(frozen=True, slots=True)
class MigrationResult:
    report: V2MigrationReport
    database_path: Path
    backup_path: Path | None
    dry_run: bool


def _sqlite_backup(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(source)) as source_conn, closing(
        sqlite3.connect(destination)
    ) as dest_conn:
        source_conn.backup(dest_conn)


def migrate_database(database_path: str | Path, *, dry_run: bool = False) -> MigrationResult:
    source = Path(database_path).resolve()
    if not source.is_file():
        raise FileNotFoundError(f"database not found: {source}")

    backup_path: Path | None = None
    if dry_run:
        temp_dir = tempfile.TemporaryDirectory(prefix="avm-v2-migration-")
        target = Path(temp_dir.name) / source.name
        _sqlite_backup(source, target)
    else:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup_path = source.with_name(f"{source.stem}.v1-backup-{stamp}{source.suffix}")
        _sqlite_backup(source, backup_path)
        target = source
        temp_dir = None

    try:
        with closing(sqlite3.connect(target)) as conn:
            report = migrate_v2(conn)
            conn.commit()
    finally:
        if temp_dir is not None:
            temp_dir.cleanup()

    return MigrationResult(
        report=report,
        database_path=source,
        backup_path=backup_path,
        dry_run=dry_run,
    )


def restore_database(database_path: str | Path, backup_path: str | Path) -> None:
    target = Path(database_path).resolve()
    backup = Path(backup_path).resolve()
    if not backup.is_file():
        raise FileNotFoundError(f"backup not found: {backup}")
    target.parent.mkdir(parents=True, exist_ok=True)
    _sqlite_backup(backup, target)
