"""The frozen entry point. It exists for one line.

Ported from File Manager 0.40.0. Since 1.4 File Compare reads files and
walks folders on a share in worker processes (`app/io/pool.py`), started with
multiprocessing's spawn context, which re-launches this executable and
imports its way back to the child function. In a PyInstaller build there is no `-m` and
no script to import: without `freeze_support()` the child re-runs the entry
point instead, and every worker would open another File Compare window, which opens
more workers. Called first, it recognises a spawned child, runs the child, and
exits.

It has to be the first thing that happens, before Qt is imported and before
anything reads a setting, so this file stays four lines long and the
application proper stays in `app/__main__.py`.
"""

import multiprocessing
import sys

if __name__ == "__main__":
    multiprocessing.freeze_support()
    from app.__main__ import main
    sys.exit(main())
