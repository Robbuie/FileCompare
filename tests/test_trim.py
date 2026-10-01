"""Checks on what the installer leaves out.

Ported from File Manager (tests/test_trim.py) with the pywin32 cases removed:
File Compare does not use pywin32.

`packaging/trim.py` decides which collected files never reach the build, and
getting it wrong does not fail the build -- it produces one that works on the
machine it was made on and fails somewhere specific much later. An image plugin
dropped by mistake is a folder of drawings that quietly stops previewing, which
is the same failure mode the spec's own note about Pillow describes.

So the two halves are tested from opposite directions. One says the entries
meant to go are gone. The other pins the things that were considered and kept,
with the feature each one is there for -- because those are what a later pass
over the same list, reading only the module exclusions, would remove again.

No PyInstaller and no Windows: this is string comparison, which is where the
mistake would be.
"""

from __future__ import annotations

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "packaging"))

import trim  # noqa: E402


@pytest.mark.parametrize("destination", [
    "PySide6/opengl32sw.dll",
    "PySide6/Qt6Quick.dll",
    "PySide6/Qt6Qml.dll",
    "PySide6/Qt6QmlModels.dll",
    "PySide6/Qt6VirtualKeyboard.dll",
    "PySide6/plugins/platforminputcontexts/qtvirtualkeyboardplugin.dll",
    "PySide6/Qt6OpenGL.dll",
    "PySide6/plugins/tls/qopensslbackend.dll",
    "PySide6/plugins/tls/qschannelbackend.dll",
    "PySide6/plugins/networkinformation/qnetworklistmanager.dll",
    "PySide6/plugins/generic/qtuiotouchplugin.dll",
    "PySide6/translations/qt_de.qm",
    "PySide6/translations/qtbase_fr.qm",
])
def test_what_the_application_never_loads_is_dropped(destination):
    assert not trim.keep(destination)


@pytest.mark.parametrize("destination, why", [
    # `.pdf` is in PREVIEW_IMAGE_KINDS and protocol.py says so deliberately:
    # Qt's PDF plugin registers as an image format, so page one of a drawing
    # set previews like a photograph. `PySide6.QtPdf` is excluded as a module
    # and the plugin is what does the work -- which is why reading the spec's
    # exclusion list and stopping there gets this one wrong.
    ("PySide6/Qt6Pdf.dll", "pdf previews"),
    ("PySide6/plugins/imageformats/qpdf.dll", "pdf previews"),
    # `.svg` and `.svgz` are previewable kinds. `ui/glyphs.py` saying it needs
    # no QtSvg is about the chrome, not about what the previewer reads.
    ("PySide6/Qt6Svg.dll", "svg previews"),
    ("PySide6/plugins/imageformats/qsvg.dll", "svg previews"),
    ("PySide6/plugins/iconengines/qsvgicon.dll", "svg previews"),
    # Python's own OpenSSL, at the root of _internal rather than in PySide6/,
    # beside _ssl.pyd and _hashlib.pyd. The update check's HTTPS and its
    # SHA-256 verification both run on it.
    ("libcrypto-3.dll", "the update check"),
    ("libssl-3.dll", "the update check"),
    ("_ssl.pyd", "the update check"),
    ("_hashlib.pyd", "the update check"),
    # The rest of the image formats, and the platform plugin the window needs.
    ("PySide6/plugins/imageformats/qjpeg.dll", "jpeg previews"),
    ("PySide6/plugins/imageformats/qwebp.dll", "webp previews"),
    ("PySide6/plugins/imageformats/qtiff.dll", "tiff previews"),
    ("PySide6/plugins/imageformats/qico.dll", "ico previews"),
    ("PySide6/plugins/platforms/qwindows.dll", "the window existing at all"),
    ("PySide6/plugins/styles/qmodernwindowsstyle.dll", "the native style"),
    ("PySide6/Qt6Core.dll", "everything"),
    ("PySide6/Qt6Gui.dll", "everything"),
    ("PySide6/Qt6Widgets.dll", "everything"),
])
def test_what_a_feature_depends_on_is_kept(destination, why):
    assert trim.keep(destination), f"dropping this would break {why}"


@pytest.mark.parametrize("destination", [
    "PySide6\\Qt6Quick.dll",
    "pyside6/qt6quick.dll",
    "PYSIDE6/QT6QUICK.DLL",
    "./PySide6/Qt6Quick.dll",
])
def test_the_spelling_of_a_collected_path_does_not_decide_it(destination):
    """PyInstaller writes the building platform's separator, and the case of a
    DLL name is whatever the wheel shipped. Neither should change the answer.
    """
    assert not trim.keep(destination)


def test_apply_drops_the_entries_and_says_how_many():
    """The count is what the build prints. A spec that silently shipped what it
    meant to drop -- a renamed file, a hook collecting by another route --
    would look exactly like one that worked.
    """
    class FakeAnalysis:
        binaries = [
            ("PySide6/Qt6Core.dll", "/src/Qt6Core.dll", "BINARY"),
            ("PySide6/Qt6Quick.dll", "/src/Qt6Quick.dll", "BINARY"),
            ("PySide6/opengl32sw.dll", "/src/opengl32sw.dll", "BINARY"),
        ]
        datas = [
            ("PySide6/translations/qt_de.qm", "/src/qt_de.qm", "DATA"),
            ("assets/icon.png", "/src/icon.png", "DATA"),
        ]

    analysis = FakeAnalysis()
    report = trim.apply(analysis)

    assert dict(report) == {"binaries": 2, "datas": 1}
    assert [entry[0] for entry in analysis.binaries] == ["PySide6/Qt6Core.dll"]
    assert [entry[0] for entry in analysis.datas] == ["assets/icon.png"]


def test_the_list_refuses_rather_than_allows():
    """Something PySide6 starts shipping tomorrow is kept, not dropped.

    An allow-list would break every time a file was renamed, and it would
    break by leaving something out -- the failure that does not announce
    itself until somebody opens the feature that needed it.
    """
    assert trim.keep("PySide6/Qt6SomethingNew.dll")
    assert trim.keep("PySide6/plugins/imageformats/qbrandnew.dll")


def test_the_pdf_plugin_keeps_the_network_library_it_links_to():
    # 1.4.2: the link check refused the 1.4.1 build because Qt6Pdf.dll needs
    # Qt6Network.dll. The binding goes; the library stays.
    assert trim.keep("PySide6/Qt6Network.dll")
    assert trim.keep("PySide6/Qt6Pdf.dll")
    assert trim.keep("PySide6/QtNetwork.pyd")     # 1.4.3: QLocalServer
    assert not trim.keep("PySide6/Qt6QmlMeta.dll")
    assert not trim.keep("PySide6/Qt6QmlWorkerScript.dll")


def test_every_qt_module_the_application_imports_is_shipped():
    # 1.4.3: the first installer ever built died on start because the trim
    # list, copied from File Manager, dropped QtNetwork -- which this
    # application uses for its single window. Every PySide6 module imported
    # anywhere under app/ must survive both the spec's exclusions and the trim.
    import pathlib
    import re

    root = pathlib.Path(__file__).resolve().parent.parent
    used = set()
    for path in (root / "app").rglob("*.py"):
        used |= set(re.findall(r"PySide6\.(Qt\w+)", path.read_text(encoding="utf-8")))
    assert {"QtCore", "QtGui", "QtWidgets", "QtNetwork"} <= used
    spec = (root / "packaging" / "filecompare.spec").read_text(encoding="utf-8")
    for module in sorted(used):
        assert f'"PySide6.{module}"' not in spec, f"the spec excludes {module}"
        assert trim.keep(f"PySide6/{module}.pyd"), f"trim drops {module}"
        assert trim.keep(f"PySide6/Qt6{module[2:]}.dll"), f"trim drops Qt6{module[2:]}"
