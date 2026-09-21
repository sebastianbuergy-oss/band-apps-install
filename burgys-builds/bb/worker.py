"""The queue worker.

Without this, the API can *accept* a build and nothing ever runs it - fine
while a human types ``burgys run``, useless for Buergys Agent.  The worker
drains the queue in the background while the server is up.

It cannot start anything a human has not cleared: a build that needs
approval never reaches the queue in the first place (see
:meth:`bb.builds.BuildController.request_build`), so the worker only ever
picks up work that is already allowed to run.  The cost guard is checked
again inside the run, not here, so this class has no say over money.
"""
from __future__ import annotations

import threading
import time

from . import audit as A


class Worker:
    def __init__(self, controller, *, interval: float = 2.0,
                 poll_interval: float = 5.0) -> None:
        self.controller = controller
        self.interval = interval
        self.poll_interval = poll_interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.completed = 0
        self.errors = 0

    # -- lifecycle -----------------------------------------------------
    def start(self) -> "Worker":
        if self._thread is not None:
            return self
        self._thread = threading.Thread(target=self._loop, name="burgys-worker",
                                        daemon=True)
        self._thread.start()
        self.controller.audit.record(A.BUILD_STATE, actor="worker",
                                     result="started")
        return self

    def stop(self, timeout: float = 30.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # -- the loop ------------------------------------------------------
    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                manifest = self.controller.run_next(
                    poll_interval=self.poll_interval)
            except Exception as exc:  # noqa: BLE001
                # One bad build must not take the worker down; the build
                # itself is already marked FAILED by the controller.
                self.errors += 1
                self.controller.audit.record(
                    A.BUILD_STATE, actor="worker", result="error",
                    detail=f"{type(exc).__name__}: {exc}"[:300])
                manifest = None
            if manifest is None:
                self._stop.wait(self.interval)
            else:
                self.completed += 1

    def drain(self, timeout: float = 60.0) -> int:
        """Run everything currently queued and return how many finished.

        Used by tests and by ``burgys run --all``; the background loop is
        the normal path.
        """
        done = 0
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            manifest = self.controller.run_next(poll_interval=self.poll_interval)
            if manifest is None:
                return done
            done += 1
        return done
