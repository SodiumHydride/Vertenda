# -*- coding: utf-8 -*-
"""Self-contained ffmpeg downloader.

Stores the binaries in the OS-standard per-user data directory so a clean
uninstall = remove that directory. We never touch the system PATH.

  macOS:   ~/Library/Application Support/Vertenda/ffmpeg/
  Windows: %LOCALAPPDATA%\\Vertenda\\ffmpeg\\
  Linux:   ~/.local/share/Vertenda/ffmpeg/   (best-effort; distros vary)

Download sources (all current as of 2024+):
  macOS   : evermeet.cx (static, includes libass)
  Windows : gyan.dev    (release-essentials build, includes libass)
  Linux   : johnvansickle.com (amd64/arm64 static)
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import threading
import urllib.request
import urllib.error
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


APP_FOLDER_NAME = "Vertenda"
# The marker filename is kept as the historic "convert" identifier: it is an
# internal-only file used to decide "was this cache installed by us?" and
# changing it would orphan existing caches on upgrade. Not a branding surface.
INSTALL_MARKER_NAME = ".installed_by_convert.json"


# User-selectable override. When set, ffmpeg is cached under <override>/Vertenda/
# rather than the platform default. Managed via `set_data_dir_override` + reads
# from QSettings upstream (kept out of this module to avoid a Qt dependency).
_data_dir_override: Path | None = None


def set_data_dir_override(path: str | Path | None) -> None:
    """Opt-in user-chosen parent for the app data directory.

    Pass `None` or an empty string to revert to the platform default.
    The override should be an existing writable directory; we create our
    own ``Vertenda/`` subdir inside it.
    """
    global _data_dir_override
    if not path:
        _data_dir_override = None
        return
    _data_dir_override = Path(path).expanduser().resolve()


def get_data_dir_override() -> Path | None:
    return _data_dir_override


def _default_app_data_dir() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_FOLDER_NAME
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / APP_FOLDER_NAME
    xdg = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg) if xdg else (Path.home() / ".local" / "share")
    return base / APP_FOLDER_NAME


def app_data_dir() -> Path:
    """Per-user writable data directory for the app.

    Respects :func:`set_data_dir_override` when set, otherwise falls back to
    the platform-default location.
    """
    if _data_dir_override is not None:
        return _data_dir_override / APP_FOLDER_NAME
    return _default_app_data_dir()


def ffmpeg_cache_dir() -> Path:
    """Directory where we keep auto-downloaded ffmpeg/ffprobe."""
    return app_data_dir() / "ffmpeg"


def cached_binary_paths() -> tuple[Path, Path]:
    """Return (ffmpeg, ffprobe) paths inside our cache dir, regardless of existence."""
    d = ffmpeg_cache_dir()
    if sys.platform == "win32":
        return d / "ffmpeg.exe", d / "ffprobe.exe"
    return d / "ffmpeg", d / "ffprobe"


def install_marker_path() -> Path:
    return ffmpeg_cache_dir() / INSTALL_MARKER_NAME


def has_cached_binaries() -> bool:
    ff, fp = cached_binary_paths()
    return ff.is_file() and fp.is_file() and _probe(ff) and _probe(fp)


def installed_by_us() -> bool:
    """Return True when the cached binaries were placed there by our installer.

    Used by the uninstall flow: we only offer to delete ffmpeg when we're
    confident the user didn't point us at their own brew/system install.
    """
    return install_marker_path().is_file() and has_cached_binaries()


def _probe(path: Path, *, timeout: float = 4.0) -> bool:
    try:
        cp = subprocess.run(
            [str(path), "-version"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=timeout,
        )
        return cp.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _warmup_probe(path: Path) -> bool:
    """Longer-timeout probe for first-time-on-disk binaries.

    On Apple Silicon, a freshly-downloaded x86_64 ffmpeg triggers Rosetta 2
    translation on its first execve; that one-off cost can be 10+ seconds.
    macOS Gatekeeper also does a synchronous virus scan on unfamiliar
    executables. Give both of them generous headroom.
    """
    return _probe(path, timeout=30.0)


# ---- Download plan per platform ---------------------------------------------

@dataclass
class DownloadAsset:
    url: str
    # Names inside the archive we want to extract. Matched by basename.
    wanted_basenames: tuple[str, ...]
    archive_kind: str  # "zip" | "tar.xz" | "tar.gz"


def _plan_for_platform() -> list[DownloadAsset]:
    if sys.platform == "darwin":
        return [
            DownloadAsset(
                url="https://evermeet.cx/ffmpeg/getrelease/zip",
                wanted_basenames=("ffmpeg",),
                archive_kind="zip",
            ),
            DownloadAsset(
                url="https://evermeet.cx/ffmpeg/getrelease/ffprobe/zip",
                wanted_basenames=("ffprobe",),
                archive_kind="zip",
            ),
        ]
    if sys.platform == "win32":
        return [DownloadAsset(
            url="https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip",
            wanted_basenames=("ffmpeg.exe", "ffprobe.exe"),
            archive_kind="zip",
        )]
    # Linux: John Van Sickle's static builds (amd64/arm64 depending on host).
    import platform
    arch = platform.machine().lower()
    if arch in ("aarch64", "arm64"):
        url = "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-arm64-static.tar.xz"
    else:
        url = "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz"
    return [DownloadAsset(
        url=url,
        wanted_basenames=("ffmpeg", "ffprobe"),
        archive_kind="tar.xz",
    )]


# ---- Download & extract -----------------------------------------------------

ProgressCallback = Callable[[int, int], None]  # (bytes_read, total_bytes)
StatusCallback = Callable[[str], None]         # human-readable stage label


def _download(url: str, dest: Path, on_progress: ProgressCallback | None = None,
              chunk_size: int = 64 * 1024, cancel_flag: threading.Event | None = None) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "Vertenda/2.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        total = int(resp.headers.get("Content-Length") or 0)
        read = 0
        with open(dest, "wb") as f:
            while True:
                if cancel_flag is not None and cancel_flag.is_set():
                    raise RuntimeError("cancelled")
                chunk = resp.read(chunk_size)
                if not chunk:
                    break
                f.write(chunk)
                read += len(chunk)
                if on_progress is not None:
                    on_progress(read, total)


def _extract(archive: Path, kind: str, wanted: tuple[str, ...], dest_dir: Path) -> list[Path]:
    """Pull files whose basename matches `wanted` out of the archive."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    extracted: list[Path] = []

    def _safe_write(in_path: str, stream) -> None:
        base = os.path.basename(in_path)
        if base not in wanted:
            return
        out = dest_dir / base
        with open(out, "wb") as f:
            shutil.copyfileobj(stream, f)
        _make_executable(out)
        extracted.append(out)

    if kind == "zip":
        with zipfile.ZipFile(archive) as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                base = os.path.basename(info.filename)
                if base not in wanted:
                    continue
                with zf.open(info) as stream:
                    _safe_write(info.filename, stream)
    elif kind in ("tar.xz", "tar.gz"):
        mode = "r:xz" if kind == "tar.xz" else "r:gz"
        with tarfile.open(archive, mode=mode) as tf:
            for member in tf.getmembers():
                if not member.isfile():
                    continue
                base = os.path.basename(member.name)
                if base not in wanted:
                    continue
                stream = tf.extractfile(member)
                if stream is None:
                    continue
                _safe_write(member.name, stream)
    else:
        raise ValueError(f"Unsupported archive kind: {kind}")

    return extracted


def _make_executable(path: Path) -> None:
    if sys.platform == "win32":
        return
    st = path.stat()
    path.chmod(st.st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    if sys.platform == "darwin":
        _strip_quarantine(path)


def _strip_quarantine(path: Path) -> None:
    """Remove macOS Gatekeeper quarantine / provenance attributes.

    Without this, the first exec of a freshly-downloaded binary is blocked by
    the OS with a cryptic permissions error, even though the file has +x.
    Safe to silently ignore failures - the user can still allow the binary
    manually if needed.
    """
    try:
        subprocess.run(
            ["xattr", "-cr", str(path)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        pass


# ---- Public API -------------------------------------------------------------

class InstallError(RuntimeError):
    pass


def install_bundle(on_progress: ProgressCallback | None = None,
                    on_status: StatusCallback | None = None,
                    cancel_flag: threading.Event | None = None) -> tuple[Path, Path]:
    """Download+extract ffmpeg & ffprobe into the cache dir.

    Returns (ffmpeg_path, ffprobe_path). Raises InstallError on failure.
    """
    def _status(msg: str) -> None:
        if on_status is not None:
            on_status(msg)

    plan = _plan_for_platform()
    dest_dir = ffmpeg_cache_dir()
    dest_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        for i, asset in enumerate(plan, start=1):
            if cancel_flag is not None and cancel_flag.is_set():
                raise InstallError("已取消")

            archive = tmp_path / f"asset_{i}"
            _status(f"正在下载 ({i}/{len(plan)})…")

            def scaled_progress(read: int, total: int, _i=i, _n=len(plan)):
                if on_progress is None:
                    return
                per_asset = (read / total) if total > 0 else 0.0
                overall = ((_i - 1) + per_asset) / _n
                on_progress(int(overall * 1000), 1000)  # permille for smoother UI

            try:
                _download(asset.url, archive, scaled_progress, cancel_flag=cancel_flag)
            except urllib.error.URLError as exc:
                raise InstallError(f"下载失败: {exc.reason}") from exc
            except RuntimeError as exc:
                raise InstallError(str(exc)) from exc

            _status(f"正在解压 ({i}/{len(plan)})…")
            try:
                pulled = _extract(archive, asset.archive_kind,
                                   asset.wanted_basenames, dest_dir)
            except (zipfile.BadZipFile, tarfile.TarError) as exc:
                raise InstallError(f"压缩包损坏: {exc}") from exc
            if not pulled:
                raise InstallError(
                    f"压缩包里没找到 {asset.wanted_basenames}，"
                    "可能下载源结构变了，请手动下载 ffmpeg 后重试。"
                )

        if on_progress is not None:
            on_progress(1000, 1000)

    ff, fp = cached_binary_paths()
    if not ff.is_file() or not fp.is_file():
        missing = [p for p in (ff, fp) if not p.is_file()]
        raise InstallError(f"缺少文件: {missing}")

    _status("正在验证可执行性（首次启动 Rosetta 翻译可能需要 10-20 秒）…")
    if not _warmup_probe(ff) or not _warmup_probe(fp):
        raise InstallError(
            "二进制文件无法运行（可能架构不匹配或被系统安全策略拦截）。\n"
            "如果你在 Apple Silicon 机器上，请先安装 Rosetta 2：\n"
            "  softwareupdate --install-rosetta --agree-to-license"
        )

    _write_marker(plan, ff, fp)
    _status("✓ 安装完成")
    return ff, fp


def _write_marker(plan: list[DownloadAsset], ff: Path, fp: Path) -> None:
    """Record that we own this copy so the uninstaller can safely delete it."""
    try:
        from converter import __version__ as app_version
    except Exception:
        app_version = "unknown"

    def _head_line(path: Path) -> str:
        try:
            cp = subprocess.run(
                [str(path), "-version"],
                capture_output=True, text=True, timeout=10,
            )
            return (cp.stdout.splitlines() or [""])[0].strip()
        except (OSError, subprocess.SubprocessError):
            return ""

    data = {
        "schema": 1,
        "installed_at": _dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "app_version": app_version,
        "sources": [a.url for a in plan],
        "ffmpeg_version": _head_line(ff),
        "ffprobe_version": _head_line(fp),
        "platform": sys.platform,
    }
    try:
        install_marker_path().write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError:
        pass  # Marker is nice-to-have; don't fail install on write error.


def read_marker() -> dict | None:
    """Parse the marker file, or return None when missing/corrupt."""
    p = install_marker_path()
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def remove_cache() -> bool:
    """Wipe the ffmpeg cache directory. Returns True if anything was removed.

    Safe to call unconditionally: no-op if the directory doesn't exist.
    Note: this deletes everything under ``ffmpeg_cache_dir()`` whether or not
    the marker is present. For conservative cleanup, callers should check
    :func:`installed_by_us` first.
    """
    d = ffmpeg_cache_dir()
    if not d.exists():
        return False
    shutil.rmtree(d, ignore_errors=True)
    return True


def cache_size_bytes() -> int:
    """Total disk usage of the ffmpeg cache directory, 0 when absent."""
    d = ffmpeg_cache_dir()
    if not d.exists():
        return 0
    total = 0
    for root, _dirs, files in os.walk(d):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                continue
    return total
