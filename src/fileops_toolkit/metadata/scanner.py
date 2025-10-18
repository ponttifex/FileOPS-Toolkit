"""Metadata scanning for FileOps Toolkit.

Collects filesystem metadata and optional checksums for files discovered
by the discovery engine.  Hash algorithms are selected via configuration.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, Optional, Sequence, Union

try:
    import xxhash
except ImportError:  # pragma: no cover
    xxhash = None  # type: ignore


ChecksumRequest = Optional[Union[str, Sequence[str]]]


def _normalise_algorithms(request: ChecksumRequest) -> list[str]:
    if request is None:
        return []
    if isinstance(request, str):
        request = [request]
    return [algo.lower() for algo in request]


@dataclass(slots=True)
class FileMetadata:
    path: Path
    size_bytes: int
    mtime: float
    checksums: Dict[str, str] = field(default_factory=dict)
    stat: Optional[os.stat_result] = None
    source_root: Optional[Path] = None
    relative_path: Optional[Path] = None

    def get_checksum(self, algo: Optional[str] = None) -> Optional[str]:
        if not self.checksums:
            return None
        if algo is None:
            # Return the first checksum stored (preserves caller expectation of single value).
            return next(iter(self.checksums.values()))
        return self.checksums.get(algo.lower())

    @property
    def checksum(self) -> Optional[str]:
        return self.get_checksum()


def compute_checksum(path: Path, algo: str) -> str:
    """Compute a checksum of a file using the given algorithm.

    Supported algorithms: ``md5``, ``sha1``, ``xxh128`` (requires ``xxhash``).
    """
    if algo.lower() == 'md5':
        h = hashlib.md5()
    elif algo.lower() == 'sha1':
        h = hashlib.sha1()
    elif algo.lower() == 'xxh128':
        if xxhash is None:
            raise RuntimeError('xxhash module not installed')
        h = xxhash.xxh3_128()  # type: ignore[assignment]
    else:
        raise ValueError(f'Unsupported checksum algorithm: {algo}')
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            h.update(chunk)
    return h.hexdigest()


def get_file_metadata(
    path: Path,
    checksum_algo: ChecksumRequest = None,
    *,
    source_root: Optional[Path] = None,
    relative_path: Optional[Path] = None,
) -> FileMetadata:
    """Gather file metadata and optional checksum.

    Args:
        path: The file path.
        checksum_algo: Single algorithm or sequence of algorithms to compute (case-insensitive).

    Returns:
        ``FileMetadata`` with size, modification time and optional checksum.
    """
    stat = path.stat()
    checksums: Dict[str, str] = {}
    for algo in _normalise_algorithms(checksum_algo):
        checksums[algo] = compute_checksum(path, algo)
    return FileMetadata(
        path=path,
        size_bytes=stat.st_size,
        mtime=stat.st_mtime,
        checksums=checksums,
        stat=stat,
        source_root=source_root,
        relative_path=relative_path,
    )
