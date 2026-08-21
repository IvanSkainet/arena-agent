"""Lightweight context manager for measuring latency and execution duration."""
import time
from contextlib import contextmanager
from typing import Generator

class TimingResult:
    def __init__(self) -> None:
        self.duration_seconds: float = 0.0
        self.duration_ms: float = 0.0

@contextmanager
def time_block() -> Generator[TimingResult, None, None]:
    """Measure execution duration in seconds and milliseconds."""
    res = TimingResult()
    start = time.perf_counter()
    try:
        yield res
    finally:
        elapsed = time.perf_counter() - start
        res.duration_seconds = elapsed
        res.duration_ms = elapsed * 1000.0
