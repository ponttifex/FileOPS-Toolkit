"""Transfer engine for FileOps Toolkit.

Provides resilient file transfer utilities with retry/backoff and
verification friendly metadata.  ``rsync`` is preferred when available,
falling back to a pure Python copy implementation for environments where
the binary is missing.
"""

from __future__ import annotations

import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional, Sequence


@dataclass(slots=True)
class TransferOutcome:
    src: Path
    dst: Path
    success: bool
    exit_code: int
    attempts: int
    duration: float
    tool: str
    stdout: str
    stderr: str
    dry_run: bool = False

    @property
    def error_message(self) -> str:
        return self.stderr.strip() or self.stdout.strip()


class TransferError(RuntimeError):
    """Raised when the transfer tool cannot be executed."""


def _run_rsync(src: Path, dst: Path, args: Sequence[str]) -> TransferOutcome:
    cmd = ['rsync', *args, str(src), str(dst)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return TransferOutcome(
        src=src,
        dst=dst,
        success=result.returncode == 0,
        exit_code=result.returncode,
        attempts=1,
        duration=0.0,
        tool='rsync',
        stdout=result.stdout,
        stderr=result.stderr,
    )


def _run_copy(src: Path, dst: Path) -> TransferOutcome:
    try:
        shutil.copy2(src, dst)
    except Exception as exc:  # pragma: no cover - unexpected IO failure
        return TransferOutcome(
            src=src,
            dst=dst,
            success=False,
            exit_code=1,
            attempts=1,
            duration=0.0,
            tool='copy',
            stdout='',
            stderr=str(exc),
        )
    return TransferOutcome(
        src=src,
        dst=dst,
        success=True,
        exit_code=0,
        attempts=1,
        duration=0.0,
        tool='copy',
        stdout='',
        stderr='',
    )


def transfer_file(
    src: Path,
    dst: Path,
    *,
    tool: str = 'rsync',
    args: Optional[Iterable[str]] = None,
    max_retries: int = 3,
    backoff_seconds: float = 1.0,
    backoff_multiplier: float = 2.0,
    dry_run: bool = False,
) -> TransferOutcome:
    """Transfer ``src`` to ``dst`` with optional retry/backoff."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dry_run:
        return TransferOutcome(
            src=src,
            dst=dst,
            success=True,
            exit_code=0,
            attempts=0,
            duration=0.0,
            tool=tool,
            stdout='dry_run',
            stderr='',
            dry_run=True,
        )

    retries = 0
    delay = max(backoff_seconds, 0)
    args = tuple(args or ())
    last_outcome: Optional[TransferOutcome] = None

    while True:
        start = time.monotonic()
        if tool == 'rsync' and shutil.which('rsync'):
            outcome = _run_rsync(src, dst, args or ('-aHAX', '--partial', '--info=progress2'))
        elif tool == 'rsync':
            outcome = _run_copy(src, dst)
            outcome.tool = 'copy-fallback'
        elif tool == 'copy':
            outcome = _run_copy(src, dst)
        else:
            raise TransferError(f'Unsupported transfer tool: {tool}')

        outcome.duration = time.monotonic() - start
        outcome.attempts = retries + 1
        if outcome.success:
            return outcome

        last_outcome = outcome
        retries += 1
        if retries > max_retries:
            return outcome
        if delay > 0:
            time.sleep(delay)
            delay *= backoff_multiplier

    # Should never reach here
    return last_outcome or TransferOutcome(src, dst, False, 1, retries, 0.0, tool, '', 'unknown error')
