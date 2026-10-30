#!/usr/bin/env python3
"""Stage every workspace database; --apply writes back with rollback backups.

Usage: uv run python scripts/maintain_workspace.py /absolute/workspace [--apply]
Only SQLite databases are copied. Configurations, captures and result files stay
at their existing paths. Backups and the metadata report are retained on failure.
"""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from uuid import uuid4

from taskweave.infrastructure.locking import InstanceLock
from taskweave.infrastructure.sqlite_storage import validate_schema

if __package__:
    from scripts.maintain_current_schema import rebuild, quote
else:
    from maintain_current_schema import rebuild, quote


def backup_database(source, target, *, existing=False):
    """Use SQLite's consistent snapshot API, including committed WAL content."""
    source, target = Path(source), Path(target)
    if not existing and target.exists():
        raise FileExistsError(target)
    if not existing:
        target.parent.mkdir(parents=True, exist_ok=True)
    target_mode = 'rw' if existing else 'rwc'
    with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)) as reader, \
            closing(sqlite3.connect(target.as_uri() + '?mode=' + target_mode, uri=True)) as writer:
        reader.backup(writer)


def apply_database(candidate, source):
    backup_database(candidate, source, existing=True)


def inspect_database(path, *, kind=None):
    """Return table counts only; never expose cell contents in the report."""
    with closing(sqlite3.connect(Path(path).as_uri() + '?mode=ro', uri=True)) as db:
        if kind:
            validate_schema(db, kind)
        if db.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
            raise ValueError('Database integrity check failed')
        if db.execute('PRAGMA foreign_key_check').fetchall():
            raise ValueError('Database foreign key check failed')
        tables = [row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        return {table: db.execute(f'SELECT count(*) FROM {quote(table)}').fetchone()[0] for table in sorted(tables)}


def _write_report(folder, report):
    temporary = folder / 'report.pending.json'
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(folder / 'report.json')


def maintain_workspace(workspace, *, backup_dir=None, apply=False, definition_evidence=None):
    workspace = Path(workspace)
    if not workspace.is_absolute():
        raise ValueError('Workspace must be an absolute path')
    workspace = workspace.resolve(strict=True)
    if not workspace.is_dir() or not (workspace / 'taskweave.db').is_file():
        raise ValueError('Workspace must contain taskweave.db')
    if backup_dir is None:
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        backup_dir = workspace / 'backups' / f'current-schema-{stamp}-{uuid4().hex[:8]}'
    backup_dir = Path(backup_dir)
    if not backup_dir.is_absolute():
        raise ValueError('Backup directory must be an absolute path')
    backup_dir = backup_dir.resolve()
    if backup_dir.is_relative_to(workspace / 'tasks'):
        raise ValueError('Backup directory must be outside task data directories')
    if backup_dir.exists():
        raise FileExistsError(backup_dir)

    if definition_evidence is not None:
        definition_evidence = Path(definition_evidence)
        if not definition_evidence.is_absolute() or not definition_evidence.is_file():
            raise ValueError('Definition evidence must be an existing absolute database path')
        definition_evidence = definition_evidence.resolve()

    with closing(InstanceLock(workspace / 'coordinator.lock')):
        sources = [(workspace / 'taskweave.db', 'control')]
        sources.extend((path, 'task-data') for path in sorted((workspace / 'tasks').glob('*/data.db')))
        for path, _ in sources:
            if path.resolve() != path or not path.is_file():
                raise ValueError('Database symlinks or non-files require explicit review')
        backup_dir.mkdir(parents=True, exist_ok=False)
        report = {'workspace': str(workspace), 'backup_dir': str(backup_dir),
                  'mode': 'apply' if apply else 'dry_run', 'status': 'preparing',
                  'created_at': datetime.now(timezone.utc).isoformat(), 'databases': []}
        _write_report(backup_dir, report)
        touched = []
        try:
            evidence_copy = None
            if definition_evidence is not None:
                evidence_copy = backup_dir / 'evidence' / 'taskweave.db'
                backup_database(definition_evidence, evidence_copy)
                report['definition_evidence'] = str(definition_evidence)
                report['definition_evidence_backup'] = str(evidence_copy)
                _write_report(backup_dir, report)
            # Back up every source before building or writing any candidate.
            for path, kind in sources:
                relative = path.relative_to(workspace)
                original = backup_dir / 'original' / relative
                candidate = backup_dir / 'converted' / relative
                backup_database(path, original)
                counts = inspect_database(original)
                report['databases'].append({'source': str(path), 'backup': str(original),
                    'candidate': str(candidate), 'kind': kind, 'original_counts': counts})
                _write_report(backup_dir, report)
            for entry in report['databases']:
                candidate = Path(entry['candidate'])
                candidate.parent.mkdir(parents=True, exist_ok=True)
                entry['definition_hash_updates'] = []
                rebuild(entry['backup'], candidate, entry['kind'],
                        definition_evidence=evidence_copy if entry['kind'] == 'control' else None,
                        audit=entry['definition_hash_updates'])
                counts = inspect_database(candidate, kind=entry['kind'])
                if counts != entry['original_counts']:
                    raise ValueError('Maintenance changed table identities or record counts')
                entry['converted_counts'] = counts
                _write_report(backup_dir, report)
            report['status'] = 'prepared'
            _write_report(backup_dir, report)
            if not apply:
                report['status'] = 'dry_run'
                _write_report(backup_dir, report)
                return report
            for entry in report['databases']:
                # Include the failing destination: a backup call may fail after
                # changing it. Rollback uses the independent, immutable backup.
                touched.append(entry)
                apply_database(Path(entry['candidate']), Path(entry['source']))
                if inspect_database(entry['source'], kind=entry['kind']) != entry['original_counts']:
                    raise ValueError('Applied database verification failed')
                entry['applied'] = True
                _write_report(backup_dir, report)
            report['status'] = 'applied'
            _write_report(backup_dir, report)
            return report
        except BaseException as exc:
            failures = []
            for entry in reversed(touched):
                try:
                    backup_database(Path(entry['backup']), Path(entry['source']), existing=True)
                    if inspect_database(entry['source']) != entry['original_counts']:
                        raise ValueError('Rollback count check failed')
                    entry['restored'] = True
                except BaseException as restore_error:
                    failures.append({'source': entry['source'], 'error_type': type(restore_error).__name__})
            report.update(status='rollback_failed' if failures else 'rolled_back' if touched else 'preparation_failed',
                          error_type=type(exc).__name__, rollback_failures=failures)
            _write_report(backup_dir, report)
            if failures:
                raise RuntimeError(f'Rollback incomplete; retained backups and report: {backup_dir}') from exc
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('workspace', type=Path)
    parser.add_argument('--backup-dir', type=Path)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--definition-evidence', type=Path)
    args = parser.parse_args()
    report = maintain_workspace(args.workspace, backup_dir=args.backup_dir, apply=args.apply,
                                definition_evidence=args.definition_evidence)
    print(json.dumps({'status': report['status'], 'databases': len(report['databases']),
                      'report': str(Path(report['backup_dir']) / 'report.json')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
