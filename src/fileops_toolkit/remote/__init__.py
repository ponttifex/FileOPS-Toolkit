"""Remote source helpers for FileOps Toolkit."""

from .sync import (
    RemoteSourceConfig,
    RemoteStageResult,
    RemoteSyncError,
    extract_remote_sources,
    is_remote_target,
    sanitize_label,
    stage_remote_sources,
)

__all__ = [
    'RemoteSourceConfig',
    'RemoteStageResult',
    'RemoteSyncError',
    'extract_remote_sources',
    'is_remote_target',
    'sanitize_label',
    'stage_remote_sources',
]
