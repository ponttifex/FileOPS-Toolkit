"""Worker supervisor for FileOps Toolkit.

Uses a thread pool to execute callable tasks with progress callbacks and
simple cancellation support.
"""

from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from typing import Callable, Iterable, Iterator, List, Optional, TypeVar

T = TypeVar('T')


class WorkerSupervisor:
    """Manage worker threads for parallel operations."""

    def __init__(self, max_workers: int = 4):
        self.max_workers = max_workers
        self._executor: Optional[ThreadPoolExecutor] = None
        self._futures: List[Future[T]] = []

    def __enter__(self) -> 'WorkerSupervisor':
        self._executor = ThreadPoolExecutor(max_workers=self.max_workers, thread_name_prefix='fileops-worker')
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.shutdown(wait=True)

    def submit(self, task: Callable[[], T]) -> Future[T]:
        if self._executor is None:
            self._executor = ThreadPoolExecutor(max_workers=self.max_workers, thread_name_prefix='fileops-worker')
        future = self._executor.submit(task)
        self._futures.append(future)
        return future

    def run_tasks(
        self,
        tasks: Iterable[Callable[[], T]],
        progress_callback: Optional[Callable[[T], None]] = None,
    ) -> List[T]:
        """Run callables and return their results."""
        results: List[T] = []
        for task in tasks:
            self.submit(task)

        while self._futures:
            done, _ = wait(self._futures, return_when=FIRST_COMPLETED)
            for future in list(done):
                self._futures.remove(future)
                result = future.result()
                results.append(result)
                if progress_callback:
                    progress_callback(result)
        return results

    def shutdown(self, wait: bool = False) -> None:
        if self._executor:
            self._executor.shutdown(wait=wait)
            self._executor = None
        self._futures.clear()
