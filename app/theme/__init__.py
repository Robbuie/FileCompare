"""The design system, ported from File Manager, which ported it from Redline PDF.

Three independent axes -- theme, accent, density -- kept independent on
purpose. `tokens.py` and `qss.py` are File Manager's files unchanged, so a grey
that changes there can be carried over by copying the file. What compare adds
lives beside them rather than inside them: `diff.py` for the difference
colours, `sheet.py` for this application's stylesheet.

**No literal colour belongs anywhere outside this package.** `tests/test_look.py`
fails the build on one.
"""

from app.theme.tokens import ACCENTS, DENSITIES, DEFAULTS, THEMES  # noqa: F401
