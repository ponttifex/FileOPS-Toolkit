"""Logging utilities for FileOps Toolkit.

Provides CSV/JSON logging helpers and an orchestration wrapper that
captures transfer metadata alongside deduplication decisions.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

from ..deduplication.engine import DedupResult
from ..metadata.scanner import FileMetadata
from ..transfer.engine import TransferOutcome

CSV_FIELDS = [
    'run_id',
    'timestamp',
    'worker',
    'src_path',
    'dst_path',
    'size_bytes',
    'mtime_unix',
    'hash',
    'decision',
    'reason',
    'note',
    'duration_ms',
    'rsync_exit',
    'error_msg',
    'tool',
    'attempts',
    'verified',
]


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _resolve_template(template: str, run_id: str) -> str:
    now = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    return template.replace('$(date +%F_%T)', now).replace('$(run_id)', run_id)


class CSVLogger:
    def __init__(self, path: Path, fieldnames: Sequence[str]):
        _ensure_parent(path)
        self.path = path
        self.file = path.open('w', newline='', encoding='utf-8')
        self.writer = csv.DictWriter(self.file, fieldnames=fieldnames)
        self.writer.writeheader()

    def log_row(self, row: Dict[str, Any]) -> None:
        self.writer.writerow(row)
        self.file.flush()

    def close(self) -> None:
        self.file.close()


class JSONLogger:
    def __init__(self, path: Path):
        _ensure_parent(path)
        self.path = path
        self.records: list[Dict[str, Any]] = []

    def add_entry(self, entry: Dict[str, Any]) -> None:
        self.records.append(entry)

    def flush(self) -> None:
        with self.path.open('w', encoding='utf-8') as fh:
            json.dump(self.records, fh, indent=2)


@dataclass(slots=True)
class OperationLoggers:
    csv: CSVLogger
    json: JSONLogger
    errors_path: Path

    def close(self) -> None:
        self.csv.close()
        self.json.flush()


def setup_loggers(logging_config: Dict[str, Any], run_id: str) -> OperationLoggers:
    log_dir = Path(logging_config.get('dir', './logs')).expanduser()
    csv_name = _resolve_template(logging_config.get('csv_file', 'operations.csv'), run_id)
    json_name = _resolve_template(logging_config.get('json_file', 'summary.json'), run_id)
    errors_name = _resolve_template(logging_config.get('errors_file', 'errors.log'), run_id)
    csv_logger = CSVLogger(log_dir / csv_name, CSV_FIELDS)
    json_logger = JSONLogger(log_dir / json_name)
    errors_path = (log_dir / errors_name).expanduser()
    _ensure_parent(errors_path)
    return OperationLoggers(csv_logger, json_logger, errors_path)


def _primary_checksum(meta: FileMetadata, preferred: Sequence[str]) -> Optional[str]:
    for algo in preferred:
        checksum = meta.get_checksum(algo)
        if checksum:
            return checksum
    return meta.checksum


def log_operation(
    loggers: OperationLoggers,
    *,
    run_id: str,
    worker: str,
    result: DedupResult,
    transfer: Optional[TransferOutcome],
    verified: Optional[bool],
    preferred_algos: Sequence[str],
) -> None:
    checksum = _primary_checksum(result.src, preferred_algos)
    duration_ms = round((transfer.duration if transfer else 0.0) * 1000, 3)
    exit_code: Any = ''
    error_msg = ''
    tool = ''
    attempts = 0
    if transfer:
        exit_code = transfer.exit_code
        tool = transfer.tool
        attempts = transfer.attempts
        if not transfer.success:
            error_msg = transfer.error_message

    row = {
        'run_id': run_id,
        'timestamp': _timestamp(),
        'worker': worker,
        'src_path': str(result.src.path),
        'dst_path': str(result.dest_path),
        'size_bytes': result.src.size_bytes,
        'mtime_unix': result.src.mtime,
        'hash': checksum or '',
        'decision': result.decision.name.lower(),
        'reason': result.reason,
        'note': result.message or '',
        'duration_ms': duration_ms,
        'rsync_exit': exit_code,
        'error_msg': error_msg,
        'tool': tool,
        'attempts': attempts,
        'verified': verified if verified is not None else '',
    }
    loggers.csv.log_row(row)
    loggers.json.add_entry(row)
    if error_msg:
        with loggers.errors_path.open('a', encoding='utf-8') as fh:
            fh.write(json.dumps(row) + '\n')
