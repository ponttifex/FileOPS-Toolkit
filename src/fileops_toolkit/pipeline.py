"""Pipeline orchestration for FileOps Toolkit."""

from __future__ import annotations

import shutil
import threading
import time
import uuid
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, Union

from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)

from .deduplication.engine import DedupResult, Decision, deduplicate
from .discovery.engine import DiscoveredFile, discover_files
from .logging.logger import OperationLoggers, log_operation, setup_loggers
from .metadata.scanner import FileMetadata, get_file_metadata
from .prechecks import PreflightReport, run_prechecks
from .supervisor.manager import WorkerSupervisor
from .transfer.engine import TransferOutcome, transfer_file
from .verification.engine import verify_file
from .remote import extract_remote_sources, stage_remote_sources


ChecksumConfig = Optional[Union[str, Sequence[str]]]


@dataclass(slots=True)
class OperationOutcome:
    result: DedupResult
    transfer: Optional[TransferOutcome]
    verified: Optional[bool]
    worker: str


@dataclass(slots=True)
class PipelineStats:
    run_id: str
    discovered_files: int
    metadata_collected: int
    dry_run: bool
    duration_seconds: float
    decision_counts: Dict[str, int]
    errors: int
    csv_log: Path
    json_log: Path
    report: PreflightReport


def _normalise_algorithms(configured: ChecksumConfig) -> List[str]:
    if configured is None:
        return []
    if isinstance(configured, str):
        configured = [configured]
    return [item.lower() for item in configured]


def _create_metadata_progress(console: Optional[Console], total: int) -> Progress:
    columns = (
        SpinnerColumn(),
        TextColumn('[progress.description]{task.description}'),
        BarColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
    )
    return Progress(*columns, console=console, transient=True, disable=console is None, expand=True)


def _make_transfer_task(
    result: DedupResult,
    *,
    tool: str,
    args: Sequence[str],
    dry_run: bool,
    max_retries: int,
    backoff_seconds: float,
    backoff_multiplier: float,
    verify_algorithms: Sequence[str],
    verify_after_transfer: bool,
) -> Callable[[], OperationOutcome]:
    def task() -> OperationOutcome:
        worker = threading.current_thread().name
        transfer_outcome: Optional[TransferOutcome] = None
        verified: Optional[bool] = None
        start = time.monotonic()
        try:
            if (
                result.backup_path
                and not dry_run
                and result.dest_path.exists()
                and not result.backup_path.exists()
            ):
                result.backup_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(result.dest_path, result.backup_path)
            transfer_outcome = transfer_file(
                result.src.path,
                result.dest_path,
                tool=tool,
                args=args,
                max_retries=max_retries,
                backoff_seconds=backoff_seconds,
                backoff_multiplier=backoff_multiplier,
                dry_run=dry_run,
            )
            if verify_after_transfer and transfer_outcome.success and not dry_run:
                verified = verify_file(
                    result.src.path,
                    result.dest_path,
                    checksum_algos=verify_algorithms,
                    src_metadata=result.src,
                )
            elif transfer_outcome.dry_run:
                verified = None
            else:
                verified = transfer_outcome.success
        except Exception as exc:  # pragma: no cover - defensive path
            duration = time.monotonic() - start
            transfer_outcome = TransferOutcome(
                src=result.src.path,
                dst=result.dest_path,
                success=False,
                exit_code=1,
                attempts=1,
                duration=duration,
                tool=tool,
                stdout='',
                stderr=str(exc),
                dry_run=dry_run,
            )
            verified = False
        return OperationOutcome(result=result, transfer=transfer_outcome, verified=verified, worker=worker)

    return task


def execute_pipeline(
    cfg: Dict[str, Any],
    *,
    console: Optional[Console] = None,
    dry_run_override: Optional[bool] = None,
) -> Tuple[PipelineStats, List[DedupResult], List[OperationOutcome]]:
    """Execute the full FileOps pipeline."""
    local_sources, remote_sources = extract_remote_sources(cfg)
    extensions = cfg.get('extensions')
    destination = Path(cfg['destination']).expanduser()
    backup_dir = Path(cfg['backup_duplicates_to']).expanduser() if cfg.get('backup_duplicates_to') else None
    dry_run = cfg.get('dry_run', True) if dry_run_override is None else dry_run_override
    checksum_algorithms = _normalise_algorithms(cfg.get('checksum_algo'))
    parallel_workers = int(cfg.get('parallel_workers', 4))
    transfer_tool = cfg.get('transfer_tool', 'rsync')
    transfer_args = tuple(cfg.get('rsync_args', []))
    verify_after_transfer = cfg.get('verify_after_transfer', True)
    max_retries = int(cfg.get('max_retries', 3))
    backoff_seconds = float(cfg.get('retry_backoff_seconds', 1.0))
    backoff_multiplier = float(cfg.get('retry_backoff_multiplier', 2.0))
    patterns: Sequence[str] | None = cfg.get('patterns')
    pattern_mode = cfg.get('pattern_mode', 'glob')
    case_sensitive_patterns = bool(cfg.get('pattern_case_sensitive', False))
    operation_mode = cfg.get('operation_mode', 'flatten')
    duplicate_action = cfg.get('duplicates_policy', 'skip')
    duplicate_archive_dir = Path(cfg['duplicates_archive_dir']).expanduser() if cfg.get('duplicates_archive_dir') else None
    mirror_prefix_with_root = bool(cfg.get('mirror_prefix_with_root', True))

    if duplicate_action == 'archive' and not duplicate_archive_dir:
        raise RuntimeError('duplicates_policy is set to archive but duplicates_archive_dir is not configured.')

    remote_staging_dir = Path(cfg.get('remote_staging_dir', './data/remote_staging'))
    remote_parallel = int(cfg.get('remote_parallel_workers', parallel_workers))
    remote_default_args = cfg.get('remote_rsync_args') or cfg.get('rsync_args')

    run_id = uuid.uuid4().hex
    start_time = time.monotonic()
    precheck_cfg = dict(cfg)
    precheck_cfg['sources'] = local_sources
    report = run_prechecks(precheck_cfg, remote_sources=remote_sources)
    if report.errors:
        raise RuntimeError('Prechecks failed:\n' + '\n'.join(report.errors))

    staged_remote = stage_remote_sources(
        remote_sources,
        staging_root=remote_staging_dir,
        default_rsync_args=remote_default_args,
        dry_run=dry_run,
        parallelism=remote_parallel,
        console=console,
    )

    for result in staged_remote:
        stage_note = 'Remote staged' if not result.dry_run else 'Remote staged (dry-run)'
        report.info.append(f'{stage_note}: {result.config.target} -> {result.staging_path}')

    effective_sources = [
        str(Path(src).expanduser()) for src in local_sources
    ] + [str(item.staging_path) for item in staged_remote]

    discovered: List[DiscoveredFile] = list(
        discover_files(
            effective_sources or [],
            extensions,
            patterns=patterns,
            pattern_mode=pattern_mode,
            case_sensitive=case_sensitive_patterns,
        )
    )
    metadata: List[FileMetadata] = []
    metadata_progress = _create_metadata_progress(console, len(discovered))
    with metadata_progress:
        task_id: Optional[int] = None
        if discovered:
            task_id = metadata_progress.add_task('Collecting metadata', total=len(discovered))
        for item in discovered:
            metadata.append(
                get_file_metadata(
                    Path(item.path),
                    checksum_algorithms,
                    source_root=item.root,
                    relative_path=item.relative_path,
                )
            )
            if task_id is not None:
                metadata_progress.advance(task_id)

    dedup_results = deduplicate(
        metadata,
        destination=destination,
        policy=cfg.get('deduplication_policy', 'prefer_newer'),
        preferred_algos=checksum_algorithms,
        backup_dir=backup_dir,
        operation_mode=operation_mode,
        duplicate_action=duplicate_action,
        duplicate_archive_dir=duplicate_archive_dir,
        mirror_prefix_with_root=mirror_prefix_with_root,
    )

    loggers = setup_loggers(cfg.get('logging', {}), run_id)
    decision_counts = Counter(result.decision.name.lower() for result in dedup_results)
    transfer_candidates = [result for result in dedup_results if result.should_transfer]
    skipped_results = [result for result in dedup_results if not result.should_transfer]
    operation_outcomes: List[OperationOutcome] = []
    errors = 0

    try:
        for result in skipped_results:
            transfer_record: Optional[TransferOutcome] = None
            verified_flag = False if result.decision == Decision.DUPLICATE else None
            if (
                result.decision == Decision.DUPLICATE
                and result.duplicate_action in {'archive', 'delete'}
                and not dry_run
            ):
                try:
                    if result.duplicate_action == 'archive' and result.archive_path:
                        result.archive_path.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(result.src.path, result.archive_path)
                        result.message = f'archived_duplicate->{result.archive_path}'
                    elif result.duplicate_action == 'delete':
                        result.src.path.unlink(missing_ok=True)  # type: ignore[arg-type]
                        result.message = 'duplicate_deleted'
                    verified_flag = True
                except Exception as exc:  # pragma: no cover - defensive
                    result.message = f'duplicate_action_failed:{exc}'
                    errors += 1
            log_operation(
                loggers,
                run_id=run_id,
                worker='planner',
                result=result,
                transfer=transfer_record,
                verified=verified_flag,
                preferred_algos=checksum_algorithms,
            )

        transfer_progress: Optional[Progress] = None
        transfer_task_id: Optional[int] = None
        if transfer_candidates:
            transfer_progress = _create_metadata_progress(console, len(transfer_candidates))

        def handle_outcome(outcome: OperationOutcome) -> None:
            operation_outcomes.append(outcome)
            if transfer_progress and transfer_task_id is not None:
                transfer_progress.advance(transfer_task_id)
            log_operation(
                loggers,
                run_id=run_id,
                worker=outcome.worker,
                result=outcome.result,
                transfer=outcome.transfer,
                verified=outcome.verified,
                preferred_algos=checksum_algorithms,
            )

        if transfer_progress:
            with transfer_progress:
                transfer_task_id = transfer_progress.add_task('Transferring files', total=len(transfer_candidates))
                task_factories = [
                    _make_transfer_task(
                        result,
                        tool=transfer_tool,
                        args=transfer_args,
                        dry_run=dry_run,
                        max_retries=max_retries,
                        backoff_seconds=backoff_seconds,
                        backoff_multiplier=backoff_multiplier,
                        verify_algorithms=checksum_algorithms,
                        verify_after_transfer=verify_after_transfer,
                    )
                    for result in transfer_candidates
                ]
                with WorkerSupervisor(max_workers=parallel_workers) as supervisor:
                    supervisor.run_tasks(task_factories, progress_callback=handle_outcome)
        else:
            task_factories = [
                _make_transfer_task(
                    result,
                    tool=transfer_tool,
                    args=transfer_args,
                    dry_run=dry_run,
                    max_retries=max_retries,
                    backoff_seconds=backoff_seconds,
                    backoff_multiplier=backoff_multiplier,
                    verify_algorithms=checksum_algorithms,
                    verify_after_transfer=verify_after_transfer,
                )
                for result in transfer_candidates
            ]
            with WorkerSupervisor(max_workers=parallel_workers) as supervisor:
                supervisor.run_tasks(task_factories, progress_callback=handle_outcome)

        errors = sum(
            1
            for outcome in operation_outcomes
            if (outcome.transfer and not outcome.transfer.success) or outcome.verified is False
        )
    finally:
        loggers.close()
    duration = time.monotonic() - start_time
    stats = PipelineStats(
        run_id=run_id,
        discovered_files=len(discovered),
        metadata_collected=len(metadata),
        dry_run=dry_run,
        duration_seconds=duration,
        decision_counts=dict(decision_counts),
        errors=errors,
        csv_log=loggers.csv.path,
        json_log=loggers.json.path,
        report=report,
    )
    return stats, dedup_results, operation_outcomes
