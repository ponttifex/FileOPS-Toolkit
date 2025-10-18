"""Pre-execution checks for FileOps Toolkit."""

from __future__ import annotations

import importlib
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Sequence, Union

from .remote import RemoteSourceConfig, is_remote_target


@dataclass(slots=True)
class PreflightReport:
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    info: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def _normalise_algorithms(value: Union[str, Sequence[str], None]) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    return [item.lower() for item in value]


def run_prechecks(cfg: Dict[str, Any], remote_sources: Sequence[RemoteSourceConfig] | None = None) -> PreflightReport:
    report = PreflightReport()
    sources = cfg.get('sources', [])
    destination = Path(cfg.get('destination', '.')).expanduser()

    for src in sources:
        if isinstance(src, str) and is_remote_target(src):
            report.info.append(f'Remote source pending staging: {src}')
            continue
        src_path = Path(src).expanduser()
        if not src_path.exists():
            report.errors.append(f'Source path missing: {src_path}')
        elif not src_path.is_dir():
            report.errors.append(f'Source is not a directory: {src_path}')
        else:
            report.info.append(f'Source ready: {src_path}')

    if not destination.exists():
        try:
            destination.mkdir(parents=True, exist_ok=True)
            report.info.append(f'Created destination directory {destination}')
        except Exception as exc:
            report.errors.append(f'Cannot create destination {destination}: {exc}')
    else:
        report.info.append(f'Destination ready: {destination}')

    tools_to_check = ['find', 'rsync', 'xargs', 'ssh']
    for tool in tools_to_check:
        if shutil.which(tool):
            report.info.append(f'Command available: {tool}')
        else:
            report.warnings.append(f'Command not found: {tool}')

    backup_dir = cfg.get('backup_duplicates_to')
    if backup_dir:
        backup_path = Path(backup_dir).expanduser()
        if not backup_path.exists():
            try:
                backup_path.mkdir(parents=True, exist_ok=True)
                report.info.append(f'Created backup directory {backup_path}')
            except Exception as exc:  # pragma: no cover - defensive
                report.errors.append(f'Cannot create backup directory {backup_path}: {exc}')
        else:
            report.info.append(f'Backup directory ready: {backup_path}')

    duplicates_archive = cfg.get('duplicates_archive_dir')
    if duplicates_archive:
        archive_path = Path(duplicates_archive).expanduser()
        if not archive_path.exists():
            try:
                archive_path.mkdir(parents=True, exist_ok=True)
                report.info.append(f'Created duplicates archive dir {archive_path}')
            except Exception as exc:  # pragma: no cover - defensive
                report.errors.append(f'Cannot create duplicates archive dir {archive_path}: {exc}')
        else:
            report.info.append(f'Duplicates archive ready: {archive_path}')

    checksum_algos = _normalise_algorithms(cfg.get('checksum_algo'))
    if any(algo.startswith('xxh') for algo in checksum_algos):
        try:
            importlib.import_module('xxhash')
        except ModuleNotFoundError:
            report.warnings.append('xxhash module not installed; xxh algorithms unavailable.')

    min_free = cfg.get('min_free_bytes')
    if min_free:
        try:
            min_free = int(min_free)
            free = shutil.disk_usage(destination).free
            if free < min_free:
                report.errors.append(
                    f'Destination {destination} has {free} bytes free (< required {min_free}).'
                )
            else:
                report.info.append(f'Free space check passed ({free} bytes available).')
        except Exception as exc:  # pragma: no cover - defensive
            report.warnings.append(f'Failed to evaluate free space: {exc}')

    if remote_sources:
        staging_dir = Path(cfg.get('remote_staging_dir', './data/remote_staging')).expanduser()
        try:
            staging_dir.mkdir(parents=True, exist_ok=True)
            report.info.append(f'Remote staging ready: {staging_dir}')
        except Exception as exc:
            report.errors.append(f'Cannot prepare remote staging dir {staging_dir}: {exc}')

        for remote in remote_sources:
            report.info.append(f'Remote source configured: {remote.target} -> {remote.name}')
            if remote.identity_file and not remote.identity_file.exists():
                report.errors.append(f'Identity file not found for {remote.target}: {remote.identity_file}')
            if remote.password and not shutil.which('sshpass'):
                report.errors.append(
                    f'Password provided for {remote.target} but sshpass is unavailable.'
                )

    return report
