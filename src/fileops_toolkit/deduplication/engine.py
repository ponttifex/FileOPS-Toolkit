"""Deduplication engine for FileOps Toolkit.

Implements simple policies for resolving duplicates based on file name,
size, modification time and checksum.  This is a stub designed to be
extended; it currently performs a basic selection of the preferred file
and returns a list of decisions.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from itertools import count
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from ..metadata.scanner import FileMetadata, get_file_metadata


class Decision(Enum):
    COPY = auto()
    SKIP = auto()
    REPLACE = auto()
    DUPLICATE = auto()
    COPY_WITH_SUFFIX = auto()
    ERROR = auto()


@dataclass
class DedupResult:
    src: FileMetadata
    dest_path: Path
    decision: Decision
    reason: str
    dst_exists: bool = False
    existing_metadata: Optional[FileMetadata] = None
    backup_path: Optional[Path] = None
    should_transfer: bool = False
    suffix_applied: Optional[str] = None
    message: Optional[str] = None
    duplicate_action: str = 'skip'
    archive_path: Optional[Path] = None


def _primary_checksum(meta: FileMetadata, preferred_algos: Sequence[str]) -> Optional[str]:
    for algo in preferred_algos:
        checksum = meta.get_checksum(algo)
        if checksum:
            return checksum
    return meta.checksum


def _metadata_equal(a: FileMetadata, b: FileMetadata, preferred_algos: Sequence[str]) -> bool:
    if a.size_bytes != b.size_bytes:
        return False
    checksum_a = _primary_checksum(a, preferred_algos)
    checksum_b = _primary_checksum(b, preferred_algos)
    if checksum_a and checksum_b:
        return checksum_a == checksum_b
    # Fall back to modification time if checksum not available.
    return abs(a.mtime - b.mtime) < 1e-3


def _duplicate_reason(candidate: FileMetadata, winner: FileMetadata) -> str:
    if candidate.size_bytes != winner.size_bytes:
        return 'size_diff'
    if candidate.mtime != winner.mtime:
        return 'newer' if candidate.mtime < winner.mtime else 'older'
    if candidate.checksum and winner.checksum and candidate.checksum == winner.checksum:
        return 'hash_match'
    return 'policy_prefer_newer'


def _unique_dest_path(base_dir: Path, filename: str, used: Dict[Path, int]) -> Tuple[Path, Optional[str]]:
    path = base_dir / filename
    if path not in used and not path.exists():
        used[path] = 0
        return path, None
    stem = Path(filename).stem
    ext = ''.join(Path(filename).suffixes)
    counter = used.get(path, 0) + 1
    while True:
        candidate = base_dir / f'{stem}_{counter}{ext}'
        if candidate not in used and not candidate.exists():
            used[path] = counter
            used[candidate] = 0
            return candidate, f'_{counter}'
        counter += 1


def _load_destination_metadata(
    dest_path: Path,
    preferred_algos: Sequence[str],
    cache: Dict[Path, Optional[FileMetadata]],
) -> Optional[FileMetadata]:
    if dest_path in cache:
        return cache[dest_path]
    if not dest_path.exists():
        cache[dest_path] = None
        return None
    cache[dest_path] = get_file_metadata(dest_path, preferred_algos)
    return cache[dest_path]


def _build_backup_path(dest_path: Path, backup_dir: Path) -> Path:
    candidate = backup_dir / dest_path.name
    if not candidate.exists():
        return candidate
    stem = dest_path.stem
    suffix = ''.join(dest_path.suffixes)
    for idx in count(1):
        candidate = backup_dir / f'{stem}_{idx}{suffix}'
        if not candidate.exists():
            return candidate


def deduplicate(
    files: Iterable[FileMetadata],
    destination: Path,
    policy: str = 'prefer_newer',
    preferred_algos: Optional[Sequence[str]] = None,
    backup_dir: Optional[Path] = None,
    *,
    operation_mode: str = 'flatten',
    duplicate_action: str = 'skip',
    duplicate_archive_dir: Optional[Path] = None,
    mirror_prefix_with_root: bool = True,
) -> List[DedupResult]:
    """Plan deduplication operations for discovered files.

    Args:
        files: Metadata describing candidate source files.
        destination: Base directory to place resulting files.
        policy: Deduplication policy (``prefer_newer`` or ``keep_both_with_suffix``).
        preferred_algos: Priority order for checksum comparison.
        backup_dir: Optional directory to store overwritten files.
    """
    preferred_algos = tuple(algo.lower() for algo in (preferred_algos or ()))
    destination = destination.expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)
    if backup_dir:
        backup_dir = backup_dir.expanduser().resolve()
        backup_dir.mkdir(parents=True, exist_ok=True)
    if duplicate_archive_dir:
        duplicate_archive_dir = duplicate_archive_dir.expanduser().resolve()
        duplicate_archive_dir.mkdir(parents=True, exist_ok=True)

    if operation_mode == 'mirror':
        planned: List[DedupResult] = []
        for meta in files:
            relative = meta.relative_path or Path(meta.path.name)
            if mirror_prefix_with_root and meta.source_root:
                relative = Path(meta.source_root.name) / relative
            dest_path = destination / relative
            planned.append(
                DedupResult(
                    src=meta,
                    dest_path=dest_path,
                    decision=Decision.COPY,
                    reason='mirror_mode',
                    dst_exists=dest_path.exists(),
                    should_transfer=True,
                )
            )
        return planned

    grouped: Dict[str, List[FileMetadata]] = {}
    for meta in files:
        grouped.setdefault(meta.path.name, []).append(meta)

    existing_cache: Dict[Path, Optional[FileMetadata]] = {}
    planned: List[DedupResult] = []
    used_names: Dict[Path, int] = {}

    for name, metas in sorted(grouped.items()):
        metas_sorted = sorted(metas, key=lambda m: (m.size_bytes, m.mtime), reverse=True)
        if policy not in {'prefer_newer', 'keep_both_with_suffix'}:
            raise ValueError(f'Unknown policy {policy}')

        if policy == 'prefer_newer':
            winner = metas_sorted[0]
            dest_path = destination / winner.path.name
            existing = _load_destination_metadata(dest_path, preferred_algos, existing_cache)
            if existing and _metadata_equal(winner, existing, preferred_algos):
                planned.append(
                    DedupResult(
                        src=winner,
                        dest_path=dest_path,
                        decision=Decision.SKIP,
                        reason='existing_identical',
                        dst_exists=True,
                        existing_metadata=existing,
                        should_transfer=False,
                    )
                )
            else:
                backup_path = None
                reason = 'unique'
                decision = Decision.COPY
                if existing:
                    reason = _duplicate_reason(existing, winner)
                    decision = Decision.REPLACE
                    if backup_dir:
                        backup_path = _build_backup_path(dest_path, backup_dir)
                planned.append(
                    DedupResult(
                        src=winner,
                        dest_path=dest_path,
                        decision=decision,
                        reason=reason,
                        dst_exists=existing is not None,
                        existing_metadata=existing,
                        backup_path=backup_path,
                        should_transfer=True,
                    )
                )

            for meta in metas_sorted[1:]:
                planned.append(
                    DedupResult(
                        src=meta,
                        dest_path=destination / meta.path.name,
                        decision=Decision.DUPLICATE,
                        reason=_duplicate_reason(meta, winner),
                        should_transfer=False,
                        duplicate_action=duplicate_action,
                        archive_path=(
                            _build_backup_path(destination / meta.path.name, duplicate_archive_dir)
                            if duplicate_action == 'archive' and duplicate_archive_dir
                            else None
                        )
                    )
                )
        else:  # keep_both_with_suffix
            for idx, meta in enumerate(metas_sorted, start=1):
                dest_path, suffix = _unique_dest_path(destination, meta.path.name, used_names)
                existing = _load_destination_metadata(dest_path, preferred_algos, existing_cache)
                if existing and _metadata_equal(meta, existing, preferred_algos):
                    planned.append(
                        DedupResult(
                            src=meta,
                            dest_path=dest_path,
                            decision=Decision.SKIP,
                            reason='existing_identical',
                            dst_exists=True,
                            existing_metadata=existing,
                            should_transfer=False,
                            suffix_applied=suffix,
                        )
                    )
                    continue
                decision = Decision.COPY_WITH_SUFFIX if suffix else Decision.COPY
                planned.append(
                    DedupResult(
                        src=meta,
                        dest_path=dest_path,
                        decision=decision,
                        reason='keep_both',
                        dst_exists=existing is not None,
                        existing_metadata=existing,
                        should_transfer=True,
                        suffix_applied=suffix,
                    )
                )

    # Resolve duplicates by checksum across different file names.
    seen_hashes: Dict[str, DedupResult] = {}
    final_results: List[DedupResult] = []
    for result in planned:
        primary_hash = _primary_checksum(result.src, preferred_algos)
        if (
            primary_hash
            and result.decision in {Decision.COPY, Decision.REPLACE, Decision.COPY_WITH_SUFFIX}
            and result.should_transfer
        ):
            if primary_hash in seen_hashes:
                final_results.append(
                    DedupResult(
                        src=result.src,
                        dest_path=result.dest_path,
                        decision=Decision.DUPLICATE,
                        reason='hash_match',
                        dst_exists=result.dst_exists,
                        existing_metadata=result.existing_metadata,
                        backup_path=result.backup_path,
                        should_transfer=False,
                        duplicate_action=duplicate_action,
                        archive_path=(
                            _build_backup_path(result.dest_path, duplicate_archive_dir)
                            if duplicate_action == 'archive' and duplicate_archive_dir
                            else None
                        ),
                    )
                )
                continue
            seen_hashes[primary_hash] = result
        final_results.append(result)

    return final_results
