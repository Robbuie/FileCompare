"""Entry point: hand over to a running window, or become the window.

The order matters. The command line is parsed before Qt is asked for anything,
and a running instance is looked for before a window is built -- a second
start from File Manager should cost a socket connection and nothing else, not
a stylesheet render and a window that flashes and closes.
"""

from __future__ import annotations

import multiprocessing
import os
import sys


def main() -> int:
    multiprocessing.freeze_support()
    argv = sys.argv[1:]
    cwd = os.getcwd()

    from app import cli

    request = cli.parse(argv, cwd)
    if request.report:
        # 1.11: no window, no hand-over to one -- a report and an exit code.
        from app import batch
        from app.core.config import Config

        return batch.run(request, Config.load())

    from PySide6.QtCore import QCoreApplication, Qt
    from PySide6.QtWidgets import QApplication

    from app import __version__
    from app.core import appearance, instance
    from app.core.config import Config
    from app.ui.window import MainWindow

    QCoreApplication.setAttribute(Qt.AA_ShareOpenGLContexts, True)
    app = QApplication.instance() or QApplication([sys.argv[0]])
    app.setApplicationName("File Compare")
    app.setApplicationVersion(__version__)

    if not request.wait and instance.hand_over(argv, cwd):
        return 0

    config = Config.load()
    if request.select_left:
        # Explorer's "Select left side" with no window open: remember it and
        # go. A window that flashes up to say "noted" is worse than none.
        config.set("explorer.left", request.select_left)
        config.save()
        return 0

    look, source = appearance.resolve(config)
    window = MainWindow(config, look=look, look_source=source)

    listener = instance.Listener()
    if not request.wait:
        # A window started for git is git's: it does not take other launches'
        # tabs, which would keep git waiting on a window full of other work.
        listener.received.connect(
            lambda args, where: (window.open_request(cli.parse(args, where)),
                                 window.bring_forward()))
        listener.listen()

    window.open_request(request)
    if config.get("window.maximized"):
        window.showMaximized()
    else:
        window.show()
    code = app.exec()
    listener.close()
    # A downloaded, verified update runs once the window is gone, so the
    # installer is not waiting on files this process still holds.
    window.updates.install_staged()
    if request.merge:
        # What git's mergetool reads: 0 only when the merge was saved with
        # nothing left unresolved.
        return 0 if window.merge_ok else 1
    return code


if __name__ == "__main__":
    sys.exit(main())
