"""Discovery engine for FileOps Toolkit.

This module provides utilities to recursively search source directories for
files matching a set of extensions.  It yields absolute file paths for
downstream processing.  The current implementation uses Python's
``os.walk`` and is designed to be replaced or augmented with faster tools
such as ``fd``/``fdfind`` via subprocess if desired.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
import fnmatch
import re
from pathlib import Path
from typing import Iterable, Iterator, Optional, Sequence


@dataclass(frozen=True)
class DiscoveredFile:
    path: Path
    root: Path
    relative_path: Path


class DiscoveryError(RuntimeError):
    """Raised when discovery fails unexpectedly."""


def _which_tool() -> tuple[str | None, str]:
    for tool in ('fdfind', 'fd'):
        match = shutil.which(tool)
        if match:
            return match, tool
    match = shutil.which('find')
    if match:
        return match, 'find'
    return None, ''


def _run_fd(tool: str, source: Path, extensions: Sequence[str]) -> Iterator[Path]:
    cmd = [tool, '--type', 'f', '--color', 'never', '--hidden', '--print0']
    for ext in extensions:
        cmd.extend(['--extension', ext.lstrip('.')])
    cmd.append('.')
    proc = subprocess.run(
        cmd,
        cwd=str(source),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode != 0:
        raise DiscoveryError(proc.stderr.decode() or f'{tool} exited with {proc.returncode}')
    for raw in proc.stdout.split(b'\0'):
        if not raw:
            continue
        yield Path(os.fsdecode(raw))


def _run_find(tool_path: str, source: Path, extensions: Sequence[str]) -> Iterator[Path]:
    cmd: list[str] = [tool_path, str(source), '-type', 'f', '(']
    for idx, ext in enumerate(extensions):
        if idx:
            cmd.append('-o')
        cmd.extend(['-iname', f'*.{ext.lstrip(".")}'])
    cmd.extend([')', '-print0'])
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if proc.returncode != 0:
        raise DiscoveryError(proc.stderr.decode() or f'find exited with {proc.returncode}')
    for raw in proc.stdout.split(b'\0'):
        if not raw:
            continue
        yield Path(os.fsdecode(raw))


def _walk_python(source: Path, extensions: Sequence[str] | None = None) -> Iterator[Path]:
    normalized_exts = {ext.lower().lstrip('.') for ext in extensions or ()}
    for root, _, files in os.walk(source):
        for name in files:
            if not normalized_exts or name.lower().split('.')[-1] in normalized_exts:
                yield Path(root) / name


def _compile_patterns(patterns: Sequence[str], mode: str, case_sensitive: bool) -> list:
    compiled = []
    if not patterns:
        return compiled
    mode = mode.lower()
    if mode not in {'glob', 'regex'}:
        raise DiscoveryError(f'Unsupported pattern_mode: {mode}')
    flags = 0 if case_sensitive else re.IGNORECASE
    for pattern in patterns:
        if mode == 'glob':
            compiled.append((pattern, None))
        else:
            compiled.append((None, re.compile(pattern, flags)))
    return compiled


def _pattern_match(path: Path, compiled_patterns: list, case_sensitive: bool) -> bool:
    if not compiled_patterns:
        return True
    text = path.as_posix()
    for glob_pattern, regex in compiled_patterns:
        if glob_pattern is not None:
            if fnmatch.fnmatch(text if case_sensitive else text.lower(), glob_pattern if case_sensitive else glob_pattern.lower()):
                return True
        elif regex and regex.search(text):
            return True
    return False


def _filter_paths(
    paths: Iterable[Path],
    patterns: Sequence[str] | None,
    pattern_mode: str,
    case_sensitive: bool,
) -> Iterator[Path]:
    compiled = _compile_patterns(patterns or (), pattern_mode, case_sensitive)
    for path in paths:
        if _pattern_match(path, compiled, case_sensitive):
            yield path


def discover_files(
    sources: Sequence[str],
    extensions: Sequence[str] | None = None,
    *,
    patterns: Sequence[str] | None = None,
    pattern_mode: str = 'glob',
    case_sensitive: bool = False,
    use_external: bool = True,
) -> Iterator[DiscoveredFile]:
    """Yield discovered files with root and relative path metadata."""
    resolved_sources = [Path(src).expanduser() for src in sources]
    tool_path, tool_name = _which_tool() if use_external else (None, '')
    # Validate sources early to surface helpful errors.
    for src in resolved_sources:
        if not src.exists():
            raise DiscoveryError(f'Source path does not exist: {src}')
        if not src.is_dir():
            raise DiscoveryError(f'Source path is not a directory: {src}')

    use_ext_filters = bool(extensions and not patterns)
    normalized_exts = {ext.lower().lstrip('.') for ext in (extensions or ())}
    compiled_patterns = _compile_patterns(patterns or (), pattern_mode, case_sensitive)

    for src in resolved_sources:
        if use_external and tool_path and tool_name in {'fdfind', 'fd'} and use_ext_filters:
            iterator = (src / rel if not rel.is_absolute() else rel for rel in _run_fd(tool_path, src, extensions or ()))
        elif use_external and tool_path and tool_name == 'find' and use_ext_filters:
            iterator = _run_find(tool_path, src, extensions or ())
        else:
            iterator = _walk_python(src, extensions if use_ext_filters else None)

        for path in iterator:
            if normalized_exts and path.suffix:
                if path.suffix.lower().lstrip('.') not in normalized_exts and path.name.lower().split('.')[-1] not in normalized_exts:
                    continue
            if compiled_patterns and not _pattern_match(path, compiled_patterns, case_sensitive):
                continue
            yield DiscoveredFile(
                path=path,
                root=src,
                relative_path=path.relative_to(src),
            )
