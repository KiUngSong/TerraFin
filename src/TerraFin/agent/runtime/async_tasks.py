"""Async task handle used by the hosted runtime's dispatcher pool."""
from concurrent.futures import Future
from threading import Event


class _AsyncTaskHandle:
    def __init__(self, session_id: str, task_id: str) -> None:
        self.session_id = session_id
        self.task_id = task_id
        self.cancel_event = Event()
        self.future: Future[None] | None = None
