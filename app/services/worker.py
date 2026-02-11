from __future__ import annotations

import logging
import threading
import time

from app.core.config import get_settings
from app.core.db import get_session_maker
from app.services.training import TrainingOrchestrator

logger = logging.getLogger(__name__)


class BackgroundWorker:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    def start(self) -> None:
        if not self.settings.enable_background_worker:
            logger.info("background_worker_disabled")
            return
        if self._thread and self._thread.is_alive():
            return

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info("background_worker_started")

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        logger.info("background_worker_stopped")

    def _run_loop(self) -> None:
        session_maker = get_session_maker()
        while not self._stop_event.is_set():
            try:
                with session_maker() as db:
                    orchestrator = TrainingOrchestrator(db)
                    processed = 0
                    while processed < 3:
                        run = orchestrator.process_next_queued_run()
                        if not run:
                            break
                        processed += 1
                        logger.info("processed_run", extra={"run_id": run.id, "state": run.state.value})
            except Exception:
                logger.exception("background_worker_cycle_failed")
            finally:
                self._stop_event.wait(self.settings.worker_poll_seconds)
