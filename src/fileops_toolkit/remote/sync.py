"""Remote source staging utilities."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)

REMOTE_PATTERN = re.compile(r'^[^@\s]+@[^:\s]+:.+')
DEFAULT_REMOTE_ARGS: Tuple[str, ...] = ('-avz', '--info=progress2')


@dataclass(slots=True, frozen=True)
class RemoteSourceConfig:
    """Parsed configuration for a remote rsync source."""

    target: str
    name: str
    identity_file: Optional[Path]
    password: Optional[str]
    ssh_options: Tuple[str, ...]
    rsync_args: Tuple[str, ...]
    env: Tuple[Tuple[str, str], ...]


@dataclass(slots=True)
class RemoteStageResult:
    """Outcome of staging a remote source into the local workspace."""

    config: RemoteSourceConfig
    staging_path: Path
    stdout: str
    stderr: str
    dry_run: bool
    duration: float


class RemoteSyncError(RuntimeError):
    """Raised when a remote source cannot be staged."""


def is_remote_target(value: str) -> bool:
    """Return True if the value looks like an rsync remote target."""
    return value.startswith('ssh://') or bool(REMOTE_PATTERN.match(value))


def sanitize_label(value: str) -> str:
    """Create a filesystem-friendly label from a remote target string."""
    label = value.replace('ssh://', '')
    label = re.sub(r'[@:]+', '_', label)
    label = re.sub(r'[^\w.\-]+', '_', label).strip('_')
    return label or 'remote_source'


def _unique_label(base: str, used: set[str]) -> str:
    candidate = base
    counter = 2
    while candidate in used:
        candidate = f'{base}-{counter}'
        counter += 1
    used.add(candidate)
    return candidate


def _parse_remote_entry(entry: Any, used_names: set[str]) -> RemoteSourceConfig:
    if isinstance(entry, str):
        target = entry
        name = _unique_label(sanitize_label(target), used_names)
        return RemoteSourceConfig(target, name, None, None, (), (), ())
    if not isinstance(entry, dict):
        raise ValueError(f'Unsupported remote source entry: {entry!r}')

    target = entry.get('target')
    if not target:
        host = entry.get('host') or entry.get('user') or entry.get('username')
        path = entry.get('path')
        if host and path:
            target = f'{host}:{path}'
        else:
            raise ValueError('Remote source dict must define "target" or "host" + "path".')
    name = entry.get('name') or sanitize_label(target)
    name = _unique_label(name, used_names)
    identity = entry.get('identity_file')
    identity_path = Path(identity).expanduser() if identity else None
    password = entry.get('password')
    ssh_options = tuple(entry.get('ssh_options', []))
    rsync_args = tuple(entry.get('rsync_args', []))
    env = tuple((str(k), str(v)) for k, v in entry.get('env', {}).items())
    return RemoteSourceConfig(
        target=target,
        name=name,
        identity_file=identity_path,
        password=password,
        ssh_options=ssh_options,
        rsync_args=rsync_args,
        env=env,
    )


def extract_remote_sources(cfg: Dict[str, Any]) -> Tuple[List[str], List[RemoteSourceConfig]]:
    """Separate local and remote sources from the configuration."""
    used_names: set[str] = set()
    local_sources: List[str] = []
    remote_sources: List[RemoteSourceConfig] = []

    for source in cfg.get('sources', []):
        if isinstance(source, str) and is_remote_target(source):
            remote_sources.append(_parse_remote_entry(source, used_names))
        else:
            local_sources.append(source)

    for entry in cfg.get('remote_sources', []):
        remote_sources.append(_parse_remote_entry(entry, used_names))

    return local_sources, remote_sources


def _build_rsync_command(
    remote: RemoteSourceConfig,
    *,
    destination: Path,
    default_args: Sequence[str],
    dry_run: bool,
) -> Tuple[List[str], Optional[Dict[str, str]]]:
    args = list(remote.rsync_args or default_args)
    if dry_run and '--dry-run' not in args and '-n' not in args:
        args.append('--dry-run')
    ssh_parts: List[str] = ['ssh']
    if remote.identity_file:
        ssh_parts.extend(['-i', str(remote.identity_file)])
    if remote.ssh_options:
        ssh_parts.extend(remote.ssh_options)
    cmd: List[str] = ['rsync', *args]
    if len(ssh_parts) > 1:
        cmd.extend(['-e', ' '.join(ssh_parts)])
    target = remote.target
    dest_arg = str(destination)
    if not dest_arg.endswith(os.sep):
        dest_arg += os.sep
    cmd.extend([target, dest_arg])

    if remote.password:
        if not shutil.which('sshpass'):
            raise RemoteSyncError(
                f'sshpass is required to use password authentication for remote source {remote.target}'
            )
        cmd = ['sshpass', '-p', remote.password, *cmd]

    env: Optional[Dict[str, str]] = None
    if remote.env:
        env = dict(os.environ)
        env.update(dict(remote.env))

    return cmd, env


def stage_remote_sources(
    remote_sources: Sequence[RemoteSourceConfig],
    *,
    staging_root: Path,
    default_rsync_args: Sequence[str] | None = None,
    dry_run: bool = False,
    parallelism: int = 1,
    console: Optional[Console] = None,
) -> List[RemoteStageResult]:
    """Stage remote sources locally using rsync and return staging directories."""
    if not remote_sources:
        return []

    staging_root = staging_root.expanduser()
    staging_root.mkdir(parents=True, exist_ok=True)
    default_args = tuple(default_rsync_args or DEFAULT_REMOTE_ARGS)

    def _sync(remote: RemoteSourceConfig) -> RemoteStageResult:
        destination = staging_root / remote.name
        destination.mkdir(parents=True, exist_ok=True)
        cmd, env = _build_rsync_command(remote, destination=destination, default_args=default_args, dry_run=dry_run)
        start = time.monotonic()
        proc = subprocess.run(cmd, capture_output=True, text=True, env=env)
        duration = time.monotonic() - start
        if proc.returncode != 0:
            raise RemoteSyncError(
                f'rsync failed for {remote.target}: {proc.stderr.strip() or proc.stdout.strip() or proc.returncode}'
            )
        return RemoteStageResult(remote, destination, proc.stdout, proc.stderr, dry_run, duration)

    progress = Progress(
        SpinnerColumn(),
        TextColumn('[progress.description]{task.description}'),
        BarColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
        transient=True,
        disable=console is None,
        expand=True,
    )

    results: Dict[str, RemoteStageResult] = {}
    max_workers = max(1, min(parallelism, len(remote_sources)))

    with progress:
        task_id = progress.add_task('Syncing remote sources', total=len(remote_sources))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_map = {executor.submit(_sync, remote): remote for remote in remote_sources}
            for future in as_completed(future_map):
                remote = future_map[future]
                try:
                    result = future.result()
                except Exception as exc:  # pragma: no cover - propagated upwards
                    for other in future_map:
                        if other is not future:
                            other.cancel()
                    raise RemoteSyncError(str(exc)) from exc
                results[remote.name] = result
                progress.advance(task_id)

    ordered = [results[remote.name] for remote in remote_sources if remote.name in results]
    return ordered
