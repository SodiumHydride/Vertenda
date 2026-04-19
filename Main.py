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


from PyQt5.QtWidgets import QApplication, QMessageBox  # noqa: E402

from converter.ffmpeg.probe import check_ffmpeg_available  # noqa: E402
from converter.ui.main_window import ConverterMainWindow  # noqa: E402


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Convert")
    app.setOrganizationName("Kurisu")

    if not check_ffmpeg_available():
        QMessageBox.critical(
            None, "FFmpeg 错误",
            "未找到可用的 FFmpeg 可执行文件。\n"
            "请确认 resources/ffmpeg 存在，或将 ffmpeg 添加到 PATH。",
        )
        return 1

    window = ConverterMainWindow()
    window.show()
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
