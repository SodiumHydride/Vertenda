# -*- coding: utf-8 -*-
"""Application entrypoint.

Responsibility: decide between GUI and CLI mode, set up Qt if GUI.
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


# macOS LaunchServices appends -psn_X_Y to argv when a .app is launched from
# Finder. Strip those so argparse doesn't choke.
def _clean_argv(argv: list[str]) -> list[str]:
    return [a for a in argv if not a.startswith("-psn_")]


def _should_use_cli(argv: list[str]) -> bool:
    """CLI mode: any command-line arg given (except explicit --gui)."""
    if not argv:
        return False
    if "--gui" in argv:
        return False
    return True


def _run_cli(argv: list[str]) -> int:
    # Import lazily so a `convert install-ffmpeg` invocation from a headless
    # shell doesn't drag in Qt dependencies.
    from converter.cli import main as cli_main
    return cli_main(argv)


def _run_gui() -> int:
    from PyQt5.QtCore import QSettings
    from PyQt5.QtWidgets import QApplication

    from converter import constants
    from converter.constants import SettingsKey, app_runtime_dir
    from converter.ffmpeg.installer import set_data_dir_override
    from converter.ffmpeg.probe import check_ffmpeg_available
    from converter.ui.main_window import ConverterMainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("Vertenda")
    app.setOrganizationName("Kurisu")

    # Load custom data directory BEFORE we resolve ffmpeg paths.
    config_path = os.path.join(app_runtime_dir(), "converter_config.ini")
    settings = QSettings(config_path, QSettings.IniFormat)
    settings.setFallbacksEnabled(False)
    override = settings.value(SettingsKey.CUSTOM_DATA_DIR, "", type=str).strip()
    if override and os.path.isdir(override):
        set_data_dir_override(override)
    else:
        set_data_dir_override(None)
    constants.FFMPEG_PATH, constants.FFPROBE_PATH = constants.resolve_ffmpeg_paths()

    if not check_ffmpeg_available():
        # Apply the theme first so the first-run dialog looks like part of the app.
        from converter.ui.first_run_dialog import FirstRunDialog
        from converter.ui.theme import build_stylesheet
        theme = settings.value(SettingsKey.THEME_MODE, "Dark", type=str)
        app.setStyleSheet(build_stylesheet(theme))

        dlg = FirstRunDialog(settings=settings)
        dlg.exec_()
        if not dlg.succeeded:
            return 1
        constants.FFMPEG_PATH, constants.FFPROBE_PATH = constants.resolve_ffmpeg_paths()
        if not check_ffmpeg_available():
            return 1

    window = ConverterMainWindow()
    window.show()
    return app.exec_()


def main() -> int:
    argv = _clean_argv(sys.argv[1:])
    if _should_use_cli(argv):
        return _run_cli(argv)
    return _run_gui()


if __name__ == "__main__":
    sys.exit(main())
