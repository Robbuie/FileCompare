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

    from PySide6.QtCore import QCoreApplication, Qt
    from PySide6.QtWidgets import QApplication

    from app import __version__, cli
    from app.core import appearance, instance
    from app.core.config import Config
    from app.ui.window import MainWindow

    QCoreApplication.setAttribute(Qt.AA_ShareOpenGLContexts, True)
    app = QApplication.instance() or QApplication([sys.argv[0]])
    app.setApplicationName("File Compare")
    app.setApplicationVersion(__version__)

    if instance.hand_over(argv, cwd):
        return 0

    config = Config.load()
    look, source = appearance.resolve(config)
    window = MainWindow(config, look=look, look_source=source)

    listener = instance.Listener()
    listener.received.connect(
        lambda args, where: (window.open_request(cli.parse(args, where)), window.bring_forward()))
    listener.listen()

    window.open_request(cli.parse(argv, cwd))
    if config.get("window.maximized"):
        window.showMaximized()
    else:
        window.show()
    code = app.exec()
    listener.close()
    return code


if __name__ == "__main__":
    sys.exit(main())
