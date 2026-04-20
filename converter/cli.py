# -*- coding: utf-8 -*-
"""Command-line interface for Vertenda.

Two usage shapes, both routed through the same argparse:

  Simple (happy-path) form - auto-detects input kind:
    vertenda input.wav -f mp3
    vertenda input.mov -f mp4 --hw-accel --quality high
    vertenda input.srt -f lrc

  Explicit subcommands for multi-input or management tasks:
    vertenda burn video.mp4 subs.srt -o out.mp4 [--soft]
    vertenda merge audio.mp3 video.mp4 -o merged.mp4
    vertenda install-ffmpeg [--data-dir PATH]
    vertenda uninstall-ffmpeg
    vertenda where
    vertenda --gui

Design principle: the GUI and the CLI share the same worker functions and
command builders. No business logic duplicated.
"""

from __future__ import annotations

import argparse
import os
import sys
import threading
from pathlib import Path
from typing import Iterable

from . import constants
from .constants import (
    AUDIO_EXTS,
    SUBTITLE_EXTS,
    VIDEO_EXTS,
    DEFAULT_BURN_STYLE,
    ext_of,
    is_audio_file,
    is_lrc_file,
    is_subtitle_file,
    is_video_file,
)
from .ffmpeg.commands import (
    build_burn_subtitle_cmd,
    build_convert_cmd,
    build_extract_audio_cmd,
    build_merge_av_cmd,
    build_subtitle_transcode_cmd,
)
from .ffmpeg.probe import check_ffmpeg_available, get_media_duration
from .ffmpeg.quality import QualityPreset, parse as parse_preset
from .ffmpeg.runner import CancelToken, run_blocking, run_with_progress
from .ffmpeg.installer import (
    cached_binary_paths,
    ffmpeg_cache_dir,
    install_bundle,
    installed_by_us,
    read_marker,
    remove_cache,
    set_data_dir_override,
)
from .fs import ConflictPolicy, resolve_output_path
from .subtitle.converters import (
    SubtitleConversionError,
    lrc_to_srt,
    lrc_to_vtt,
    srt_to_lrc,
    vtt_to_lrc,
)
from .subtitle.styling import inject_burn_style


EXIT_OK = 0
EXIT_USAGE = 2
EXIT_RUNTIME = 3
EXIT_NO_FFMPEG = 4


# ----------------------------------------------------------------------
# Printing helpers
# ----------------------------------------------------------------------

def _err(msg: str) -> None:
    print(f"[error] {msg}", file=sys.stderr)


def _info(msg: str) -> None:
    print(msg, file=sys.stderr)


# ----------------------------------------------------------------------
# Commands
# ----------------------------------------------------------------------

def cmd_where(_args: argparse.Namespace) -> int:
    """Print diagnostic paths - handy for bug reports."""
    print(f"ffmpeg    : {constants.FFMPEG_PATH}")
    print(f"ffprobe   : {constants.FFPROBE_PATH}")
    print(f"ffmpeg usable : {check_ffmpeg_available()}")
    print(f"data dir  : {ffmpeg_cache_dir().parent}")
    print(f"cache dir : {ffmpeg_cache_dir()}")
    marker = read_marker()
    if marker:
        print("marker    :")
        for k, v in marker.items():
            print(f"  {k}: {v}")
    else:
        print("marker    : (none)")
    return EXIT_OK


def cmd_install_ffmpeg(args: argparse.Namespace) -> int:
    if args.data_dir:
        set_data_dir_override(args.data_dir)
    _info(f"下载目标: {ffmpeg_cache_dir()}")

    def on_progress(read: int, total: int) -> None:
        if total <= 0:
            return
        pct = int(read / total * 100)
        # Cap update rate by writing only on 5% steps.
        if not hasattr(on_progress, "_last"):
            on_progress._last = -1  # type: ignore[attr-defined]
        if pct // 5 != on_progress._last:  # type: ignore[attr-defined]
            on_progress._last = pct // 5   # type: ignore[attr-defined]
            print(f"[ffmpeg] {pct}%", file=sys.stderr)

    def on_status(msg: str) -> None:
        print(f"[ffmpeg] {msg}", file=sys.stderr)

    try:
        ff, fp = install_bundle(on_progress=on_progress, on_status=on_status)
    except Exception as exc:
        _err(f"FFmpeg 安装失败: {exc}")
        return EXIT_RUNTIME

    constants.FFMPEG_PATH, constants.FFPROBE_PATH = constants.resolve_ffmpeg_paths()
    print(str(ff))
    print(str(fp))
    return EXIT_OK


def cmd_uninstall_ffmpeg(_args: argparse.Namespace) -> int:
    if not installed_by_us():
        _info("未检测到由本程序下载的 FFmpeg 缓存，无需清理。")
        return EXIT_OK
    target = ffmpeg_cache_dir()
    remove_cache()
    _info(f"已删除: {target}")
    return EXIT_OK


def cmd_install_context_menu(_args: argparse.Namespace) -> int:
    """Register the Windows Explorer cascading context menu under HKCU.

    Works against the running binary: in a PyInstaller frozen build that is
    ``Vertenda.exe``; in a source checkout we have no stable exe to point at,
    so the caller must build first.
    """
    if sys.platform != "win32":
        _err("右键菜单集成只在 Windows 可用。")
        return EXIT_USAGE
    from .shell import win_registry  # imported lazily so macOS/Linux stay clean
    exe = _context_menu_exe_path()
    if exe is None:
        _err("源码模式下无法自动确定可执行文件路径；请先用 scripts\\build_windows.bat 打包后再运行此命令。")
        return EXIT_RUNTIME
    try:
        win_registry.register(exe)
    except (OSError, win_registry.PlatformError, FileNotFoundError) as exc:
        _err(f"注册失败: {exc}")
        return EXIT_RUNTIME
    _info(f"已注册右键菜单 (指向 {exe})。")
    _info("提示: 如果菜单没立刻出现，重启资源管理器 (taskkill /f /im explorer.exe && start explorer) 或注销登录。")
    return EXIT_OK


def cmd_uninstall_context_menu(_args: argparse.Namespace) -> int:
    if sys.platform != "win32":
        _err("右键菜单集成只在 Windows 可用。")
        return EXIT_USAGE
    from .shell import win_registry
    try:
        win_registry.unregister()
    except win_registry.PlatformError as exc:
        _err(str(exc))
        return EXIT_RUNTIME
    _info("已移除右键菜单 (包括旧版本残留)。")
    return EXIT_OK


def _context_menu_exe_path() -> str | None:
    """Path to embed in the registry ``command`` values.

    Only returns a path when we are running a frozen build; otherwise the
    caller cannot safely point Explorer at a stable executable.
    """
    if getattr(sys, "frozen", False):
        return sys.executable
    return None


def cmd_convert(args: argparse.Namespace) -> int:
    """Single-file conversion (possibly to an audio target = extract audio)."""
    if not _require_ffmpeg():
        return EXIT_NO_FFMPEG

    src = os.path.abspath(args.input)
    if not os.path.isfile(src):
        _err(f"输入文件不存在: {src}")
        return EXIT_USAGE

    target = args.format.lower().lstrip(".")
    spec = _spec_from(args)

    if args.output:
        out = os.path.abspath(args.output)
        # Explicit -o must not point at the input itself: ffmpeg would read
        # and truncate the same path concurrently, destroying the source.
        if os.path.abspath(out) == os.path.abspath(src):
            _err(f"输出路径与输入文件相同，已拒绝执行以防源文件被覆盖: {out}")
            return EXIT_USAGE
    else:
        # Default output sits next to the source file — matches user intent
        # for right-click "quick convert" flows. Auto-rename on collision
        # (which includes the same-format case, e.g. foo.mp4 -> foo_1.mp4)
        # so a re-invocation never clobbers the input or a prior output.
        out_dir = args.output_dir or os.path.dirname(src)
        os.makedirs(out_dir, exist_ok=True)
        out = os.path.join(out_dir, Path(src).stem + "." + target)
        out, _ = resolve_output_path(out, ConflictPolicy.RENAME)

    src_ext = ext_of(src)
    target_ext = "." + target

    if src_ext in SUBTITLE_EXTS and target_ext in SUBTITLE_EXTS:
        return _run_subtitle(src, src_ext, target, out)

    if src_ext in SUBTITLE_EXTS or target_ext in SUBTITLE_EXTS:
        _err("字幕互转只能在字幕格式之间进行。")
        return EXIT_USAGE

    # Media paths
    if is_video_file(src) and target_ext in AUDIO_EXTS:
        cmd = build_extract_audio_cmd(src, out, spec=spec)
        label = f"提取音频 · {target}"
    else:
        cmd = build_convert_cmd(
            src, out, use_hw=args.hw_accel, spec=spec,
            trim_start=getattr(args, "trim_start", None),
            trim_end=getattr(args, "trim_end", None),
            scale_preset=getattr(args, "scale", None),
            volume_normalize=getattr(args, "normalize", False),
        )
        label = f"转换 · {target}"

    return _run_media(cmd, label, duration=get_media_duration(src) or 1.0)


def cmd_burn(args: argparse.Namespace) -> int:
    if not _require_ffmpeg():
        return EXIT_NO_FFMPEG

    video = os.path.abspath(args.video)
    subtitle = os.path.abspath(args.subtitle)
    if not os.path.isfile(video):
        _err(f"视频文件不存在: {video}")
        return EXIT_USAGE
    if not os.path.isfile(subtitle):
        _err(f"字幕文件不存在: {subtitle}")
        return EXIT_USAGE

    spec = _spec_from(args)
    out = os.path.abspath(args.output or str(Path(video).with_name(Path(video).stem + "_burned.mp4")))
    hardcode = not args.soft
    if not hardcode and out.lower().endswith(".ts"):
        _err("软封装字幕不支持 TS 容器，请换 MP4 或 MKV。")
        return EXIT_USAGE

    try:
        with inject_burn_style(subtitle) as styled:
            cmd = build_burn_subtitle_cmd(
                video_path=video, styled_sub_path=styled.path, output_path=out,
                hardcode=hardcode, use_hw=args.hw_accel,
                force_style=DEFAULT_BURN_STYLE, spec=spec,
            )
            return _run_media(cmd, f"烧录字幕 · {'硬编码' if hardcode else '软封装'}",
                               duration=get_media_duration(video) or 1.0)
    except RuntimeError as exc:
        _err(f"字幕样式处理失败: {exc}")
        return EXIT_RUNTIME


def cmd_merge(args: argparse.Namespace) -> int:
    if not _require_ffmpeg():
        return EXIT_NO_FFMPEG

    audio = os.path.abspath(args.audio)
    video = os.path.abspath(args.video)
    if not os.path.isfile(audio) or not os.path.isfile(video):
        _err("音频或视频文件不存在。")
        return EXIT_USAGE

    spec = _spec_from(args)
    out = os.path.abspath(args.output or "merged_output.mp4")
    cmd = build_merge_av_cmd(audio, video, out, use_hw=args.hw_accel, spec=spec)
    return _run_media(cmd, "合并音视频", duration=get_media_duration(video) or 1.0)


# ----------------------------------------------------------------------
# Runners
# ----------------------------------------------------------------------

def _spec_from(args: argparse.Namespace):
    from .ffmpeg.quality import spec_for
    return spec_for(parse_preset(getattr(args, "quality", "balanced")))


def _require_ffmpeg() -> bool:
    if check_ffmpeg_available():
        return True
    _err(
        "未找到可用的 FFmpeg。可以先安装一下:\n"
        "  convert install-ffmpeg"
    )
    return False


def _run_media(cmd: list[str], label: str, *, duration: float) -> int:
    _info(f"[{label}] 开始…")
    cancel = CancelToken()
    last = {"pct": -1}

    def on_progress(p: int) -> None:
        if p != last["pct"]:
            last["pct"] = p
            print(f"\r[{label}] {p}%", end="", file=sys.stderr, flush=True)

    result = run_with_progress(
        cmd, duration,
        on_progress=on_progress,
        on_time=lambda _t: None,
        on_log=lambda _line: None,  # keep CLI output clean; user can pipe stderr
        cancel=cancel,
    )
    print("", file=sys.stderr)  # newline after the \r-based progress
    if result.cancelled:
        _err("已取消。")
        return EXIT_RUNTIME
    if not result.ok:
        _err(f"FFmpeg 失败:\n{result.stderr_tail}")
        return EXIT_RUNTIME
    _info(f"[{label}] 完成。")
    return EXIT_OK


def _run_subtitle(src: str, src_ext: str, target: str, out: str) -> int:
    """Pure-python subtitle conversions + ffmpeg-transcode fallback."""
    try:
        if target == "lrc":
            if src_ext == ".srt":
                srt_to_lrc(src, out)
            elif src_ext == ".vtt":
                vtt_to_lrc(src, out)
            elif src_ext in (".ass", ".ssa"):
                tmp_srt = out + ".__tmp__.srt"
                res = run_blocking(build_subtitle_transcode_cmd(src, tmp_srt))
                try:
                    if not res.ok:
                        raise RuntimeError(res.stderr_tail.strip())
                    srt_to_lrc(tmp_srt, out)
                finally:
                    if os.path.exists(tmp_srt):
                        os.remove(tmp_srt)
            else:
                raise RuntimeError(f"不支持从 {src_ext} 转 LRC")
        elif target == "srt" and src_ext == ".lrc":
            lrc_to_srt(src, out)
        elif target == "vtt" and src_ext == ".lrc":
            lrc_to_vtt(src, out)
        else:
            res = run_blocking(build_subtitle_transcode_cmd(src, out))
            if not res.ok:
                raise RuntimeError(res.stderr_tail.strip())
        _info(f"字幕转换完成: {out}")
        return EXIT_OK
    except (SubtitleConversionError, RuntimeError, OSError) as exc:
        _err(f"字幕转换失败: {exc}")
        return EXIT_RUNTIME


# ----------------------------------------------------------------------
# Argument parser
# ----------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vertenda",
        description="盐酸转换器 (Vertenda) · CLI (与 GUI 共享同一套命令构造)",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("--gui", action="store_true", help="强制打开 GUI（默认无参时也是 GUI）")
    parser.add_argument("--version", action="version", version=_version_string())

    sub = parser.add_subparsers(dest="command")

    # --- convert (implicit when called without a subcommand too) ------
    convert_p = sub.add_parser("convert", help="单文件转换（音频/视频/字幕/视频提取音频）")
    _add_convert_args(convert_p)

    # --- burn ----------------------------------------------------------
    burn_p = sub.add_parser("burn", help="字幕烧录到视频")
    burn_p.add_argument("video")
    burn_p.add_argument("subtitle")
    burn_p.add_argument("-o", "--output", help="输出文件路径（默认 <video>_burned.mp4）")
    burn_p.add_argument("--soft", action="store_true", help="软封装（只适用 mp4/mkv）")
    _add_shared_runtime_flags(burn_p)
    burn_p.set_defaults(func=cmd_burn)

    # --- merge ---------------------------------------------------------
    merge_p = sub.add_parser("merge", help="合并音频 + 视频")
    merge_p.add_argument("audio")
    merge_p.add_argument("video")
    merge_p.add_argument("-o", "--output", help="输出文件路径（默认 merged_output.mp4）")
    _add_shared_runtime_flags(merge_p)
    merge_p.set_defaults(func=cmd_merge)

    # --- install-ffmpeg / uninstall-ffmpeg / where --------------------
    inst_p = sub.add_parser("install-ffmpeg", help="下载并安装静态 FFmpeg 到数据目录")
    inst_p.add_argument("--data-dir", help="（可选）指定数据目录的父路径，覆盖默认 AppData")
    inst_p.set_defaults(func=cmd_install_ffmpeg)

    un_p = sub.add_parser("uninstall-ffmpeg", help="删除本程序下载的 FFmpeg 缓存")
    un_p.set_defaults(func=cmd_uninstall_ffmpeg)

    ctx_in_p = sub.add_parser("install-context-menu",
                               help="注册 Windows 资源管理器右键菜单 (HKCU)")
    ctx_in_p.set_defaults(func=cmd_install_context_menu)

    ctx_un_p = sub.add_parser("uninstall-context-menu",
                               help="移除 Windows 资源管理器右键菜单 (含旧版残留)")
    ctx_un_p.set_defaults(func=cmd_uninstall_context_menu)

    where_p = sub.add_parser("where", help="打印路径信息，用于排错")
    where_p.set_defaults(func=cmd_where)

    # The default parser is `convert`: allow `convert input.wav -f mp3` without
    # saying `convert convert input.wav ...`. We wire this via a positional
    # arg on the top-level parser too, detected later in `dispatch`.
    _add_convert_args(parser, add_func=False, add_positional=False)
    return parser


def _add_convert_args(p: argparse.ArgumentParser, *,
                       add_func: bool = True, add_positional: bool = True) -> None:
    if add_positional:
        p.add_argument("input", nargs="?", help="输入文件")
    p.add_argument("-f", "--format", help="目标格式（扩展名，不带点）")
    p.add_argument("-o", "--output", help="显式输出文件路径")
    p.add_argument("-d", "--output-dir", help="输出目录（不指定 -o 时用）")
    _add_shared_runtime_flags(p)
    if add_func:
        p.set_defaults(func=cmd_convert)


def _add_shared_runtime_flags(p: argparse.ArgumentParser) -> None:
    p.add_argument("--hw-accel", action="store_true", help="开启 macOS VideoToolbox 加速")
    p.add_argument("-q", "--quality", default="balanced",
                   choices=[qp.value for qp in QualityPreset],
                   help="转换质量预设 (默认 balanced)")
    p.add_argument("--conflict", default="overwrite",
                   choices=["skip", "overwrite", "rename"],
                   help="冲突策略: skip/overwrite/rename (默认 overwrite)")
    p.add_argument("--filename-template", default="{base}",
                   help="输出文件名模板 (默认 {base})")
    p.add_argument("--concurrency", default="auto",
                   help="并发路数: auto 或 1-8 (默认 auto)")
    p.add_argument("--scale", default=None,
                   help="缩放: 1080p/720p/480p/WxH")
    p.add_argument("--normalize", action="store_true",
                   help="音量归一化 (loudnorm EBU R128)")
    p.add_argument("--trim-start", type=float, default=None,
                   help="裁剪起始时间 (秒)")
    p.add_argument("--trim-end", type=float, default=None,
                   help="裁剪结束时间 (秒)")


def _version_string() -> str:
    try:
        from . import __version__
        return f"convert {__version__}"
    except Exception:
        return "convert (unknown)"


# ----------------------------------------------------------------------
# Entry dispatcher
# ----------------------------------------------------------------------

_KNOWN_SUBCOMMANDS = {
    "convert", "burn", "merge",
    "install-ffmpeg", "uninstall-ffmpeg",
    "install-context-menu", "uninstall-context-menu",
    "where",
}


def _normalise_argv(argv: list[str]) -> list[str]:
    """Allow the implicit ``convert`` form: ``convert file.wav -f mp3``.

    Argparse's required subparsers can't be skipped, so we synthetically
    insert ``convert`` before the first positional when it isn't itself
    one of the known subcommands.
    """
    if not argv:
        return argv
    if argv[0] in _KNOWN_SUBCOMMANDS or argv[0].startswith("-"):
        return argv
    return ["convert", *argv]


def main(argv: Iterable[str] | None = None) -> int:
    argv_list = list(argv) if argv is not None else sys.argv[1:]
    argv_list = _normalise_argv(argv_list)

    parser = build_parser()
    args = parser.parse_args(argv_list)

    if args.gui:
        return _launch_gui(parser)

    if args.command is None:
        return _launch_gui(parser)

    func = getattr(args, "func", None)
    if func is None:
        parser.error("未实现的子命令")
        return EXIT_USAGE
    return func(args)


def _launch_gui(_parser: argparse.ArgumentParser) -> int:
    # Import lazily so `convert install-ffmpeg` from a headless shell doesn't
    # need Qt libraries.
    try:
        from Main import main as gui_main  # type: ignore
    except Exception as exc:
        _err(f"无法启动 GUI: {exc}")
        return EXIT_RUNTIME
    return gui_main()
