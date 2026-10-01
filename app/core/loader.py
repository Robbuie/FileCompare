"""Running work off the UI thread and getting the answer back onto it.

Every read, every "is this a folder", and every diff goes through here. The
window asks, gets a request id, and later receives `finished(id, envelope)` on
its own thread; a reply for an id nobody is waiting on any more -- a tab that
closed, a side that was retried -- is simply dropped by the receiver.

**Threads for work, processes for shares (1.4).** Most of what comes here is
computation -- a diff, a colouring, a table -- and runs on a small thread
pool. A *read* goes through `submit_io` with the path it reads: on a local
disk that is the same thread pool, and on a network volume it is a worker
process of that server's own (`io/pool.py`). The difference matters for one
case, a share that has stopped answering: a thread blocked in an SMB call
cannot be stopped, a process can. When a read misses its deadline the caller
says so with `abandon`, and a worker holding it is killed and started again
on the next request -- so stuck reads never pile up and take the threads the
rest of the window needs.

The envelope is a plain dataclass: success or failure both, never a bare value
the caller has to guess about, and never an exception crossing the boundary.
"""

from __future__ import annotations

import itertools
import traceback
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Callable

from PySide6.QtCore import QObject, Qt, QTimer, Signal

from app.io import volume

#: Enough that one stuck share does not stall the others, few enough that a
#: bad afternoon on the network does not become a hundred blocked threads.
WORKERS = 6


@dataclass
class Envelope:
    ok: bool
    value: Any = None
    error: str = ""


class Loader(QObject):
    """`finished(id, envelope)` always arrives later, on the UI thread.

    Always *later* is the part that was learned the hard way. A read that
    finishes before `submit` returns -- a folder, a missing file -- has its
    done-callback run at once, on the calling thread, before the caller has
    even stored the id it is about to be told about; the answer then matched
    nothing and was dropped, and the side sat on "Reading..." for good. So the
    worker side emits a private signal connected with `QueuedConnection`,
    which posts an event whatever thread it is emitted from, and the public
    signal is re-emitted from the UI thread's event loop. That also settles
    which thread every receiver runs on without relying on Qt's automatic
    choice for a thread it did not start.
    """

    finished = Signal(int, object)
    _ready = Signal(int, object)

    def __init__(self, parent: QObject | None = None, workers: int = WORKERS) -> None:
        super().__init__(parent)
        self._ready.connect(self._relay, Qt.QueuedConnection)
        self._pool = ThreadPoolExecutor(max_workers=workers,
                                        thread_name_prefix="filecompare")
        self._ids = itertools.count(1)
        # 1.4: reads on shares. Made the first time one is asked for, so a
        # session that never touches a share never starts a process.
        self._processes = None
        #: Progress objects of reads running in a worker, by request: the
        #: worker's counts are copied into them, and a cancel set on one is
        #: carried to the worker by `_watch`.
        self._progress: dict[int, Any] = {}
        self._cancelled: set[int] = set()
        self._watch_timer = QTimer(self)
        self._watch_timer.setInterval(250)
        self._watch_timer.timeout.connect(self._watch)

    def submit(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> int:
        """Run `fn(*args, **kwargs)` off the UI thread. Returns the request id."""
        request = next(self._ids)
        future = self._pool.submit(_guard, fn, args, kwargs)
        # The callback runs on the worker thread. Emitting from there to a
        # receiver on the UI thread is a queued connection, which is the whole
        # hand-back mechanism.
        future.add_done_callback(lambda f, r=request: self._done(r, f))
        return request

    def submit_io(self, path: str, fn: Callable[..., Any], *args: Any,
                  progress: Any = None, **kwargs: Any) -> int:
        """A read of `path`: `fn(*args, **kwargs)`, with `progress=` passed on
        when given. On a local disk, the thread pool; on a share, that
        server's worker process, whose counts are copied into `progress`."""
        key = volume.key(path)
        if key == volume.LOCAL:
            if progress is not None:
                kwargs["progress"] = progress
            return self.submit(fn, *args, **kwargs)
        request = next(self._ids)
        if self._processes is None:
            from app.io.pool import Pool

            self._processes = Pool(self._from_pool, self._pool_progress)
        if progress is not None:
            self._progress[request] = progress
            self._watch_timer.start()
        self._processes.submit(key, request, fn, args, kwargs,
                               wants_progress=progress is not None)
        return request

    def abandon(self, request: int) -> bool:
        """A read missed its deadline. If a worker process holds it, that
        worker is killed -- with whatever else it held, which is answered
        with an error -- and the next read of that share starts a new one.
        True if one was."""
        if not request or self._processes is None:
            return False
        self._progress.pop(request, None)
        return self._processes.restart_holding(request)

    def _from_pool(self, request: int, ok: bool, value: Any, error: str) -> None:
        # On the pool's reader thread: hand back exactly as a thread does.
        progress = self._progress.pop(request, None)
        if progress is not None:
            progress.done = True
        try:
            self._ready.emit(request, Envelope(ok, value, error))
        except RuntimeError:
            pass

    def _pool_progress(self, request: int, counts: dict) -> None:
        progress = self._progress.get(request)
        if progress is None:
            return
        progress.folders = counts.get("folders", progress.folders)
        progress.files = counts.get("files", progress.files)
        progress.current = counts.get("current", progress.current)

    def _watch(self) -> None:
        """Carry a cancel set on a progress object to the worker running it."""
        if not self._progress:
            self._watch_timer.stop()
            return
        for request, progress in list(self._progress.items()):
            cancel = getattr(progress, "cancel", None)
            if cancel is not None and cancel.is_set() and request not in self._cancelled:
                self._cancelled.add(request)
                if self._processes is not None:
                    self._processes.cancel(request)

    def _done(self, request: int, future: Future) -> None:
        try:
            envelope = future.result()
        except Exception as exc:  # noqa: BLE001 - cancelled, or the pool died
            envelope = Envelope(False, error=str(exc) or type(exc).__name__)
        try:
            self._ready.emit(request, envelope)
        except RuntimeError:
            # The receiver's C++ half has gone: the window closed while this
            # was running. Nobody to tell.
            pass

    def _relay(self, request: int, envelope: Envelope) -> None:
        self.finished.emit(request, envelope)

    def shutdown(self) -> None:
        """Stop taking work. Does not wait: a thread stuck on a share would
        hold the window open on the way out, which is the hang in a new place."""
        self._pool.shutdown(wait=False, cancel_futures=True)
        self._watch_timer.stop()
        if self._processes is not None:
            self._processes.shutdown()
            self._processes = None


def _guard(fn: Callable[..., Any], args: tuple, kwargs: dict) -> Envelope:
    try:
        return Envelope(True, fn(*args, **kwargs))
    except Exception as exc:  # noqa: BLE001 - reported, never raised across
        detail = "".join(traceback.format_exception_only(type(exc), exc)).strip()
        return Envelope(False, error=detail)
