"""File Compare -- a Windows side-by-side compare and merge tool.

Split three ways, like File Manager, and the boundaries are the design: `ui`
renders and takes input and never touches a file, `core` holds the state and
the diff engine, `io` does every read. See CLAUDE.md before adding to any of
them.
"""

__version__ = "0.7.0"
