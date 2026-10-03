"""Run a metered AI call on its own thread and stream what it produces.

The call (and the credit settlement in its ``finally``) runs on a worker
thread that doesn't depend on the HTTP response: when the client goes away
mid-stream, the response generator is simply abandoned, but the worker still
finishes, records the usage and settles the credit hold. The response side
only reads from a queue.

``produce(emit, stopped)`` does the work: ``emit(item)`` hands an item to the
response (False once nobody is reading), and ``stopped`` is a
:class:`threading.Event` set when the response has ended, so long-running work
(a Reliability Agent turn) can stop early.
"""

from __future__ import annotations

import logging
import queue
import threading

logger = logging.getLogger(__name__)

_DONE = object()


class Relay:
    def __init__(self, produce, *, maxsize: int = 1024, put_timeout: float = 120.0):
        self._produce = produce
        self._q: queue.Queue = queue.Queue(maxsize=maxsize)
        self._put_timeout = put_timeout
        self.stopped = threading.Event()
        self.thread = threading.Thread(target=self._run, name="ai-relay", daemon=True)

    def start(self) -> "Relay":
        self.thread.start()
        return self

    def _emit(self, item) -> bool:
        if self.stopped.is_set():
            return False
        try:
            self._q.put(item, timeout=self._put_timeout)
            return True
        except queue.Full:  # nobody has read for a long time: the client is gone
            self.stopped.set()
            return False

    def _run(self) -> None:
        try:
            self._produce(self._emit, self.stopped)
        except Exception:  # noqa: BLE001 - produce settles in its own finally
            logger.exception("AI relay worker failed")
        finally:
            try:
                self._q.put(_DONE, timeout=self._put_timeout)
            except queue.Full:
                pass

    def items(self):
        """What the worker emits, in order, until it finishes. Ending this
        generator early (the response was closed) tells the worker to stop."""
        try:
            while True:
                item = self._q.get()
                if item is _DONE:
                    return
                yield item
        finally:
            self.stopped.set()
