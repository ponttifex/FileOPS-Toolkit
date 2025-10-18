"""Verification module for FileOps Toolkit.

After files are transferred, this module checks that the destination file
matches the source file in size and (optionally) checksum(s).
"""

from __future__ import annotations

from pathlib import Path
from typing import Mapping, Optional, Sequence, Union

from ..metadata.scanner import FileMetadata, compute_checksum

ChecksumRequest = Optional[Union[str, Sequence[str]]]


def _normalise(request: ChecksumRequest) -> Sequence[str]:
    if request is None:
        return ()
    if isinstance(request, str):
        return (request.lower(),)
    return tuple(algo.lower() for algo in request)


def verify_file(
    src: Path,
    dst: Path,
    checksum_algos: ChecksumRequest = None,
    src_metadata: Optional[FileMetadata] = None,
) -> bool:
    """Verify that ``dst`` matches ``src``.

    Args:
        src: Source file path.
        dst: Destination file path.
        checksum_algos: Optional checksum algorithm(s) to compare.
        src_metadata: Optional metadata with precomputed checksums.
    """
    try:
        src_stat = src.stat()
        dst_stat = dst.stat()
    except FileNotFoundError:
        return False

    if src_stat.st_size != dst_stat.st_size:
        return False

    algorithms = _normalise(checksum_algos)
    if not algorithms:
        return True

    src_checksums: Mapping[str, str] = {}
    if src_metadata:
        src_checksums = {k.lower(): v for k, v in src_metadata.checksums.items()}

    for algo in algorithms:
        src_checksum = src_checksums.get(algo)
        if src_checksum is None:
            src_checksum = compute_checksum(src, algo)
        dst_checksum = compute_checksum(dst, algo)
        if src_checksum != dst_checksum:
            return False
    return True
