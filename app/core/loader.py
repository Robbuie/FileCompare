"""Running work off the UI thread and getting the answer back onto it.

Every read, every "is this a folder", and every diff goes through here. The
window asks, gets a request id, and later receives `finished(id, envelope)` on
its own thread; a reply for an id nobody is waiting on any more -- a tab that
closed, a side that was retried -- is simply dropped by the receiver.

**Threads, for now, not File Manager's worker processes.** The difference
matters for exactly one case: a read from a share that has stopped answering.
A process can be killed; a thread blocked in an SMB call cannot. What this
module guarantees is the part that matters to the window -- it never waits,
the side shows "not answering" at its deadline with a retry, and the late
answer is thrown away -- but the stuck thread stays stuck until Windows gives
up on the call. With a handful of threads that is a bounded cost, and folder
compare (which walks whole trees on shares) is where porting File Manager's
per-volume worker pool earns its keep; see CLAUDE.md's build order.

The envelope is a plain dataclass: success or failure both, never a bare value
the caller has to guess about, and never an exception crossing the boundary.
"""

from __future__ import annotations

import itertools
import traceback
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Callable

from PySide6.QtCore import QObject, Qt, Signal

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

    def submit(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> int:
        """Run `fn(*args, **kwargs)` off the UI thread. Returns the request id."""
        request = next(self._ids)
        future = self._pool.submit(_guard, fn, args, kwargs)
        # The callback runs on the worker thread. Emitting from there to a
        # receiver on the UI thread is a queued connection, which is the whole
        # hand-back mechanism.
        future.add_done_callback(lambda f, r=request: self._done(r, f))
        return request

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


def _guard(fn: Callable[..., Any], args: tuple, kwargs: dict) -> Envelope:
    try:
        return Envelope(True, fn(*args, **kwargs))
    except Exception as exc:  # noqa: BLE001 - reported, never raised across
        detail = "".join(traceback.format_exception_only(type(exc), exc)).strip()
        return Envelope(False, error=detail)
