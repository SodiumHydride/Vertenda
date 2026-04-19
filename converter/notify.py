# -*- coding: utf-8 -*-
"""Cross-platform desktop notifications (best-effort, silent degradation)."""

from __future__ import annotations

import subprocess
import sys


def send_notification(title: str, body: str) -> None:
    """Fire a native desktop notification.  Never raises."""
    try:
        if sys.platform == "darwin":
            _notify_macos(title, body)
        elif sys.platform == "win32":
            _notify_windows(title, body)
        else:
            _notify_linux(title, body)
    except Exception:
        pass


def _notify_macos(title: str, body: str) -> None:
    script = (
        f'display notification "{_escape_applescript(body)}" '
        f'with title "{_escape_applescript(title)}"'
    )
    subprocess.Popen(
        ["osascript", "-e", script],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def _escape_applescript(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def _notify_windows(title: str, body: str) -> None:
    try:
        from winotify import Notification
        toast = Notification(
            app_id="盐酸转换器",
            title=title,
            msg=body,
        )
        toast.show()
    except ImportError:
        pass


def _notify_linux(title: str, body: str) -> None:
    subprocess.Popen(
        ["notify-send", title, body],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
