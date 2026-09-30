"""One window, however many times the program is started.

Pressing Ctrl+F2 five times in File Manager starts this program five times.
Five windows is the wrong answer; one window with five tabs is the right one.
So the first instance listens on a named local socket, and every later one
connects, hands over its arguments and its working directory, and exits.

The working directory goes with the arguments because relative paths were
typed relative to *it*, and the listening instance has its own.

The message is one line of JSON. The encoding and decoding are plain functions
so the tests can check them without a socket.
"""

from __future__ import annotations

import getpass
import json

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

#: How long a second instance waits for the first to answer before deciding
#: there is no first and becoming it.
CONNECT_MS = 400


def server_name() -> str:
    try:
        user = getpass.getuser()
    except Exception:  # noqa: BLE001 - no user name is not worth failing over
        user = "user"
    return f"FileCompare-{user}"


def encode(argv: list[str], cwd: str) -> bytes:
    return (json.dumps({"argv": list(argv), "cwd": cwd}) + "\n").encode("utf-8")


def decode(data: bytes) -> tuple[list[str], str] | None:
    try:
        message = json.loads(data.decode("utf-8").strip() or "null")
    except (UnicodeDecodeError, ValueError):
        return None
    if not isinstance(message, dict):
        return None
    argv = message.get("argv")
    cwd = message.get("cwd")
    if not isinstance(argv, list) or not all(isinstance(a, str) for a in argv):
        return None
    return argv, cwd if isinstance(cwd, str) else ""


def hand_over(argv: list[str], cwd: str, name: str | None = None) -> bool:
    """Give the arguments to a running instance. True if one took them."""
    socket = QLocalSocket()
    socket.connectToServer(name or server_name())
    if not socket.waitForConnected(CONNECT_MS):
        return False
    socket.write(encode(argv, cwd))
    socket.flush()
    socket.waitForBytesWritten(CONNECT_MS)
    socket.disconnectFromServer()
    return True


class Listener(QObject):
    """The first instance's end. Emits `received(argv, cwd)` per hand-over."""

    received = Signal(list, str)

    def __init__(self, name: str | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._name = name or server_name()
        self._server = QLocalServer(self)
        self._server.newConnection.connect(self._accept)
        self._buffers: dict[QLocalSocket, bytes] = {}
        self._sockets: set[QLocalSocket] = set()

    def listen(self) -> bool:
        if self._server.listen(self._name):
            return True
        # A server left behind by an instance that crashed holds the name on
        # some platforms. Nothing answered `hand_over`, so it is dead.
        QLocalServer.removeServer(self._name)
        return self._server.listen(self._name)

    def close(self) -> None:
        """Stop listening and let go of every connection, signals first.

        A socket still connected when the server is destroyed emits
        `disconnected` from inside its own destructor, and a handler that runs
        then is handling an object that is half gone. So the handlers are
        detached before anything is closed.
        """
        for socket in list(self._sockets):
            self._detach(socket)
            socket.abort()
            socket.deleteLater()
        self._sockets.clear()
        self._buffers.clear()
        self._server.close()

    def _detach(self, socket: QLocalSocket) -> None:
        for signal in (socket.readyRead, socket.disconnected):
            try:
                signal.disconnect()
            except (RuntimeError, TypeError):
                pass

    def _accept(self) -> None:
        while self._server.hasPendingConnections():
            socket = self._server.nextPendingConnection()
            self._buffers[socket] = b""
            self._sockets.add(socket)
            socket.readyRead.connect(lambda s=socket: self._read(s))
            socket.disconnected.connect(lambda s=socket: self._closed(s))

    def _read(self, socket: QLocalSocket) -> None:
        if socket not in self._buffers:
            return
        self._buffers[socket] += bytes(socket.readAll())
        if self._buffers[socket].endswith(b"\n"):
            self._deliver(socket)

    def _closed(self, socket: QLocalSocket) -> None:
        """The one place a socket is let go of. Deleting it from `_read` as
        well scheduled it twice, and the second arrived at a socket that was
        already being destroyed -- a crash inside the next event loop, which
        in the tests was somebody else's."""
        if socket in self._buffers:
            self._deliver(socket)
        self._detach(socket)
        self._sockets.discard(socket)
        socket.deleteLater()

    def _deliver(self, socket: QLocalSocket) -> None:
        data = self._buffers.pop(socket, b"")
        message = decode(data) if data else None
        if message is not None:
            self.received.emit(*message)
