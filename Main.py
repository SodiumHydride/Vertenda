# -*- coding: utf-8 -*-
"""Application entrypoint.

Responsibility: Qt bootstrapping + Windows subprocess window suppression.
All business logic lives in the `converter` package.
"""

from __future__ import annotations

import os
import subprocess
import sys


# Silence Qt's cross-platform font-alias warnings. The QSS stack lists fonts
# from every OS (Helvetica Neue / Segoe UI / PingFang SC / ...), which makes
# Qt warn about the absent ones on each platform even though fallback works.
os.environ.setdefault("QT_LOGGING_RULES", "qt.qpa.fonts.debug=false;qt.qpa.fonts.warning=false")


# On Windows, hide console windows from spawned ffmpeg subprocesses globally.
# Doing this in the entry module ensures the monkey-patch is in effect before
# any worker thread calls subprocess.Popen.
if sys.platform == "win32":
    _CREATE_NO_WINDOW = 0x08000000
    _original_popen = subprocess.Popen

    def _popen_no_window(*args, **kwargs):  # type: ignore[no-untyped-def]
        flags = kwargs.get("creationflags", 0)
        kwargs["creationflags"] = flags | _CREATE_NO_WINDOW
        return _original_popen(*args, **kwargs)

    subprocess.Popen = _popen_no_window  # type: ignore[assignment]


from PyQt5.QtWidgets import QApplication, QDialog  # noqa: E402

from converter import constants  # noqa: E402
from converter.ffmpeg.probe import check_ffmpeg_available  # noqa: E402
from converter.ui.main_window import ConverterMainWindow  # noqa: E402


def _ensure_ffmpeg(app: QApplication) -> bool:
    """Make sure a runnable ffmpeg+ffprobe exist. Show the first-run dialog if not."""
    if check_ffmpeg_available():
        return True

    # Imported lazily so the helper module does not import Qt at test time.
    from converter.ui.first_run_dialog import FirstRunDialog

    dlg = FirstRunDialog()
    dlg.exec_()
    if not dlg.succeeded:
        return False

    constants.FFMPEG_PATH, constants.FFPROBE_PATH = constants.resolve_ffmpeg_paths()
    return check_ffmpeg_available()


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Convert")
    app.setOrganizationName("Kurisu")

    if not _ensure_ffmpeg(app):
        return 1

    window = ConverterMainWindow()
    window.show()
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
