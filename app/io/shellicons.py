"""Windows' own icon for a kind of file, asked for by kind and never by path.

File Manager's listing draws the real shell icons, and the folder compare is
meant to read as the same family, so it draws them too (1.12). The rule is
File Manager's, from its CLAUDE.md: an icon is asked for by kind -- an
extension, a folder, a file without an extension -- with
SHGFI_USEFILEATTRIBUTES, which makes the shell answer from the association
database alone and never go near a path. A folder of 50,000 files on a dead
share costs one lookup per distinct extension and touches nothing on it.

File Manager does this with pywin32. Here it is ctypes, because a dependency
ships inside the installer and four calls do not justify one. Every handle
crosses as a pointer-sized integer with its types declared, since a 64-bit
handle passed as a default `int` is truncated quietly and GDI leaks without
complaint.

The pixels are drawn twice, once over black and once over white, and the
alpha is the difference. That is what makes old mask-only icons come out with
transparent corners as well as 32-bit ones, without branching on which kind
the shell handed back.

Nothing here is Qt. It runs on the icon thread in `ui/fileicons.py`, and off
Windows it answers None for everything, which leaves the drawn fallbacks.
"""

from __future__ import annotations

import sys

FOLDER = ":folder"
FILE = ":file"

_SEPARATORS = ("\\", "/", ":")


def key_for(name: str, is_dir: bool) -> str:
    """The kind a row draws: an extension with its dot, or one of two names."""
    if is_dir:
        return FOLDER
    dot = name.rfind(".")
    if dot <= 0 or dot == len(name) - 1:
        return FILE
    ext = name[dot:].lower()
    if any(ch in ext for ch in _SEPARATORS) or len(ext) > 16:
        return FILE
    return ext


def alpha_from(black: bytes, white: bytes) -> bytes:
    """Premultiplied BGRA from the same icon drawn over black and over white.

    Over black a pixel is its colour times its alpha, which is exactly the
    premultiplied value; over white it is that plus (1 - alpha) * 255. So the
    alpha is 255 minus the difference, taken from the green channel, which no
    icon format stores at lower precision than the others.
    """
    out = bytearray(len(black))
    for i in range(0, len(black), 4):
        a = 255 - (white[i + 1] - black[i + 1])
        a = 0 if a < 0 else 255 if a > 255 else a
        out[i] = min(black[i], a)
        out[i + 1] = min(black[i + 1], a)
        out[i + 2] = min(black[i + 2], a)
        out[i + 3] = a
    return bytes(out)


def pixels(key: str, size: int) -> bytes | None:
    """`size` by `size` premultiplied BGRA, top row first, or None."""
    if sys.platform != "win32":
        return None
    try:
        return _win_pixels(key, size)
    except Exception:  # noqa: BLE001 - a missing association is not an error
        return None


_api = None


def _load():
    global _api
    if _api is not None:
        return _api
    import ctypes
    from ctypes import wintypes

    class SHFILEINFOW(ctypes.Structure):
        _fields_ = [("hIcon", ctypes.c_void_p), ("iIcon", ctypes.c_int),
                    ("dwAttributes", wintypes.DWORD),
                    ("szDisplayName", ctypes.c_wchar * 260),
                    ("szTypeName", ctypes.c_wchar * 80)]

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
                    ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                    ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                    ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                    ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                    ("biClrImportant", wintypes.DWORD)]

    shell32 = ctypes.WinDLL("shell32")
    user32 = ctypes.WinDLL("user32")
    gdi32 = ctypes.WinDLL("gdi32")
    ole32 = ctypes.WinDLL("ole32")
    vp = ctypes.c_void_p

    shell32.SHGetFileInfoW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD,
                                       ctypes.POINTER(SHFILEINFOW), wintypes.UINT, wintypes.UINT]
    shell32.SHGetFileInfoW.restype = ctypes.c_size_t
    user32.DrawIconEx.argtypes = [vp, ctypes.c_int, ctypes.c_int, vp, ctypes.c_int,
                                  ctypes.c_int, wintypes.UINT, vp, wintypes.UINT]
    user32.DrawIconEx.restype = wintypes.BOOL
    user32.DestroyIcon.argtypes = [vp]
    user32.DestroyIcon.restype = wintypes.BOOL
    gdi32.CreateCompatibleDC.argtypes = [vp]
    gdi32.CreateCompatibleDC.restype = vp
    gdi32.CreateDIBSection.argtypes = [vp, ctypes.POINTER(BITMAPINFOHEADER), wintypes.UINT,
                                       ctypes.POINTER(vp), vp, wintypes.DWORD]
    gdi32.CreateDIBSection.restype = vp
    gdi32.SelectObject.argtypes = [vp, vp]
    gdi32.SelectObject.restype = vp
    gdi32.DeleteObject.argtypes = [vp]
    gdi32.DeleteObject.restype = wintypes.BOOL
    gdi32.DeleteDC.argtypes = [vp]
    gdi32.DeleteDC.restype = wintypes.BOOL
    gdi32.GdiFlush.argtypes = []
    gdi32.GdiFlush.restype = wintypes.BOOL
    ole32.CoInitializeEx.argtypes = [vp, wintypes.DWORD]
    ole32.CoInitializeEx.restype = ctypes.c_long

    _api = (ctypes, SHFILEINFOW, BITMAPINFOHEADER, shell32, user32, gdi32, ole32)
    return _api


_com_ready = False


def _win_pixels(key: str, size: int) -> bytes | None:
    global _com_ready
    ctypes, SHFILEINFOW, BITMAPINFOHEADER, shell32, user32, gdi32, ole32 = _load()
    if not _com_ready:
        # The shell wants COM on the calling thread; this module is only ever
        # called from the one icon thread, so once is enough. S_FALSE (already
        # initialised) is as good as S_OK.
        ole32.CoInitializeEx(None, 0x2)
        _com_ready = True

    if key == FOLDER:
        name, attributes = "folder", 0x10        # FILE_ATTRIBUTE_DIRECTORY
    elif key == FILE:
        name, attributes = "file", 0x80          # FILE_ATTRIBUTE_NORMAL
    elif key.startswith(".") and not any(ch in key for ch in _SEPARATORS):
        name, attributes = "file" + key, 0x80
    else:
        return None

    info = SHFILEINFOW()
    flags = 0x100 | 0x10                         # SHGFI_ICON | SHGFI_USEFILEATTRIBUTES
    flags |= 0x0 if size > 16 else 0x1           # SHGFI_LARGEICON : SHGFI_SMALLICON
    if not shell32.SHGetFileInfoW(name, attributes, ctypes.byref(info),
                                  ctypes.sizeof(info), flags) or not info.hIcon:
        return None
    try:
        black = _draw(info.hIcon, size, 0x00)
        white = _draw(info.hIcon, size, 0xFF)
    finally:
        user32.DestroyIcon(info.hIcon)
    if black is None or white is None:
        return None
    return alpha_from(black, white)


def _draw(icon, size: int, fill: int) -> bytes | None:
    ctypes, _info, BITMAPINFOHEADER, _shell, user32, gdi32, _ole = _load()
    header = BITMAPINFOHEADER()
    header.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    header.biWidth = size
    header.biHeight = -size                      # top row first
    header.biPlanes = 1
    header.biBitCount = 32
    bits = ctypes.c_void_p()
    dc = gdi32.CreateCompatibleDC(None)
    if not dc:
        return None
    bitmap = gdi32.CreateDIBSection(dc, ctypes.byref(header), 0, ctypes.byref(bits), None, 0)
    if not bitmap or not bits.value:
        gdi32.DeleteDC(dc)
        return None
    old = gdi32.SelectObject(dc, bitmap)
    try:
        ctypes.memset(bits.value, fill, size * size * 4)
        user32.DrawIconEx(dc, 0, 0, icon, size, size, 0, None, 0x3)   # DI_NORMAL
        gdi32.GdiFlush()
        return ctypes.string_at(bits.value, size * size * 4)
    finally:
        gdi32.SelectObject(dc, old)
        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(dc)
