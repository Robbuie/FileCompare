"""One worker process per network volume, so a dead share can be killed (1.4).

The loader's threads are fine for a local disk and wrong for a share that
has stopped answering: a thread blocked in an SMB call cannot be stopped, and
each open tab asks every few seconds whether its files changed. Five tabs on
a dead share were enough to pin every thread the loader had, and from then on
every diff, every colouring and every read in the window queued behind them.

So reads, walks and "did it change" checks on a **network** volume run in a
process of their own, one per server (`io/volume.py` says which), the way
File Manager's `io/pool.py` keys its workers. A worker runs each job on a
thread of its own -- a slow job does not hold up a quick one on the same
share -- and when a job misses its deadline the loader asks the pool to
**restart** that worker: the process is killed, every job it still held is
answered with "stopped answering", and the next request starts a fresh one.
A local disk never gets here; it stays on the loader's threads, because a
process costs a start-up and a local disk does not hang that way.

What crosses the boundary is plain data, both ways: the function by its
module and name, its arguments, and back an `(id, ok, value, error)`. Walk
progress comes back as messages too, a few a second, because a shared
counter cannot be handed to a process that is already running; a cancel goes
the other way as a message.

No Qt here. The worker imports only what the job's module imports, which is
why the jobs that run here live in `app/io/` and not beside the Qt classes.
"""

from __future__ import annotations

import multiprocessing
import queue
import threading
import time
import traceback
from typing import Any, Callable

#: Seconds between progress messages from a worker.
TICK = 0.25

#: What a job that was in flight when its worker was killed is told.
STOPPED = "The share stopped answering; its reader was stopped. Retry reads it again."

Deliver = Callable[[int, bool, Any, str], None]
Progressed = Callable[[int, dict], None]


# ------------------------------------------------------------- the child

def _serve(inbox, outbox) -> None:  # pragma: no cover - runs in the child
    """The worker's loop: start each job on a thread, report it, report
    progress, take cancels."""
    from app.io.walk import Progress

    running: dict[int, Progress] = {}
    lock = threading.Lock()
    alive = threading.Event()
    alive.set()

    def run(request: int, fn, args, kwargs, wants_progress: bool) -> None:
        progress = Progress() if wants_progress else None
        if progress is not None:
            with lock:
                running[request] = progress
            kwargs = dict(kwargs, progress=progress)
        try:
            value = fn(*args, **kwargs)
            outbox.put(("done", request, True, value, ""))
        except Exception as exc:  # noqa: BLE001 - reported, never raised across
            detail = "".join(traceback.format_exception_only(type(exc), exc)).strip()
            outbox.put(("done", request, False, None, detail))
        finally:
            with lock:
                running.pop(request, None)

    def tick() -> None:
        while alive.is_set():
            time.sleep(TICK)
            with lock:
                snapshot = list(running.items())
            for request, progress in snapshot:
                outbox.put(("progress", request, {"folders": progress.folders,
                                                  "files": progress.files,
                                                  "current": progress.current}))

    threading.Thread(target=tick, name="progress", daemon=True).start()
    while True:
        message = inbox.get()
        kind = message[0]
        if kind == "stop":
            alive.clear()
            return
        if kind == "cancel":
            with lock:
                progress = running.get(message[1])
            if progress is not None:
                progress.cancel.set()
            continue
        _kind, request, fn, args, kwargs, wants_progress = message
        threading.Thread(target=run, args=(request, fn, args, kwargs, wants_progress),
                         name=f"job-{request}", daemon=True).start()


# ------------------------------------------------------------- the parent

class Worker:
    """One process and the jobs it holds."""

    def __init__(self, key: str, deliver: Deliver, progressed: Progressed) -> None:
        self.key = key
        self._deliver = deliver
        self._progressed = progressed
        context = multiprocessing.get_context("spawn")
        self.inbox = context.Queue()
        self.outbox = context.Queue()
        self.process = context.Process(target=_serve, args=(self.inbox, self.outbox),
                                       name=f"filecompare-{key}", daemon=True)
        self.process.start()
        #: Jobs sent and not yet answered.
        self.pending: set[int] = set()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._reader = threading.Thread(target=self._read, name=f"pool-{key}", daemon=True)
        self._reader.start()

    def submit(self, request: int, fn, args, kwargs, wants_progress: bool) -> None:
        with self._lock:
            self.pending.add(request)
        try:
            self.inbox.put(("run", request, fn, args, kwargs, wants_progress))
        except (OSError, ValueError):
            pass
        # The process can die between the pool's look at it and this line;
        # once its reader has given up nobody would answer this request.
        if not self._reader.is_alive() or not self.process.is_alive():
            self._fail_all("The reader for this share ended unexpectedly. "
                           "Retry reads it again.")

    def cancel(self, request: int) -> None:
        if request in self.pending:
            try:
                self.inbox.put(("cancel", request))
            except (OSError, ValueError):
                pass

    def holds(self, request: int) -> bool:
        return request in self.pending

    def _read(self) -> None:
        while not self._stop.is_set():
            try:
                message = self.outbox.get(timeout=TICK)
            except queue.Empty:
                if not self.process.is_alive():
                    # Died on its own (a crash in a native library): every
                    # job it held is answered, never left waiting -- and the
                    # flag is set first, so a submit racing this one sees a
                    # dead reader and answers its own request.
                    self._stop.set()
                    self._fail_all("The reader for this share ended unexpectedly. "
                                   "Retry reads it again.")
                    return
                continue
            except (EOFError, OSError, ValueError):
                return
            if message[0] == "progress":
                self._progressed(message[1], message[2])
                continue
            _kind, request, ok, value, error = message
            with self._lock:
                if request not in self.pending:
                    continue
                self.pending.discard(request)
            self._deliver(request, ok, value, error)

    def _fail_all(self, why: str) -> None:
        with self._lock:
            held = list(self.pending)
            self.pending.clear()
        for request in held:
            self._deliver(request, False, None, why)

    def kill(self, why: str = STOPPED) -> None:
        """Stop the process whatever it is doing; answer what it held."""
        self._stop.set()
        try:
            self.process.kill()
        except (OSError, AttributeError):
            pass
        self._fail_all(why)
        for channel in (self.inbox, self.outbox):
            try:
                channel.cancel_join_thread()
                channel.close()
            except (OSError, ValueError, AttributeError):
                pass

    def stop(self) -> None:
        """At exit: ask, then kill without waiting on anything stuck."""
        try:
            self.inbox.put(("stop",))
        except (OSError, ValueError):
            pass
        self.kill("Closing")


class Pool:
    """Workers by volume key, started the first time a volume is asked for."""

    def __init__(self, deliver: Deliver, progressed: Progressed) -> None:
        self._deliver = deliver
        self._progressed = progressed
        self._workers: dict[str, Worker] = {}
        self._lock = threading.Lock()

    def submit(self, key: str, request: int, fn, args: tuple, kwargs: dict, *,
               wants_progress: bool = False) -> None:
        with self._lock:
            worker = self._workers.get(key)
            if worker is None or not worker.process.is_alive() or worker._stop.is_set():
                worker = Worker(key, self._deliver, self._progressed)
                self._workers[key] = worker
        worker.submit(request, fn, args, kwargs, wants_progress)

    def cancel(self, request: int) -> None:
        for worker in list(self._workers.values()):
            worker.cancel(request)

    def holds(self, request: int) -> bool:
        return any(w.holds(request) for w in list(self._workers.values()))

    def restart_holding(self, request: int) -> bool:
        """Kill the worker that holds `request`, if one does. True if one did:
        that request and everything else it held have been answered."""
        with self._lock:
            for key, worker in list(self._workers.items()):
                if worker.holds(request):
                    del self._workers[key]
                    break
            else:
                return False
        worker.kill()
        return True

    def keys(self) -> list[str]:
        return list(self._workers)

    def shutdown(self) -> None:
        with self._lock:
            workers = list(self._workers.values())
            self._workers.clear()
        for worker in workers:
            worker.stop()
