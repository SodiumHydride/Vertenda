# -*- coding: utf-8 -*-
"""Command-line interface for Convert.

Two usage shapes, both routed through the same argparse:

  Simple (happy-path) form - auto-detects input kind:
    convert input.wav -f mp3
    convert input.mov -f mp4 --hw-accel --quality high
    convert input.srt -f lrc

  Explicit subcommands for multi-input or management tasks:
    convert burn video.mp4 subs.srt -o out.mp4 [--soft]
    convert merge audio.mp3 video.mp4 -o merged.mp4
    convert install-ffmpeg [--data-dir PATH]
    convert uninstall-ffmpeg
    convert where
    convert --gui

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
    else:
        out_dir = args.output_dir or os.path.dirname(src)
        os.makedirs(out_dir, exist_ok=True)
        out = os.path.join(out_dir, Path(src).stem + "." + target)

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
        cmd = build_convert_cmd(src, out, use_hw=args.hw_accel, spec=spec)
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
        prog="convert",
        description="盐酸转换器 · CLI (与 GUI 共享同一套命令构造)",
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
    "convert", "burn", "merge", "install-ffmpeg", "uninstall-ffmpeg", "where",
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
