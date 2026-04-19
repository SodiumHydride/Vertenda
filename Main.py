# -*- coding: utf-8 -*-
"""
支持音频、视频、字幕格式转换（含 srt、vtt、lrc、ass、ssa 各种互转），音视频合并, 字幕烧录等功能。
具有美化的图形用户界面，包含背景图、透明度、主题切换等设置，并集成 GPU 硬件加速。
修复了 FFmpeg 选项位置错误的问题, 增加实时进度显示, 右键打开文件位置, 字幕样式功能。
"""

import subprocess
import sys

if sys.platform == "win32":
    import subprocess
    from subprocess import STARTUPINFO, STARTF_USESHOWWINDOW

    CREATE_NO_WINDOW = 0x08000000

    # 保存原始的 Popen 方法
    original_popen = subprocess.Popen

    def subprocess_popen(*args, **kwargs):
        # 如果没有指定 creationflags，则添加 CREATE_NO_WINDOW
        if 'creationflags' not in kwargs:
            kwargs['creationflags'] = CREATE_NO_WINDOW
        else:
            kwargs['creationflags'] |= CREATE_NO_WINDOW
        return original_popen(*args, **kwargs)

    # 替换 subprocess.Popen 为自定义的函数
    subprocess.Popen = subprocess_popen

import os
import re
import subprocess
import json
import datetime
import shutil  # 导入 shutil 模块

from PyQt5.QtCore import (
    Qt, QThread, pyqtSignal, QSettings, QDir
)
from PyQt5.QtGui import (
    QIcon, QPixmap, QPainter, QFont
)
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QFileDialog, QMessageBox, QLabel, QLineEdit,
    QPlainTextEdit, QProgressBar, QDialog, QMenu,
    QFormLayout, QComboBox, QCheckBox,
    QSpinBox, QToolButton, QListWidget, QListWidgetItem, QSlider,
    QAbstractItemView, QTabWidget  # 导入 QTabWidget
)

# ==================== 工具函数 ====================

def resource_path(relative_path: str) -> str:
    """
    若打包后，在 _MEIPASS 下找资源；
    若没打包，就在当前脚本目录下找。
    """
    if hasattr(sys, '_MEIPASS'):
        base_path = sys._MEIPASS
    else:
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, relative_path)
ffmpeg_executable = resource_path("resources/ffmpeg")
ffprobe_executable = resource_path("resources/ffprobe")

def is_audio_file(filepath: str) -> bool:
    """简单通过后缀判断是否是音频"""
    ext = os.path.splitext(filepath)[1].lower()
    return ext in ['.mp3', '.wav', '.flac', '.aac', '.m4a', '.ogg', '.wma', '.opus']

def is_video_file(filepath: str) -> bool:
    """简单通过后缀判断是否是视频"""
    ext = os.path.splitext(filepath)[1].lower()
    return ext in ['.mp4', '.mov', '.avi', '.mkv', '.flv', '.wmv', '.webm', '.ts', '.rmvb']  # 增加 rmvb

def is_lrc_file(filepath: str) -> bool:
    """是否 LRC 歌词"""
    return os.path.splitext(filepath)[1].lower() == '.lrc'

def is_subtitle_file(filepath: str) -> bool:
    """是否常见字幕文件 (srt, ass, ssa, vtt, lrc 都算)"""
    ext = os.path.splitext(filepath)[1].lower()
    return ext in ['.srt', '.ass', '.ssa', '.vtt', '.lrc']

def inject_ass_style(sub_path: str) -> str:
    """为字幕文件注入粉色+黑边样式，返回临时文件路径"""
    temp_path = os.path.splitext(sub_path)[0] + "_styled.ass"

    # 转换字幕为ASS格式
    if not sub_path.lower().endswith('.ass'):
        success, _ = ffmpeg_subtitle_convert(sub_path, temp_path)
        if not success:
            return sub_path  # 转换失败则使用原文件
    else:
        temp_path = sub_path

    # 插入样式定义
    with open(temp_path, 'r+', encoding='utf-8') as f:
        content = f.read()
        if "[V4+ Styles]" not in content:
            style_header = (
                "[V4+ Styles]\n"
                "Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, "
                "Bold, Italic, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV\n"
                "Style: MyStyle,Arial,24,&HFF00FF,&H00000000,&H00000000,0,0,1,2,0,2,10,10,10\n\n"
            )
            f.seek(0)
            f.write(style_header + content)

    return temp_path

def ffmpeg_convert(input_path: str, output_path: str, use_hw_accel=False) -> (bool, str):  # 增加 use_hw_accel 参数
    """高级音视频转换函数，支持专业音频和视频参数，可选 GPU 硬件加速"""
    output_ext = os.path.splitext(output_path)[1].lower()

    # 音频编码参数
    audio_params = {
        '.mp3': ['-c:a', 'libmp3lame', '-b:a', '320k'],
        '.flac': ['-c:a', 'flac', '-compression_level', '12'],
        '.aac': ['-c:a', 'aac', '-b:a', '256k'],
        '.opus': ['-c:a', 'libopus', '-b:a', '128k', '-vbr', 'on'],
        '.wav': ['-c:a', 'pcm_s16le'],
        '.ogg': ['-c:a', 'libvorbis', '-q:a', '6']
    }

    # 视频编码参数 (软件编码)
    video_params_sw = {
        '.mp4': ['-c:v', 'libx264', '-preset', 'medium', '-crf', '23'],
        '.mkv': ['-c:v', 'libx265', '-preset', 'fast', '-crf', '28'],
        '.mov': ['-c:v', 'prores_ks', '-profile:v', '3'],  # ProRes for MOV
        '.avi': ['-c:v', 'mpeg4', '-qscale:v', '5'],  # MPEG4 for AVI
        '.flv': ['-c:v', 'flv1'],  # FLV1 for FLV
        '.wmv': ['-c:v', 'wmv2'],  # WMV2 for WMV
        '.webm': ['-c:v', 'libvpx-vp9', '-b:v', '2M'],  # VP9 for WebM
        '.ts': ['-c:v', 'libx264', '-preset', 'fast', '-crf', '25', '-muxer', 'mpegts'],  # H.264 in MPEG-TS
        '.rmvb': ['-c:v', 'librmvb', '-qscale:v', '5']  # librmvb for RMVB (需要安装)
    }

    # 视频编码参数 (硬件加速) - macOS VideoToolbox
    video_params_hw_macOS = {
        '.mp4': ['-c:v', 'h264_videotoolbox', '-b:v', '10M', '-allow_sw', '1'],  # H.264 编码，兼容性更好
        '.mov': ['-c:v', 'prores_videotoolbox', '-profile:v', '3'],  # ProRes 编码
        '.mkv': ['-c:v', 'hevc_videotoolbox', '-b:v', '10M', '-allow_sw', '1'],  # HEVC (H.265) 编码，更高压缩率
        '.avi': ['-c:v', 'h264_videotoolbox', '-b:v', '10M'],  # AVI 格式使用 H.264 编码
        '.flv': ['-c:v', 'h264_videotoolbox', '-b:v', '10M'],  # FLV 格式使用 H.264 编码
        '.webm': ['-c:v', 'libvpx-vp9'],  # WebM 格式仍然使用软件编码 (VP9)
        '.ts': ['-c:v', 'h264_videotoolbox', '-b:v', '10M', '-muxer', 'mpegts'],  # TS 格式使用 H.264 编码
        '.rmvb': ['-c:v', 'librmvb']  # RMVB 格式无硬件加速，继续使用软件编码
    }

    # 根据平台选择硬件加速参数
    hw_accel_args = []
    if use_hw_accel and sys.platform == "darwin":  # macOS
        hw_accel_args = ['-hwaccel', 'videotoolbox']
        video_params = video_params_hw_macOS
    else:
        video_params = video_params_sw

    base_cmd = [ffmpeg_executable, '-y'] + hw_accel_args + ['-i', input_path] # 硬件加速参数放在 -i 前面

    # 根据输出格式判断处理方式
    if is_video_file(output_path):
        # 视频转换保留音视频流, 默认音频转码为 AAC
        base_cmd.extend([
            '-c:a', 'aac', '-b:a', '192k',  # 音频编码
            '-map_metadata', '-1',  # 清除元数据
            '-movflags', '+faststart',  # MP4 优化
            '-sn', '-dn'  # 移除字幕和data流
        ])
        # 添加视频编码参数
        if output_ext in video_params:
            base_cmd.extend(video_params[output_ext])
        else:
            base_cmd.extend(['-c:v', 'copy'])  # 默认视频 copy (不转码)

    else:
        # 音频转换禁用视频流
        base_cmd.extend(['-vn', '-sn', '-dn', '-map_metadata', '-1'])
        # 添加音频编码参数
        if output_ext in audio_params:
            base_cmd.extend(audio_params[output_ext])
        else:
            base_cmd.extend(['-c:a', 'copy'])  # 默认音频 copy (不转码)

    base_cmd.append(output_path)

    cmd = base_cmd
    print("执行的 FFmpeg 命令:", ' '.join(cmd))  # 调试输出：打印完整的 FFmpeg 命令
    try:
        cp = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding='utf-8',
            errors='ignore'
        )
        if cp.returncode != 0:
            return False, cp.stderr
        return True, ""
    except Exception as e:
        return False, str(e)

def ffmpeg_merge_av(audio_path: str, video_path: str, output_path: str, use_hw_accel=False) -> (bool, str):  # 合并也增加硬件加速选项
    """使用 ffmpeg 合并音频 + 视频，并确保音频为 AAC 格式, 可选 GPU 加速"""
    hw_accel_args = []
    if use_hw_accel and sys.platform == "darwin":  # macOS 硬件加速合并
        hw_accel_args = ['-hwaccel', 'videotoolbox']

    cmd = [
        ffmpeg_executable,
        '-y',
    ] + hw_accel_args + [ # 硬件加速参数放在全局选项后，输入文件前
        '-i', video_path,  # 第一个输入：视频文件
        '-i', audio_path,  # 第二个输入：音频文件
    ]

    if use_hw_accel and sys.platform == "darwin":  # macOS 硬件加速合并
        cmd.extend([
            '-c:v', 'h264_videotoolbox', '-b:v', '10M',  # 使用 H.264 编码，兼容性更好
            '-c:a', 'aac',  # 音频编码
            '-b:a', '320k',  # 音频比特率
            '-map', '0:v:0',  # 映射第一个输入（视频）的第一个视频流
            '-map', '1:a:0',  # 映射第二个输入（音频）的第一个音频流
            '-shortest',  # 输出文件长度与最短输入流一致
            output_path
        ])
    else:  # 默认软件编码合并
        cmd.extend([
            '-c:v', 'copy',  # 复制视频流，不重新编码
            '-c:a', 'aac',  # 转码音频为 AAC 以确保兼容性
            '-b:a', '320k',  # 设置较高的音频比特率以保持音质
            '-map', '0:v:0',  # 映射第一个输入（视频）的第一个视频流
            '-map', '1:a:0',  # 映射第二个输入（音频）的第一个音频流
            '-shortest',  # 输出文件长度与最短输入流一致
            output_path
        ])

    try:
        cp = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding='utf-8',
            errors='ignore'
        )
        # 记录详细的 ffmpeg 输出
        log = cp.stdout + "\n" + cp.stderr
        if cp.returncode != 0:
            return False, log
        return True, log
    except Exception as e:
        return False, str(e)

def ffmpeg_subtitle_convert(input_path: str, output_path: str) -> (bool, str):
    """
    用 ffmpeg 做简单的字幕格式转换 (srt, vtt, ass, ssa) 等，
    但不包含 lrc，因为 ffmpeg 不识别 lrc 作为输入/输出
    """
    cmd = [
        ffmpeg_executable,
        '-y',
        '-i', input_path,
        output_path
    ]
    try:
        cp = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding='utf-8',
            errors='ignore'
        )
        if cp.returncode != 0:
            return False, cp.stderr
        return True, ""
    except Exception as e:
        return False, str(e)

def ffmpeg_burn_subtitle(video_path: str, sub_path: str, output_path: str,
                         hardcode=True, output_format='mp4', use_hw_accel=False) -> (bool, str):  # 烧录也增加硬件加速
    """
    使用 ffmpeg 烧录字幕到视频

    Args:
        video_path: 视频文件路径
        sub_path: 字幕文件路径
        output_path: 输出视频文件路径
        hardcode: True 为硬编码, False 为软封装 (如果支持)
        output_format: 输出格式，用于软封装时选择合适的字幕编码器
        use_hw_accel: 是否使用 GPU 硬件加速

    Returns:
        (bool, str): 成功/失败, 错误信息
    """
    # 格式兼容性检查
    if output_format == 'ts':
        return False, "TS格式不支持字幕烧录，请选择MP4/MKV格式"
    if hardcode and output_format == 'mov':
        return False, "MOV格式硬编码字幕可能存在兼容性问题，建议使用软封装或转换为MP4/MKV"
    if not hardcode and output_format not in ['mp4', 'mkv']:
        return False, "软封装字幕仅支持MP4和MKV格式"
    if not hardcode and output_format == 'mp4' and not sub_path.lower().endswith(('.srt', '.mov_text')):  # 扩展支持 mov_text
        return False, "MP4软封装字幕推荐使用SRT或MOV_TEXT格式"
    if not hardcode and output_format == 'mkv' and not sub_path.lower().endswith(('.srt', '.ass', '.ssa', '.vtt')):  # MKV 支持更多
        return False, "MKV软封装字幕支持 SRT, ASS, SSA, VTT 格式"

    hw_accel_args = []
    if use_hw_accel and sys.platform == "darwin": # macOS 硬件加速硬编码
        hw_accel_args = ['-hwaccel', 'videotoolbox']

    # 样式注入
    styled_sub = inject_ass_style(sub_path)
    need_cleanup = styled_sub != sub_path

    # 硬编码参数优化
    if hardcode:
        cmd = [
            ffmpeg_executable, '-y',
        ] + hw_accel_args + [ # 硬件加速参数放在全局选项后，输入文件前
            '-i', video_path,
            '-vf', f'subtitles={styled_sub}:force_style=FontName=Arial,PrimaryColour=&H00FFC0CB,OutlineColour=&H00000000,BorderStyle=1,Outline=2',  # 强制中文字体 + 粉色+黑边样式
        ]
        if use_hw_accel and sys.platform == "darwin":  # macOS 硬件加速硬编码
            cmd.extend([
                '-c:v', 'h264_videotoolbox', '-b:v', '10M',  # 视频硬件编码，使用 H.264
                '-c:a', 'aac', '-b:a', '192k',  # 音频编码
                output_path
            ])
        else:  # 默认软件编码硬编码
            cmd.extend([
                '-c:v', 'libx264',
                '-preset', 'fast',
                '-crf', '23',
                '-c:a', 'aac',
                '-b:a', '192k',
                output_path
            ])

    else:  # 软封装
        cmd = [
            ffmpeg_executable,
            '-y',
            '-i', video_path,
            '-i', styled_sub,
            '-map', '0',  # 映射所有输入流 (视频+音频)
            '-map', '1',  # 映射字幕流
            '-c', 'copy',  # 视频和音频流都直接复制, 软封装不转码
            '-c:s', 'ass',  # 软封装必须使用 ass 才能保证样式
            '-metadata:s:s:0', 'language=chi',  # 字幕语言 metadata
            output_path
        ]
    try:
        cp = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding='utf-8',
            errors='ignore'
        )
        if cp.returncode != 0:
            return False, cp.stderr
        return True, ""
    except Exception as e:
        return False, str(e)
    finally:
        if need_cleanup and os.path.exists(styled_sub) and styled_sub != sub_path:
            os.remove(styled_sub) # 清理临时样式文件

# ============ LRC 解析与转换 ============

def parse_lrc(lrc_path: str) -> list:
    """解析LRC，返回列表 [(time_in_sec, text), ...]"""
    lines_data = []
    # 支持 [mm:ss.xx] 或 [mm:ss] 格式
    time_pattern = re.compile(r'\[(\d{1,2}):(\d{1,2})(?:\.(\d{1,2}))?\]')
    with open(lrc_path, 'r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            line = line.strip()
            matches = time_pattern.findall(line)
            text = time_pattern.sub('', line).strip()
            for m in matches:
                mm = int(m[0])  # 分
                ss = int(m[1])  # 秒
                ms = int(m[2]) if m[2] else 0  # 毫秒
                total_sec = mm * 60 + ss + ms / 100
                lines_data.append((total_sec, text))
    lines_data.sort(key=lambda x: x[0])
    return lines_data

def sec_to_srt_timestamp(sec: float) -> str:
    """秒数转SRT时间戳格式"""
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = int(sec % 60)
    ms = int(round((sec - int(sec)) * 1000))
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

def sec_to_vtt_timestamp(sec: float) -> str:
    """秒数转VTT时间戳格式"""
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = int(sec % 60)
    ms = int(round((sec - int(sec)) * 1000))
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"

def srt_to_lrc_timestamp(sec: float) -> str:
    """秒数转 LRC 时间戳 [mm:ss.xx]"""
    # LRC 一般不需要到小时
    mm = int((sec % 3600) // 60)
    ss = int(sec % 60)
    ms = int(round((sec - int(sec)) * 100))
    return f"[{mm:02d}:{ss:02d}.{ms:02d}]"

def lrc_to_srt(lrc_path: str, srt_path: str) -> (bool, str):
    """将LRC转换为SRT"""
    data = parse_lrc(lrc_path)
    if not data:
        return False, "未解析到任何LRC数据。"
    try:
        with open(srt_path, 'w', encoding='utf-8') as f:
            for i in range(len(data)):
                start_sec, text = data[i]
                if i + 1 < len(data):
                    end_sec = data[i + 1][0]
                else:
                    end_sec = start_sec + 2  # 默认持续2秒
                f.write(f"{i + 1}\n")
                f.write(f"{sec_to_srt_timestamp(start_sec)} --> {sec_to_srt_timestamp(end_sec)}\n")
                f.write(f"{text}\n\n")
        return True, ""
    except Exception as e:
        return False, f"LRC 转 SRT 错误: {e}"

def lrc_to_vtt(lrc_path: str, vtt_path: str) -> (bool, str):
    """将LRC转换为VTT"""
    data = parse_lrc(lrc_path)
    if not data:
        return False, "未解析到任何LRC数据。"
    try:
        with open(vtt_path, 'w', encoding='utf-8') as f:
            f.write("WEBVTT\n\n")
            for i in range(len(data)):
                start_sec, text = data[i]
                if i + 1 < len(data):
                    end_sec = data[i + 1][0]
                else:
                    end_sec = start_sec + 2  # 默认持续2秒
                f.write(f"{sec_to_vtt_timestamp(start_sec)} --> {sec_to_vtt_timestamp(end_sec)}\n")
                f.write(f"{text}\n\n")
        return True, ""
    except Exception as e:
        return False, f"LRC 转 VTT 错误: {e}"

# ============ SRT 解析与转换 ============

def parse_srt(srt_path: str) -> list:
    """
    解析SRT，返回列表 [(start_sec, end_sec, text), ...]
    """
    pattern_time = re.compile(r'(\d{2}):(\d{2}):(\d{2}),(\d{3})')
    data = []
    try:
        with open(srt_path, 'r', encoding='utf-8', errors='ignore') as f:
            blocks = f.read().split('\n\n')
            idx_counter = 1
            for block in blocks:
                lines = block.strip().split('\n')
                if len(lines) >= 2:
                    # 第一行一般是数字序号 idx
                    # 第二行是时间戳
                    match_time = pattern_time.findall(lines[1])
                    if len(match_time) == 2:
                        start_h, start_m, start_s, start_ms = match_time[0]
                        end_h, end_m, end_s, end_ms = match_time[1]
                        start_sec = (int(start_h) * 3600 + int(start_m) * 60 +
                                     int(start_s) + int(start_ms)/1000.0)
                        end_sec = (int(end_h) * 3600 + int(end_m) * 60 +
                                   int(end_s) + int(end_ms)/1000.0)
                        text = '\n'.join(lines[2:])
                        data.append((start_sec, end_sec, text))
                    idx_counter += 1
        return data
    except Exception as e:
        print(f"parse_srt 错误: {e}")
        return []

def srt_to_lrc(srt_path: str, lrc_path: str) -> (bool, str):
    """
    将 SRT 转换为 LRC。
    LRC 没有“结束时间”概念，这里仅用每条字幕的开始时间做 LRC 时间戳。
    """
    data = parse_srt(srt_path)
    if not data:
        return False, "未解析到任何SRT数据。"
    try:
        with open(lrc_path, 'w', encoding='utf-8') as f:
            for (start_sec, end_sec, text) in data:
                # 去除可能多行字幕，转成一行
                text_single_line = text.replace('\n', ' ')
                # 写 LRC 时间戳 + 文本
                f.write(f"{srt_to_lrc_timestamp(start_sec)}{text_single_line}\n")
        return True, ""
    except Exception as e:
        return False, f"SRT 转 LRC 错误: {e}"

# ============ VTT 解析与转换 ============

def parse_vtt(vtt_path: str) -> list:
    """
    解析VTT，返回列表 [(start_sec, end_sec, text), ...]
    与 srt 类似，只是时间戳格式是 00:00:00.000
    """
    pattern_time = re.compile(r'(\d{2}):(\d{2}):(\d{2})\.(\d{3})')
    data = []
    try:
        with open(vtt_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read().strip()
            # 去掉开头的 "WEBVTT" 行
            if content.startswith("WEBVTT"):
                content = content[len("WEBVTT"):].strip()

            blocks = content.split('\n\n')
            for block in blocks:
                lines = block.strip().split('\n')
                # 可能有的块是空的
                if len(lines) < 2:
                    continue
                # vtt 第1行可能是序号 或 直接就是时间
                # 逐行找时间行
                time_line_idx = None
                for i, line in enumerate(lines):
                    if '-->' in line:
                        time_line_idx = i
                        break
                if time_line_idx is None:
                    continue
                time_line = lines[time_line_idx]
                match_time = pattern_time.findall(time_line)
                if len(match_time) == 2:
                    start_h, start_m, start_s, start_ms = match_time[0]
                    end_h, end_m, end_s, end_ms = match_time[1]
                    start_sec = (int(start_h) * 3600 + int(start_m) * 60 +
                                 int(start_s) + int(start_ms)/1000.0)
                    end_sec = (int(end_h) * 3600 + int(end_m) * 60 +
                               int(end_s) + int(end_ms)/1000.0)
                    # 剩下的行都拼起来
                    text_lines = lines[time_line_idx+1:]
                    text = '\n'.join(text_lines)
                    data.append((start_sec, end_sec, text))
        return data
    except Exception as e:
        print(f"parse_vtt 错误: {e}")
        return []

def vtt_to_lrc(vtt_path: str, lrc_path: str) -> (bool, str):
    """
    VTT 转 LRC
    """
    data = parse_vtt(vtt_path)
    if not data:
        return False, "未解析到任何VTT数据。"
    try:
        with open(lrc_path, 'w', encoding='utf-8') as f:
            for (start_sec, end_sec, text) in data:
                # 同样转成单行
                text_single_line = text.replace('\n', ' ')
                f.write(f"{srt_to_lrc_timestamp(start_sec)}{text_single_line}\n")
        return True, ""
    except Exception as e:
        return False, f"VTT 转 LRC 错误: {e}"

# =============== 自定义 QListWidget 类以支持拖拽和右键菜单 ===============

class FileListWidget(QListWidget):
    """自定义 QListWidget 以支持拖拽所有文件格式和右键菜单"""

    def __init__(self, parent=None):
        super(FileListWidget, self).__init__(parent)
        self.setAcceptDrops(True)
        self.setDragEnabled(True)
        self.setSelectionMode(QListWidget.ExtendedSelection)
        # 显示拖拽指示虚线
        self.setDropIndicatorShown(True)
        # 设置为只允许外部拖拽进来，避免在内部排序时出现冲突
        self.setDragDropMode(QAbstractItemView.DropOnly)
        # 右键菜单
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_context_menu)

    def dragEnterEvent(self, event):
        # 如果是带URL的拖拽（文件路径），就接受，否则忽略
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            # 接受拖拽复制操作
            event.setDropAction(Qt.CopyAction)
            event.acceptProposedAction()
            for url in event.mimeData().urls():
                fpath = url.toLocalFile()
                if os.path.isfile(fpath):
                    self.addItem(QListWidgetItem(fpath))
        else:
            event.ignore()

    def show_context_menu(self, pos):
        """显示右键菜单"""
        menu = QMenu(self)
        open_location_action = menu.addAction("打开文件位置")
        open_location_action.triggered.connect(self.open_file_location)
        menu.exec_(self.viewport().mapToGlobal(pos))

    def open_file_location(self):
        """打开文件所在位置"""
        item = self.currentItem()
        if item:
            file_path = item.text()
            if os.path.exists(file_path):
                folder_path = os.path.dirname(file_path)
                if sys.platform == "win32":
                    os.startfile(folder_path)
                elif sys.platform == "darwin":
                    subprocess.Popen(["open", folder_path])
                elif sys.platform.startswith("linux"):
                    subprocess.Popen(["xdg-open", folder_path])
                else:
                    QMessageBox.warning(self.parent(), "提示", "无法打开文件位置: 不支持的操作系统")

# =============== 线程：执行转换合并任务 (实时进度) ===============

class ConvertWorker(QThread):
    progress_signal = pyqtSignal(int)
    log_signal = pyqtSignal(str)
    finished_signal = pyqtSignal()
    error_signal = pyqtSignal(str)
    time_signal = pyqtSignal(str) # 实时时间信号

    def __init__(self, file_list, target_format, tabs_index=0, merge_av=False, burn_subtitle_options=None, use_hw_accel=False, parent=None): # 增加 use_hw_accel, tabs_index
        super().__init__(parent)
        self.file_list = file_list
        self.target_format = target_format
        self.tabs_index = tabs_index # 当前 Tab 的索引
        self.merge_av = merge_av
        self.burn_subtitle_options = burn_subtitle_options # 新增字幕烧录选项
        self.use_hw_accel = use_hw_accel # 是否使用硬件加速
        self._running = True
        self.output_path = None  # 稍后会在主窗口里赋值

    def run(self):
        total = len(self.file_list)

        # 如果勾选了“合并音视频”
        if self.merge_av:
            self.log_signal.emit("准备合并音视频...\n")
            audio_files = [f for f in self.file_list if is_audio_file(f)]
            video_files = [f for f in self.file_list if is_video_file(f)]

            if not audio_files or not video_files:
                self.error_signal.emit("合并失败：至少需要一个音频和一个视频文件。")
                return

            # 选择第一个音频和第一个视频文件
            audio_path = audio_files[0]
            video_path = video_files[0]

            # 检查文件是否存在
            if not os.path.exists(audio_path):
                self.error_signal.emit(f"音频文件不存在: {audio_path}")
                return
            if not os.path.exists(video_path):
                self.error_signal.emit(f"视频文件不存在: {video_path}")
                return

            out_dir = self.output_path if self.output_path else os.path.dirname(audio_path)
            # 确保输出目录存在
            if not os.path.exists(out_dir):
                try:
                    os.makedirs(out_dir)
                except Exception as e:
                    self.error_signal.emit(f"无法创建输出目录: {out_dir}\n{e}")
                    return
            out_path = os.path.join(out_dir, "merged_output.mp4")
            self.log_signal.emit(f"合并文件：\n音频: {audio_path}\n视频: {video_path}\n输出: {out_path}\n")
            ok, error_msg = ffmpeg_merge_av(audio_path, video_path, out_path, use_hw_accel=self.use_hw_accel) # 传递硬件加速参数
            if not ok:
                self.error_signal.emit(f"音视频合并失败，请检查文件格式或 ffmpeg 环境。\n错误信息:\n{error_msg}")
                return
            self.log_signal.emit(f"合并成功: {out_path}\n")
            self.progress_signal.emit(100)
            self.finished_signal.emit()
            return

        # 如果是字幕烧录任务
        if self.burn_subtitle_options:
            video_path = self.burn_subtitle_options.get('video_path')
            sub_path = self.burn_subtitle_options.get('sub_path')
            burn_hardcode = self.burn_subtitle_options.get('burn_hardcode', True) # 从 options 中取布尔值
            output_format = self.burn_subtitle_options.get('output_format', 'mp4')

            if not video_path or not sub_path:
                self.error_signal.emit("字幕烧录失败：视频文件和字幕文件路径未提供。")
                return
            if not os.path.exists(video_path):
                self.error_signal.emit(f"视频文件不存在: {video_path}")
                return
            if not os.path.exists(sub_path):
                self.error_signal.emit(f"字幕文件不存在: {sub_path}")
                return
            if video_path.lower().endswith('.ts') and not burn_hardcode: # 根据布尔值判断
                self.error_signal.emit("TS 格式不支持软封装字幕，请选择硬编码或转换为 MP4/MKV 格式。")
                return

            out_dir = self.output_path if self.output_path else os.path.dirname(video_path)
            if not os.path.exists(out_dir):
                try:
                    os.makedirs(out_dir)
                except Exception as e:
                    self.error_signal.emit(f"无法创建输出目录: {out_dir}\n{e}")
                    return

            base = os.path.splitext(os.path.basename(video_path))[0]
            out_ext = '.' + output_format
            out_path = os.path.join(out_dir, base + "_burned" + out_ext)

            self.log_signal.emit(f"开始字幕烧录：\n视频: {video_path}\n字幕: {sub_path}\n模式: {'硬编码' if burn_hardcode else '软封装'}\n输出: {out_path}\n")

            cmd = self.ffmpeg_burn_subtitle_cmd(video_path, sub_path, out_path,
                                                    hardcode=burn_hardcode, output_format=output_format,
                                                    use_hw_accel=self.use_hw_accel) # 获取命令列表

            duration = get_media_duration(video_path) # 获取视频时长, 用于进度计算
            if duration is None:
                self.error_signal.emit("无法获取视频时长，进度显示可能不准确。")
                duration = 1.0 # 避免除以零

            ok, error_msg = self.run_ffmpeg_with_progress(cmd, duration) # 执行命令并显示进度

            if not ok:
                self.error_signal.emit(f"字幕烧录失败，请检查文件和参数。\n错误信息:\n{error_msg}")
                return
            self.log_signal.emit(f"字幕烧录成功: {out_path}\n")
            self.progress_signal.emit(100)
            self.finished_signal.emit()
            return

        # 否则，执行批量格式转换 (音频/视频/字幕)
        if self.tabs_index == 2: # 字幕转换 Tab
            target_format = self.target_format # 直接就是目标格式 (srt, vtt, ass, lrc, ssa)

            if total == 0:
                self.error_signal.emit("没有文件可转换！")
                return

            self.log_signal.emit(f"开始字幕转换 - 目标格式: {target_format.upper()}...\n")
            for i, fpath in enumerate(self.file_list, start=1):
                if not self._running:
                    self.log_signal.emit("用户取消了任务。\n")
                    return

                if not os.path.exists(fpath):
                    self.log_signal.emit(f"[失败] 文件不存在: {fpath}\n")
                    continue

                base = os.path.splitext(os.path.basename(fpath))[0]
                dir_ = self.output_path if self.output_path else os.path.dirname(fpath)

                # 确保输出目录存在
                if not os.path.exists(dir_):
                    try:
                        os.makedirs(dir_)
                    except Exception as e:
                        self.log_signal.emit(f"[失败] 创建输出目录失败: {dir_}\n错误信息: {e}\n")
                        continue

                out_ext = '.' + target_format.lower()
                out_path = os.path.join(dir_, base + out_ext)

                input_ext = os.path.splitext(fpath)[1].lower() # 获取输入文件扩展名

                if not is_subtitle_file(fpath):
                    self.log_signal.emit(f"[跳过] 非字幕文件: {fpath}\n")
                    continue

                success = False # 默认失败
                error_msg = ""

                # 根据 目标格式 和 输入格式 选择转换方式 (更清晰的 if/elif/else 结构)
                if target_format == 'lrc': #  ========= 目标格式是 LRC  =========
                    if input_ext == '.lrc':
                        self.log_signal.emit(f"[跳过] 同是 LRC，不需要转换: {fpath}\n")
                        continue
                    elif input_ext == '.srt':
                        success, error_msg = srt_to_lrc(fpath, out_path)
                    elif input_ext == '.vtt':
                        success, error_msg = vtt_to_lrc(fpath, out_path)
                    elif input_ext in ['.ass', '.ssa']:
                        # ASS/SSA -> LRC: 先转 SRT 中间格式，再 SRT -> LRC
                        temp_srt_path = os.path.join(dir_, base + '_temp.srt')
                        ok_ffmpeg, error_msg_ffmpeg = ffmpeg_subtitle_convert(fpath, temp_srt_path)
                        if ok_ffmpeg:
                            success, error_msg = srt_to_lrc(temp_srt_path, out_path)
                            if os.path.exists(temp_srt_path):
                                os.remove(temp_srt_path)
                            if not success:
                                error_msg = error_msg
                        else:
                            success = False
                            error_msg = error_msg_ffmpeg
                    else:
                        error_msg = f"不支持的输入字幕格式转 LRC: {input_ext}"

                elif target_format == 'srt': # ========= 目标格式是 SRT =========
                    if input_ext == '.srt':
                        self.log_signal.emit(f"[跳过] 同是 SRT，不需要转换: {fpath}\n")
                        continue
                    elif input_ext == '.lrc':
                        success, error_msg = lrc_to_srt(fpath, out_path)
                    elif input_ext in ['.vtt', '.ass', '.ssa']:
                        success, error_msg = ffmpeg_subtitle_convert(fpath, out_path)
                    else:
                        error_msg = f"不支持的输入字幕格式转 SRT: {input_ext}"

                elif target_format == 'vtt': # ========= 目标格式是 VTT =========
                    if input_ext == '.vtt':
                        self.log_signal.emit(f"[跳过] 同是 VTT，不需要转换: {fpath}\n")
                        continue
                    elif input_ext == '.lrc':
                        success, error_msg = lrc_to_vtt(fpath, out_path)
                    elif input_ext in ['.srt', '.ass', '.ssa']:
                        success, error_msg = ffmpeg_subtitle_convert(fpath, out_path)
                    else:
                        error_msg = f"不支持的输入字幕格式转 VTT: {input_ext}"

                elif target_format == 'ass': # ========= 目标格式是 ASS =========
                    if input_ext == '.ass':
                        self.log_signal.emit(f"[跳过] 同是 ASS，不需要转换: {fpath}\n")
                        continue
                    elif input_ext in ['.srt', '.vtt', '.ssa']: # LRC 没法直接转 ASS, 跳过或提示
                        success, error_msg = ffmpeg_subtitle_convert(fpath, out_path)
                    elif input_ext == '.lrc':
                        error_msg = "LRC 无法直接转换为 ASS 格式，请先转换为 SRT 或 VTT 再试。" # 更明确的提示
                    else:
                        error_msg = f"不支持的输入字幕格式转 ASS: {input_ext}"

                elif target_format == 'ssa': # ========= 目标格式是 SSA =========
                    if input_ext == '.ssa':
                        self.log_signal.emit(f"[跳过] 同是 SSA，不需要转换: {fpath}\n")
                        continue
                    elif input_ext in ['.srt', '.vtt', '.ass']: # LRC 没法直接转 SSA
                        success, error_msg = ffmpeg_subtitle_convert(fpath, out_path)
                    elif input_ext == '.lrc':
                        error_msg = "LRC 无法直接转换为 SSA 格式，请先转换为 SRT 或 VTT 再试。" # 更明确的提示
                    else:
                        error_msg = f"不支持的输入字幕格式转 SSA: {input_ext}"

                else: #  ========= 未知的目标格式 =========
                    error_msg = f"未知的目标字幕格式: {target_format}"

                if success:
                    self.log_signal.emit(f"[OK] 字幕转换成功: {out_path}\n")
                else:
                    self.log_signal.emit(f"[失败] 字幕转换失败: {fpath}\n错误信息: {error_msg}\n")

                # 更新进度
                prog = int((i / total) * 100)
                self.progress_signal.emit(prog)

            self.log_signal.emit("全部处理完成。\n")
            self.progress_signal.emit(100)
            self.finished_signal.emit()
            return # 确保字幕转换分支正确退出

        # 音频/视频转换逻辑 (不变)
        else: # 音频或视频转换
            if total == 0:
                self.error_signal.emit("没有文件可转换！")
                return

            self.log_signal.emit(f"开始转换 - {self.target_format}...\n")
            for i, fpath in enumerate(self.file_list, start=1):
                if not self._running:
                    self.log_signal.emit("用户取消了任务。\n")
                    return

                if not os.path.exists(fpath):
                    self.log_signal.emit(f"[失败] 文件不存在: {fpath}\n")
                    continue

                base = os.path.splitext(os.path.basename(fpath))[0]
                dir_ = self.output_path if self.output_path else os.path.dirname(fpath)

                # 确保输出目录存在
                if not os.path.exists(dir_):
                    try:
                        os.makedirs(dir_)
                    except Exception as e:
                        self.log_signal.emit(f"[失败] 创建输出目录失败: {dir_}\n错误信息: {e}\n")
                        continue

                # 音频/视频 转换逻辑 (保持不变)
                # ... (使用 ffmpeg_convert_cmd 和 run_ffmpeg_with_progress)
                if is_lrc_file(fpath):
                    self.log_signal.emit(f"[跳过] LRC 无法转到 {self.target_format}\n")
                    continue

                # 统一用 ffmpeg_convert
                out_path = os.path.join(dir_, base + '.' + self.target_format)
                cmd = self.ffmpeg_convert_cmd(fpath, out_path, use_hw_accel=self.use_hw_accel) # 获取命令 # 获取命令

                duration = get_media_duration(fpath) # 尝试获取视频时长，音频可能获取不到
                if duration is None:
                    duration = 1.0 # 避免除以零，即使音频时长未知，也能运行

                ok, error_msg = self.run_ffmpeg_with_progress(cmd, duration) # 执行命令并显示进度

                if ok:
                    self.log_signal.emit(f"[OK] 转换完成: {out_path}\n")
                else:
                    self.log_signal.emit(f"[失败] 转换失败: {fpath}\n错误信息: {error_msg}\n")

                # 更新进度
                prog = int((i / total) * 100)
                self.progress_signal.emit(prog)

            self.log_signal.emit("全部处理完成。\n")
            self.progress_signal.emit(100)
            self.finished_signal.emit()

    def stop(self):
        self._running = False

    def ffmpeg_convert_cmd(self, input_path: str, output_path: str, use_hw_accel=False):
        """生成 ffmpeg_convert 的命令列表，方便外部调用和复用"""
        output_ext = os.path.splitext(output_path)[1].lower()

        # 音频编码参数
        audio_params = {
            '.mp3': ['-c:a', 'libmp3lame', '-b:a', '320k'],
            '.flac': ['-c:a', 'flac', '-compression_level', '12'],
            '.aac': ['-c:a', 'aac', '-b:a', '256k'],
            '.opus': ['-c:a', 'libopus', '-b:a', '128k', '-vbr', 'on'],
            '.wav': ['-c:a', 'pcm_s16le'],
            '.ogg': ['-c:a', 'libvorbis', '-q:a', '6']
        }

        # 视频编码参数 (软件编码)
        video_params_sw = {
            '.mp4': ['-c:v', 'libx264', '-preset', 'medium', '-crf', '23'],
            '.mkv': ['-c:v', 'libx265', '-preset', 'fast', '-crf', '28'],
            '.mov': ['-c:v', 'prores_ks', '-profile:v', '3'],  # ProRes for MOV
            '.avi': ['-c:v', 'mpeg4', '-qscale:v', '5'],  # MPEG4 for AVI
            '.flv': ['-c:v', 'flv1'],  # FLV1 for FLV
            '.wmv': ['-c:v', 'wmv2'],  # WMV2 for WMV
            '.webm': ['-c:v', 'libvpx-vp9', '-b:v', '2M'],  # VP9 for WebM
            '.ts': ['-c:v', 'libx264', '-preset', 'fast', '-crf', '25', '-muxer', 'mpegts'],  # H.264 in MPEG-TS
            '.rmvb': ['-c:v', 'librmvb', '-qscale:v', '5']  # librmvb for RMVB (需要安装)
        }

        # 视频编码参数 (硬件加速) - macOS VideoToolbox
        video_params_hw_macOS = {
            '.mp4': ['-c:v', 'h264_videotoolbox', '-b:v', '10M', '-allow_sw', '1'],  # H.264 编码，兼容性更好
            '.mov': ['-c:v', 'prores_videotoolbox', '-profile:v', '3'],  # ProRes 编码
            '.mkv': ['-c:v', 'hevc_videotoolbox', '-b:v', '10M', '-allow_sw', '1'],  # HEVC (H.265) 编码，更高压缩率
            '.avi': ['-c:v', 'h264_videotoolbox', '-b:v', '10M'],  # AVI 格式使用 H.264 编码
            '.flv': ['-c:v', 'h264_videotoolbox', '-b:v', '10M'],  # FLV 格式使用 H.264 编码
            '.webm': ['-c:v', 'libvpx-vp9'],  # WebM 格式仍然使用软件编码 (VP9)
            '.ts': ['-c:v', 'h264_videotoolbox', '-b:v', '10M', '-muxer', 'mpegts'],  # TS 格式使用 H.264 编码
            '.rmvb': ['-c:v', 'librmvb']  # RMVB 格式无硬件加速，继续使用软件编码
        }

        # 根据平台选择硬件加速参数
        hw_accel_args = []
        if use_hw_accel and sys.platform == "darwin":  # macOS
            hw_accel_args = ['-hwaccel', 'videotoolbox']
            video_params = video_params_hw_macOS
        else:
            video_params = video_params_sw

        base_cmd = [ffmpeg_executable, '-y'] + hw_accel_args + ['-i', input_path] # 硬件加速参数放在 -i 前面

        # 根据输出格式判断处理方式
        if is_video_file(output_path):
            # 视频转换保留音视频流, 默认音频转码为 AAC
            base_cmd.extend([
                '-c:a', 'aac', '-b:a', '192k',  # 音频编码
                '-map_metadata', '-1',  # 清除元数据
                '-movflags', '+faststart',  # MP4 优化
                '-sn', '-dn'  # 移除字幕和data流
            ])
            # 添加视频编码参数
            if output_ext in video_params:
                base_cmd.extend(video_params[output_ext])
            else:
                base_cmd.extend(['-c:v', 'copy'])  # 默认视频 copy (不转码)

        else:
            # 音频转换禁用视频流
            base_cmd.extend(['-vn', '-sn', '-dn', '-map_metadata', '-1'])
            # 添加音频编码参数
            if output_ext in audio_params:
                base_cmd.extend(audio_params[output_ext])
            else:
                base_cmd.extend(['-c:a', 'copy'])  # 默认音频 copy (不转码)

        base_cmd.append(output_path)
        return base_cmd

    def ffmpeg_burn_subtitle_cmd(self, video_path: str, sub_path: str, output_path: str,
                         hardcode=True, output_format='mp4', use_hw_accel=False):
        """生成 ffmpeg_burn_subtitle 的命令列表"""
        hw_accel_args = []
        if use_hw_accel and sys.platform == "darwin": # macOS 硬件加速硬编码
            hw_accel_args = ['-hwaccel', 'videotoolbox']

        # 样式注入
        styled_sub = inject_ass_style(sub_path)
        need_cleanup = styled_sub != sub_path # 实际上这里没用上 need_cleanup，因为cmd执行完后，cleanup是在ffmpeg_burn_subtitle中finally执行的

        # 硬编码参数优化
        if hardcode:
            cmd = [
                ffmpeg_executable, '-y',
            ] + hw_accel_args + [ # 硬件加速参数放在全局选项后，输入文件前
                '-i', video_path,
                '-vf', f'subtitles={styled_sub}:force_style=FontName=Arial,',  # 强制中文字体 + 应用样式
            ]
            if use_hw_accel and sys.platform == "darwin":  # macOS 硬件加速硬编码
                cmd.extend([
                    '-c:v', 'h264_videotoolbox', '-b:v', '10M',  # 视频硬件编码，使用 H.264
                    '-c:a', 'aac', '-b:a', '192k',  # 音频编码
                    output_path
                ])
            else:  # 默认软件编码硬编码
                cmd.extend([
                    '-c:v', 'libx264',
                    '-preset', 'fast',
                    '-crf', '23',
                    '-c:a', 'aac',
                    '-b:a', '192k',
                    output_path
                ])

        else:  # 软封装
            cmd = [
                ffmpeg_executable,
                '-y',
                '-i', video_path,
                '-i', styled_sub,
                '-map', '0',  # 映射所有输入流 (视频+音频)
                '-map', '1',  # 映射字幕流
                '-c', 'copy',  # 视频和音频流都直接复制, 软封装不转码
                '-c:s', 'ass',  # 软封装必须使用 ass 才能保证样式
                '-metadata:s:s:0', 'language=chi',  # 字幕语言 metadata
                output_path
            ]
        return cmd

    def run_ffmpeg_with_progress(self, cmd, duration):
        """执行 FFmpeg 命令并实时更新进度"""
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, # 关键: 将 stderr 重定向到 stdout
            universal_newlines=True,
            encoding='utf-8',
            errors='replace'
        )

        time_pattern = re.compile(r"time=(\d+):(\d+):(\d+\.\d+)")

        while True:
            line = process.stdout.readline()
            if not line:
                break
            if "time=" in line:
                match = time_pattern.search(line)
                if match:
                    time_str = f"{match.group(1)}:{match.group(2)}:{match.group(3).split('.')[0]}" # hh:mm:ss
                    current_time_sec = (int(match.group(1)) * 3600 + int(match.group(2)) * 60 + float(match.group(3)))
                    progress = int(min(100, (current_time_sec / duration) * 100)) # 限制最大 100%
                    self.progress_signal.emit(progress)
                    self.time_signal.emit(time_str)  # 发射实时时间信号
                    self.log_signal.emit(line.strip()) # 输出 FFmpeg 日志信息

        process.wait() # 等待进程结束
        if process.returncode != 0:
            return False, "FFmpeg 运行出错，请检查日志。"
        return True, ""

def get_media_duration(filepath):
    """使用 ffprobe 获取媒体文件时长 (秒)"""
    try:
        cmd = [
            ffprobe_executable,
            '-v', 'error',
            '-show_entries', 'format=duration',
            '-of', 'default=noprint_wrappers=1:nokey=1',
            filepath
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='ignore')
        if result.returncode == 0:
            duration_str = result.stdout.strip()
            try:
                return float(duration_str)
            except ValueError:
                return None
        else:
            return None
    except Exception:
        return None

# ==============================================
# 设置对话框
# ==============================================

class SettingsDialog(QDialog):
    """
    用于设置背景图路径、透明度、字体大小、默认输出文件路径等
    """
    hw_accel_changed_signal = pyqtSignal(bool)  # 定义硬件加速设置更改的信号

    def __init__(self, parent, settings):
        super(SettingsDialog, self).__init__(parent)
        self.settings = settings
        self.setWindowTitle("设置")
        self.resize(420, 380)  # 稍微增加高度

        # 读取现有设置
        self.bg_path = self.settings.value("bg_path", "", type=str)
        self.bg_alpha = self.settings.value("bg_alpha", 70, type=int)
        self.theme_mode = self.settings.value("theme_mode", "Dark", type=str)
        self.font_size = self.settings.value("font_size", 10, type=int)
        self.output_path = self.settings.value("output_path", "", type=str)
        self.use_hw_accel = self.settings.value("use_hw_accel", False, type=bool)  # 新增硬件加速设置

        # 布局
        layout = QFormLayout(self)

        # 背景图
        self.bg_path_edit = QLineEdit(self.bg_path, self)
        btn_browse_bg = QPushButton("浏览")
        btn_browse_bg.clicked.connect(self.on_browse_bg)
        bg_layout = QHBoxLayout()
        bg_layout.addWidget(self.bg_path_edit)
        bg_layout.addWidget(btn_browse_bg)
        layout.addRow("背景图路径:", bg_layout)

        # 背景透明度
        self.bg_alpha_slider = QSlider(Qt.Horizontal, self)
        self.bg_alpha_slider.setRange(0, 100)
        self.bg_alpha_slider.setValue(self.bg_alpha)
        self.bg_alpha_slider.valueChanged.connect(self.on_slider_changed)
        self.label_alpha_val = QLabel(f"{self.bg_alpha} %", self)
        alpha_layout = QHBoxLayout()
        alpha_layout.addWidget(self.bg_alpha_slider)
        alpha_layout.addWidget(self.label_alpha_val)
        layout.addRow("背景透明度:", alpha_layout)

        # 主题模式
        self.theme_combo = QComboBox(self)
        self.theme_combo.addItems(["Dark", "Light"])
        if self.theme_mode == "Light":
            self.theme_combo.setCurrentIndex(1)
        layout.addRow("主题模式:", self.theme_combo)

        # 字体大小
        self.spin_font_size = QSpinBox(self)
        self.spin_font_size.setRange(8, 36)
        self.spin_font_size.setValue(self.font_size)
        layout.addRow("字体大小:", self.spin_font_size)

        # 默认输出文件路径
        self.edit_output_path = QLineEdit(self.output_path, self)
        btn_browse_output = QPushButton("选择文件夹")
        btn_browse_output.clicked.connect(self.on_browse_output)
        output_layout = QHBoxLayout()
        output_layout.addWidget(self.edit_output_path)
        output_layout.addWidget(btn_browse_output)
        layout.addRow("默认输出文件路径:", output_layout)

        # 硬件加速选项
        self.check_hw_accel = QCheckBox("启用 GPU 硬件加速 (macOS VideoToolbox)")  # macOS 提示
        self.check_hw_accel.setChecked(self.use_hw_accel)
        layout.addRow("硬件加速:", self.check_hw_accel)

        # 按钮行
        btn_layout = QHBoxLayout()
        btn_save = QPushButton("保存")
        btn_cancel = QPushButton("取消")
        btn_layout.addStretch()
        btn_layout.addWidget(btn_save)
        btn_layout.addWidget(btn_cancel)
        layout.addRow(btn_layout)

        btn_save.clicked.connect(self.on_save)
        btn_cancel.clicked.connect(self.reject)

    def on_browse_bg(self):
        file_filter = "图片文件 (*.png *.jpg *.jpeg *.bmp *.gif);;所有文件 (*)"
        path, _ = QFileDialog.getOpenFileNames(self, "选择背景图片", "", file_filter)
        if path:
            self.bg_path_edit.setText(path)

    def on_browse_output(self):
        path = QFileDialog.getExistingDirectory(self, "选择默认输出文件路径", "")
        if path:
            self.edit_output_path.setText(path)

    def on_slider_changed(self, value):
        self.label_alpha_val.setText(f"{value} %")

    def on_save(self):
        self.bg_path = self.bg_path_edit.text().strip()
        self.bg_alpha = self.bg_alpha_slider.value()
        self.theme_mode = self.theme_combo.currentText()
        self.font_size = self.spin_font_size.value()
        self.output_path = self.edit_output_path.text().strip()
        self.use_hw_accel = self.check_hw_accel.isChecked()  # 保存硬件加速设置

        self.settings.setValue("bg_path", self.bg_path)
        self.settings.setValue("bg_alpha", self.bg_alpha)
        self.settings.setValue("theme_mode", self.theme_mode)
        self.settings.setValue("font_size", self.font_size)
        self.settings.setValue("output_path", self.output_path)
        self.settings.setValue("use_hw_accel", self.use_hw_accel)  # 保存硬件加速设置

        self.hw_accel_changed_signal.emit(self.use_hw_accel)  # 发射硬件加速更改信号
        self.accept()

# ==============================================
# 主窗口
# ==============================================

class ConverterMainWindow(QMainWindow):
    """
    Main Window for 多合一音视频字幕转换器 (分页增强版 - GPU 加速) - 实时进度增强版 - 右键菜单增强版
    """

    def __init__(self):
        super().__init__()
        self.setWindowTitle("盐酸转换UI - 分页增强版 (GPU 加速 - 实时进度)")  # 标题更新
        self.resize(1920, 1080)

        # 设置应用图标（若有 icon.ico）
        icon_path = resource_path("resources/favicon.ico")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        # 读取/创建 settings (同目录下的 converter_config.ini)
        exe_dir = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.abspath(".")
        self.config_file_path = os.path.join(exe_dir, "converter_config.ini")
        self.settings = QSettings(self.config_file_path, QSettings.IniFormat)
        self.settings.setFallbacksEnabled(False)

        # 若第一次运行, 填写默认配置
        if not os.path.exists(self.config_file_path):
            self.settings.setValue("bg_path", resource_path("resources/default_bg.png"))
            self.settings.setValue("bg_alpha", 70)
            self.settings.setValue("theme_mode", "Dark")
            self.settings.setValue("font_size", 10)
            self.settings.setValue("use_hw_accel", False)  # 默认禁用硬件加速
            # 默认输出文件路径 = 程序当前目录下的 output 文件夹
            default_output_folder = os.path.join(exe_dir, "output")
            self.settings.setValue("output_path", default_output_folder)

        # 下载历史记录文件 (同目录下）
        self.history_file_path = os.path.join(exe_dir, "download_history.json")

        # 初始化UI
        self.init_ui()

        # 加载设置并应用主题/背景
        self.apply_settings()

        self.current_worker_thread = None  # 用于跟踪当前工作线程
        self.use_hw_accel = self.settings.value("use_hw_accel", False, type=bool)  # 初始化时读取硬件加速设置

    def init_ui(self):
        # 主容器
        self.main_widget = QWidget(self)
        self.setCentralWidget(self.main_widget)

        main_layout = QVBoxLayout(self.main_widget)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)

        # ======= 顶部工具栏（设置按钮） =======
        top_bar = QHBoxLayout()
        self.btn_settings = QToolButton()
        self.btn_settings.setText("设置")
        self.btn_settings.clicked.connect(self.on_open_settings)
        top_bar.addWidget(self.btn_settings)

        top_bar.addStretch()

        main_layout.addLayout(top_bar)

        # ======= 分页容器 =======
        self.tabs = QTabWidget()

        # === 音频转换 Tab ===
        self.audio_tab = QWidget()
        self.setup_audio_tab_ui(self.audio_tab)
        self.tabs.addTab(self.audio_tab, "音频转换")
        self.audio_tab_index = 0 # 记录音频 Tab 的索引

        # === 视频转换 Tab ===
        self.video_tab = QWidget()
        self.setup_video_tab_ui(self.video_tab)
        self.tabs.addTab(self.video_tab, "视频转换")
        self.video_tab_index = 1 # 记录视频 Tab 的索引

        # === 字幕转换 Tab ===
        self.subtitle_tab = QWidget()
        self.setup_subtitle_tab_ui(self.subtitle_tab)
        self.tabs.addTab(self.subtitle_tab, "字幕转换")
        self.subtitle_tab_index = 2 # 记录字幕 Tab 的索引

        # === 字幕烧录 Tab ===
        self.burn_tab = QWidget()
        self.setup_burn_tab_ui(self.burn_tab)
        self.tabs.addTab(self.burn_tab, "字幕烧录")
        self.burn_tab_index = 3 # 记录烧录 Tab 的索引

        main_layout.addWidget(self.tabs)

        # ======= 日志输出 + 进度条 (所有 Tab 共用) =======
        self.log_display = QPlainTextEdit()
        self.log_display.setReadOnly(True)
        self.log_display.setPlaceholderText("日志输出...")
        main_layout.addWidget(self.log_display, stretch=2)

        progress_layout = QHBoxLayout() # 进度条和时间放一行
        self.progress_bar = QProgressBar()
        progress_layout.addWidget(self.progress_bar)
        self.time_label = QLabel("00:00:00") # 实时时间标签
        progress_layout.addWidget(self.time_label)
        main_layout.addLayout(progress_layout)


        # ======= 底部按钮 (所有 Tab 共用) =======
        bottom_btn_layout = QHBoxLayout()
        self.btn_start = QPushButton("开始")
        self.btn_cancel = QPushButton("取消")
        self.btn_close = QPushButton("关闭")
        self.btn_cancel.setEnabled(False)
        bottom_btn_layout.addWidget(self.btn_start)
        bottom_btn_layout.addWidget(self.btn_cancel)
        bottom_btn_layout.addWidget(self.btn_close)
        main_layout.addLayout(bottom_btn_layout)

        # ======= 底部 “染” 标识 =======
        bottom_signature_layout = QHBoxLayout()
        bottom_signature_layout.addStretch()
        self.label_signature = QLabel("染")
        self.label_signature.setStyleSheet("font-size: 10px; color: #888888;")
        bottom_signature_layout.addWidget(self.label_signature)
        main_layout.addLayout(bottom_signature_layout)

        # ======= 信号槽 (通用按钮) =======
        self.btn_start.clicked.connect(self.on_start_conversion)  # 统一的开始按钮
        self.btn_cancel.clicked.connect(self.on_cancel_conversion)  # 统一的取消按钮
        self.btn_close.clicked.connect(self.close)

    def setup_audio_tab_ui(self, tab_widget):
        """设置音频转换 Tab UI"""
        audio_layout = QVBoxLayout(tab_widget)

        # 输出格式选择
        self.audio_label_format = QLabel("选择音频输出格式")
        self.audio_combo_format = QComboBox()
        audio_formats = ['mp3', 'wav', 'flac', 'aac', 'ogg', 'opus']
        self.audio_combo_format.addItems(audio_formats)
        audio_layout.addWidget(self.audio_label_format)
        audio_layout.addWidget(self.audio_combo_format)

        # 文件列表
        self.audio_label_file_list = QLabel("待转换音频文件")
        self.audio_list_files = FileListWidget()
        audio_layout.addWidget(self.audio_label_file_list)
        audio_layout.addWidget(self.audio_list_files, stretch=1)

        # 按钮：添加、移除
        audio_btn_layout = QHBoxLayout()
        self.audio_btn_add_file = QPushButton("添加音频文件")
        self.audio_btn_remove_file = QPushButton("移除选中")
        audio_btn_layout.addWidget(self.audio_btn_add_file)
        audio_btn_layout.addWidget(self.audio_btn_remove_file)
        audio_layout.addLayout(audio_btn_layout)

        # 信号槽 (音频 Tab 专属按钮)
        self.audio_btn_add_file.clicked.connect(lambda: self.on_add_file(self.audio_list_files))
        self.audio_btn_remove_file.clicked.connect(lambda: self.on_remove_file(self.audio_list_files))

    def setup_video_tab_ui(self, tab_widget):
        """设置视频转换 Tab UI"""
        video_layout = QVBoxLayout(tab_widget)

        # 输出格式选择
        self.video_label_format = QLabel("选择视频输出格式")
        self.video_combo_format = QComboBox()
        video_formats = ['mp4', 'mkv', 'mov', 'avi', 'flv', 'wmv', 'webm', 'ts', 'rmvb']  # 视频格式, 增加 rmvb
        self.video_combo_format.addItems(video_formats)
        video_layout.addWidget(self.video_label_format)
        video_layout.addWidget(self.video_combo_format)

        # 文件列表
        self.video_label_file_list = QLabel("待转换视频文件")
        self.video_list_files = FileListWidget()
        video_layout.addWidget(self.video_label_file_list)
        video_layout.addWidget(self.video_list_files, stretch=1)

        # 复选框：是否合并音视频
        self.video_check_merge = QCheckBox("是否合并音视频？(仅合并第一个音频和视频文件)")
        video_layout.addWidget(self.video_check_merge)

        # 按钮：添加、移除
        video_btn_layout = QHBoxLayout()
        self.video_btn_add_file = QPushButton("添加视频文件")
        self.video_btn_remove_file = QPushButton("移除选中")
        video_btn_layout.addWidget(self.video_btn_add_file)
        video_btn_layout.addWidget(self.video_btn_remove_file)
        video_layout.addLayout(video_btn_layout)

        # 信号槽 (视频 Tab 专属按钮)
        self.video_btn_add_file.clicked.connect(lambda: self.on_add_file(self.video_list_files))
        self.video_btn_remove_file.clicked.connect(lambda: self.on_remove_file(self.video_list_files))

    def setup_subtitle_tab_ui(self, tab_widget):
        """设置字幕转换 Tab UI"""
        subtitle_layout = QVBoxLayout(tab_widget)

        # 输出格式选择
        self.subtitle_label_format = QLabel("选择目标字幕格式")
        self.subtitle_combo_format = QComboBox()
        subtitle_formats = ['lrc', 'srt', 'vtt', 'ass', 'ssa'] # 直接列出目标格式 (增加 ssa)
        self.subtitle_combo_format.addItems(subtitle_formats)
        subtitle_layout.addWidget(self.subtitle_label_format)
        subtitle_layout.addWidget(self.subtitle_combo_format)

        # 文件列表
        self.subtitle_label_file_list = QLabel("待转换字幕文件")
        self.subtitle_list_files = FileListWidget()
        subtitle_layout.addWidget(self.subtitle_label_file_list)
        subtitle_layout.addWidget(self.subtitle_list_files, stretch=1)

        # 按钮：添加、移除
        subtitle_btn_layout = QHBoxLayout()
        self.subtitle_btn_add_file = QPushButton("添加字幕文件")
        self.subtitle_btn_remove_file = QPushButton("移除选中")
        subtitle_btn_layout.addWidget(self.subtitle_btn_add_file)
        subtitle_btn_layout.addWidget(self.subtitle_btn_remove_file)
        subtitle_layout.addLayout(subtitle_btn_layout)

        # 信号槽 (字幕 Tab 专属按钮)
        self.subtitle_btn_add_file.clicked.connect(lambda: self.on_add_file(self.subtitle_list_files))
        self.subtitle_btn_remove_file.clicked.connect(lambda: self.on_remove_file(self.subtitle_list_files))

    def setup_burn_tab_ui(self, tab_widget):
        """设置字幕烧录 Tab UI"""
        burn_layout = QVBoxLayout(tab_widget)

        # 视频文件选择
        self.burn_label_video_file = QLabel("选择视频文件")
        self.burn_video_list_files = FileListWidget()
        burn_layout.addWidget(self.burn_label_video_file)
        burn_layout.addWidget(self.burn_video_list_files)

        # 字幕文件选择
        self.burn_label_subtitle_file = QLabel("选择字幕文件")
        self.burn_subtitle_list_files = FileListWidget()
        burn_layout.addWidget(self.burn_label_subtitle_file)
        burn_layout.addWidget(self.burn_subtitle_list_files)

        # 烧录模式选择
        self.burn_label_mode = QLabel("选择烧录模式")
        self.burn_combo_mode = QComboBox()
        self.burn_combo_mode.addItems(["硬编码", "软封装 (若支持)"])  # 增加软封装的说明
        burn_layout.addWidget(self.burn_label_mode)
        burn_layout.addWidget(self.burn_combo_mode)

        # 输出格式选择 (仅软封装时有效)
        self.burn_label_output_format = QLabel("选择输出格式 (仅软封装)")
        self.burn_combo_output_format = QComboBox()
        burn_video_formats = ['mp4', 'mkv']  # 烧录软封装主要支持 mp4 和 mkv
        self.burn_combo_output_format.addItems(burn_video_formats)
        burn_layout.addWidget(self.burn_label_output_format)
        burn_layout.addWidget(self.burn_combo_output_format)
        self.burn_combo_output_format.setCurrentText('mkv') # 软封装默认 MKV

        # 增加状态提示标签
        self.burn_status_label = QLabel("状态提示：")
        self.burn_hint_label = QLabel("硬编码 - 字幕永久嵌入视频，兼容性好；软封装 - 字幕可开关，文件小，但仅 MP4/MKV 且需 SRT 字幕")
        burn_layout.addWidget(self.burn_status_label)
        burn_layout.addWidget(self.burn_hint_label)

        # 按钮：添加视频, 添加字幕, 移除视频, 移除字幕
        burn_btn_layout = QHBoxLayout()
        self.burn_btn_add_video = QPushButton("添加视频")
        self.burn_btn_add_subtitle = QPushButton("添加字幕")
        self.burn_btn_remove_video = QPushButton("移除视频")
        self.burn_btn_remove_subtitle = QPushButton("移除字幕")
        burn_btn_layout.addWidget(self.burn_btn_add_video)
        burn_btn_layout.addWidget(self.burn_btn_add_subtitle)
        burn_btn_layout.addWidget(self.burn_btn_remove_video)
        burn_btn_layout.addWidget(self.burn_btn_remove_subtitle)
        burn_layout.addLayout(burn_btn_layout)

        # 信号槽 (烧录 Tab 专属按钮)
        self.burn_btn_add_video.clicked.connect(lambda: self.on_add_file(self.burn_video_list_files))
        self.burn_btn_add_subtitle.clicked.connect(lambda: self.on_add_file(self.burn_subtitle_list_files))
        self.burn_btn_remove_video.clicked.connect(lambda: self.on_remove_file(self.burn_video_list_files))
        self.burn_btn_remove_subtitle.clicked.connect(lambda: self.on_remove_file(self.burn_subtitle_list_files))
        self.burn_combo_mode.currentTextChanged.connect(self.update_burn_hint)  # 模式切换时更新提示

    def update_burn_hint(self, mode_text):
        """更新字幕烧录 Tab 的提示信息"""
        if "硬编码" in mode_text:
            self.burn_hint_label.setText("硬编码 - 字幕将永久嵌入视频画面，所有格式兼容性好")
            self.burn_label_output_format.setEnabled(False)  # 硬编码时禁用输出格式选择
            self.burn_combo_output_format.setEnabled(False)
        else:
            self.burn_hint_label.setText("软封装 - 字幕可开关，文件体积小，但仅支持 MP4/MKV 格式，推荐使用 SRT 字幕")
            self.burn_label_output_format.setEnabled(True)  # 软封装时启用输出格式选择
            self.burn_combo_output_format.setEnabled(True)

    # ========== 通用按钮操作 (所有 Tab 共用) ==========
    def on_start_conversion(self):
        current_tab_index = self.tabs.currentIndex()
        if current_tab_index == 0:  # 音频转换 Tab
            self.start_audio_conversion()
        elif current_tab_index == 1:  # 视频转换 Tab
            self.start_video_conversion()
        elif current_tab_index == 2:  # 字幕转换 Tab
            self.start_subtitle_conversion()
        elif current_tab_index == 3:  # 字幕烧录 Tab
            self.start_burn_subtitle()

    def on_cancel_conversion(self):
        if self.current_worker_thread and self.current_worker_thread.isRunning():
            reply = QMessageBox.question(self, "确认", "确定要取消当前任务吗？", QMessageBox.Yes | QMessageBox.No,
                                         QMessageBox.No)
            if reply == QMessageBox.Yes:
                self.current_worker_thread.stop()
                self.log_display.appendPlainText("已请求取消任务...\n")
        else:
            self.log_display.appendPlainText("当前无任务在进行。\n")

    # ========== Tab 页面专属的开始转换逻辑 ==========

    def start_audio_conversion(self):
        if self.current_worker_thread and self.current_worker_thread.isRunning():
            QMessageBox.information(self, "提示", "当前有任务正在进行，请等待完成或取消。")
            return

        file_list = [self.audio_list_files.item(i).text() for i in range(self.audio_list_files.count())]
        if not file_list:
            QMessageBox.information(self, "提示", "请先添加音频文件。")
            return

        target_format = self.audio_combo_format.currentText()
        self.start_worker(file_list, target_format, tabs_index=self.audio_tab_index, use_hw_accel=False)  # 音频转换不使用硬件加速

    def start_video_conversion(self):
        if self.current_worker_thread and self.current_worker_thread.isRunning():
            QMessageBox.information(self, "提示", "当前有任务正在进行，请等待完成或取消。")
            return

        file_list = [self.video_list_files.item(i).text() for i in range(self.video_list_files.count())]
        if not file_list:
            QMessageBox.information(self, "提示", "请先添加视频文件。")
            return

        target_format = self.video_combo_format.currentText()
        merge_av = self.video_check_merge.isChecked()
        self.start_worker(file_list, target_format, tabs_index=self.video_tab_index, merge_av=merge_av, use_hw_accel=self.use_hw_accel)  # 视频转换传递硬件加速

    def start_subtitle_conversion(self):
        if self.current_worker_thread and self.current_worker_thread.isRunning():
            QMessageBox.information(self, "提示", "当前有任务正在进行，请等待完成或取消。")
            return

        file_list = [self.subtitle_list_files.item(i).text() for i in range(self.subtitle_list_files.count())]
        if not file_list:
            QMessageBox.information(self, "提示", "请先添加字幕文件。")
            return

        target_format = self.subtitle_combo_format.currentText()
        self.start_worker(file_list, target_format, tabs_index=self.subtitle_tab_index, use_hw_accel=False)  # 字幕转换不使用硬件加速

    def start_burn_subtitle(self):
        if self.current_worker_thread and self.current_worker_thread.isRunning():
            QMessageBox.information(self, "提示", "当前有任务正在进行，请等待完成或取消。")
            return

        video_files = [self.burn_video_list_files.item(i).text() for i in range(self.burn_video_list_files.count())]
        subtitle_files = [self.burn_subtitle_list_files.item(i).text() for i in range(self.burn_subtitle_list_files.count())]

        if not video_files or not subtitle_files:
            QMessageBox.information(self, "提示", "请先添加视频文件和字幕文件。")
            return
        if len(video_files) > 1 or len(subtitle_files) > 1:
            QMessageBox.warning(self, "警告", "字幕烧录功能一次仅支持一个视频文件和一个字幕文件。将只处理列表中的第一个文件。")

        video_path = video_files[0]
        subtitle_path = subtitle_files[0]
        burn_mode_text = self.burn_combo_mode.currentText() # 获取用户选择的文本
        burn_hardcode = (burn_mode_text == "硬编码")  # 根据文本判断是否硬编码
        output_format = self.burn_combo_output_format.currentText()

        # TS 格式软封装提示
        if video_path.lower().endswith('.ts') and not burn_hardcode: # 使用布尔值判断
            QMessageBox.warning(self, "格式不支持", "TS 格式不支持软封装字幕，将自动切换为硬编码模式。")
            burn_hardcode = True  # 强制改为硬编码

        burn_options = {
            'video_path': video_path,
            'sub_path': subtitle_path,
            'burn_hardcode': burn_hardcode, # 传递布尔值
            'output_format': output_format
        }

        self.start_worker(file_list=[], target_format="", tabs_index=self.burn_tab_index, burn_subtitle_options=burn_options,
                          use_hw_accel=self.use_hw_accel)  # 传递硬件加速参数

    def start_worker(self, file_list, target_format, tabs_index=0, merge_av=False, burn_subtitle_options=None,
                     use_hw_accel=False):  # 启动 worker 时接收硬件加速参数, 新增 tabs_index
        """启动工作线程"""
        # 获取默认输出路径
        self.output_path = self.settings.value("output_path", "", type=str)
        if not self.output_path:
            exe_dir = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.abspath(".")
            self.output_path = os.path.join(exe_dir, "output")
            self.settings.setValue("output_path", self.output_path)

        # 确保输出目录存在
        if not os.path.exists(self.output_path):
            try:
                os.makedirs(self.output_path)
            except Exception as e:
                QMessageBox.critical(self, "错误", f"无法创建输出目录: {self.output_path}\n{e}")
                return

        # 检查输入文件夹与输出文件夹是否相同 (只针对文件列表转换，烧录不检查)
        if file_list:
            input_dirs = set(os.path.dirname(f) for f in file_list)
            output_dir = self.output_path
            if output_dir in input_dirs:
                QMessageBox.warning(self, "警告", "输出文件夹与输入文件夹相同，可能会导致输出文件被再次处理。请使用不同的输出文件夹。")
                return

        # 开始工作线程
        self.log_display.clear()
        self.progress_bar.setValue(0)
        self.time_label.setText("00:00:00") # 重置时间显示

        self.current_worker_thread = ConvertWorker(
            file_list, target_format, tabs_index=tabs_index, merge_av=merge_av, burn_subtitle_options=burn_subtitle_options,
            use_hw_accel=use_hw_accel  # 传递硬件加速参数
        )
        self.current_worker_thread.progress_signal.connect(self.on_progress_update)
        self.current_worker_thread.log_signal.connect(self.on_log_update)
        self.current_worker_thread.error_signal.connect(self.on_error)
        self.current_worker_thread.finished_signal.connect(self.on_finished)
        self.current_worker_thread.time_signal.connect(self.on_time_update) # 连接时间信号

        self.current_worker_thread.output_path = self.output_path  # 传递输出路径

        self.current_worker_thread.start()

        # 更新按钮状态
        self.btn_start.setEnabled(False)
        self.btn_cancel.setEnabled(True)
        self.btn_close.setEnabled(False)

        self.log_display.appendPlainText("开始任务...\n")

    # ========== 文件列表操作 (所有 Tab 共用) ==========
    def on_add_file(self, file_list_widget):
        files, _ = QFileDialog.getOpenFileNames(self, "选择文件", os.getcwd(), "所有文件 (*)")
        if files:
            for f in files:
                if not self.is_duplicate(f, file_list_widget):
                    file_list_widget.addItem(QListWidgetItem(f))
                else:
                    self.log_display.appendPlainText(f"[提示] 文件已存在列表中: {f}\n")

    def is_duplicate(self, filepath: str, file_list_widget) -> bool:
        """检查文件是否已在列表中"""
        for i in range(file_list_widget.count()):
            if file_list_widget.item(i).text() == filepath:
                return True
        return False

    def on_remove_file(self, file_list_widget):
        for item in file_list_widget.selectedItems():
            file_list_widget.takeItem(file_list_widget.row(item))

    # ========== 信号槽处理 (Worker Thread) ==========
    def on_progress_update(self, val: int):
        self.progress_bar.setValue(val)

    def on_time_update(self, time_str: str):
        """更新实时时间显示"""
        self.time_label.setText(time_str)

    def on_log_update(self, msg: str):
        self.log_display.appendPlainText(msg)
        self.log_display.verticalScrollBar().setValue(self.log_display.verticalScrollBar().maximum())

    def on_error(self, err: str):
        QMessageBox.critical(self, "错误", err)
        self.log_display.appendPlainText(f"[错误] {err}\n")
        self.on_finished()

    def on_finished(self):
        self.log_display.appendPlainText("处理结束。\n")
        self.btn_start.setEnabled(True)
        self.btn_cancel.setEnabled(False)
        self.btn_close.setEnabled(True)
        self.current_worker_thread = None

    # ===============================
    # 打开设置对话框
    # ===============================
    def on_open_settings(self):
        dlg = SettingsDialog(self, self.settings)
        dlg.hw_accel_changed_signal.connect(self.on_hw_accel_changed)  # 连接硬件加速更改信号
        if dlg.exec_() == QDialog.Accepted:
            # 重新应用设置
            self.apply_settings()

    # ===============================
    # 硬件加速设置更改处理
    # ===============================
    def on_hw_accel_changed(self, use_hw_accel: bool):
        """硬件加速设置更改时更新主窗口 use_hw_accel 属性"""
        self.use_hw_accel = use_hw_accel
        self.settings.setValue("use_hw_accel", self.use_hw_accel)  # 同步到 settings

    # ===============================
    # 应用用户设置(背景/主题/字体等)
    # ===============================
    def apply_settings(self):
        # 读取设置
        self.bg_path = self.settings.value("bg_path", "", type=str)
        self.bg_alpha = self.settings.value("bg_alpha", 70, type=int)
        self.theme_mode = self.settings.value("theme_mode", "Dark", type=str)
        self.font_size = self.settings.value("font_size", 10, type=int)
        self.output_path = self.settings.value("output_path", "", type=str)
        self.use_hw_accel = self.settings.value("use_hw_accel", False, type=bool)  # 读取硬件加速设置

        # 设置全局字体大小
        font = QFont()
        font.setPointSize(self.font_size)
        self.setFont(font)

        # 设置主题
        self.apply_theme_qss()

        # 加载背景图
        self.load_background()

        # 触发刷新
        self.update()

    def load_background(self):
        """
        加载背景图 QPixmap
        """
        # 如果配置里有自定义路径，则用它，否则使用默认
        if self.bg_path and os.path.exists(self.bg_path):
            pixmap = QPixmap(self.bg_path)
        else:
            # 若路径无效，尝试使用默认背景
            default_bg = resource_path("resources/default_bg.png")
            if os.path.exists(default_bg):
                pixmap = QPixmap(default_bg)
            else:
                pixmap = QPixmap()  # 空
        if not pixmap.isNull():
            self.bg_pixmap = pixmap
        else:
            self.bg_pixmap = None

    def paintEvent(self, event):
        """
        重写 paintEvent 来绘制背景图
        """
        if hasattr(self, 'bg_pixmap') and self.bg_pixmap:
            painter = QPainter(self)
            painter.setOpacity(self.bg_alpha / 100.0)
            painter.drawPixmap(
                self.rect(),
                self.bg_pixmap.scaled(
                    self.size(),
                    Qt.IgnoreAspectRatio,
                    Qt.SmoothTransformation
                )
            )
            painter.setOpacity(1.0)
        super(ConverterMainWindow, self).paintEvent(event)

    def apply_theme_qss(self):
        """
        简易 QSS 实现 Dark/Light 主题
        """
        if self.theme_mode == "Dark":
            # 深色主题
            qss = """
            QWidget {
                background: transparent;
                color: #FFFFFF;
            }
            QLineEdit, QPlainTextEdit, QListWidget, QComboBox {
                background-color: rgba(0, 0, 0, 150);
                border: 1px solid #666;
                selection-background-color: #555; /* 选中时的背景色 */
                selection-color: #FFF; /* 选中时的文字颜色 */
            }
            QPushButton {
                background-color: rgba(50, 50, 50, 150);
                border: 1px solid #666;
            }
            QPushButton:hover {
                background-color: rgba(80, 80, 80, 150);
            }
            QToolButton {
                background-color: rgba(50, 50, 50, 150);
                border: 1px solid #666;
            }
            QToolButton:hover {
                background-color: rgba(80, 80, 80, 150);
            }

            QProgressBar {
                height: 25px;
                text-align: center;
                color: #FFFFFF;
                background-color: rgba(0, 0, 0, 80);
                border: 2px solid #4CAF50;
                border-radius: 5px;
            }
            QProgressBar::chunk {
                background-color: #4CAF50;
                margin: 0.5px;
            }
            QTabWidget::pane { /* tab 页面背景 */
                background: transparent;
                border: none;
            }
            QTabBar::tab {
                background: rgba(50, 50, 50, 150);
                color: #FFFFFF;
                border: 1px solid #666;
                padding: 8px 20px;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
                margin-right: 2px;
            }

            QTabBar::tab:selected {
                background: rgba(80, 80, 80, 150);
            }

            QTabBar::tab:!selected {
                margin-top: 3px; /* 未选中时略微下沉 */
            }
            QLabel {
                background: transparent;
                color: #FFFFFF;
            }
            """
        else:
            # 浅色主题
            qss = """
            QWidget {
                background: transparent;
                color: #000000;
            }
            QLineEdit, QPlainTextEdit, QListWidget, QComboBox {
                background-color: rgba(255, 255, 255, 200);
                border: 1px solid #CCC;
                selection-background-color: #DDD; /* 选中时的背景色 */
                selection-color: #000; /* 选中时的文字颜色 */
            }
            QPushButton {
                background-color: rgba(230, 230, 230, 200);
                border: 1px solid #CCC;
            }
            QPushButton:hover {
                background-color: rgba(200, 200, 200, 200);
            }
            QToolButton {
                background-color: rgba(230, 230, 230, 200);
                border: 1px solid #CCC;
            }
            QToolButton:hover {
                background-color: rgba(200, 200, 200, 200);
            }

            QProgressBar {
                height: 25px;
                text-align: center;
                color: #000000;
                background-color: rgba(255, 255, 255, 180);
                border: 2px solid #4CAF50;
                border-radius: 5px;
            }
            QProgressBar::chunk {
                background-color: #4CAF50;
                margin: 0.5px;
            }
            QTabWidget::pane { /* tab 页面背景 */
                background: transparent;
                border: none;
            }
            QTabBar::tab {
                background: rgba(230, 230, 230, 200);
                color: #000000;
                border: 1px solid #CCC;
                padding: 8px 20px;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
                margin-right: 2px;
            }

            QTabBar::tab:selected {
                background: rgba(200, 200, 200, 200);
            }

            QTabBar::tab:!selected {
                margin-top: 3px; /* 未选中时略微下沉 */
            }
            QLabel {
                background: transparent;
                color: #000000;
            }
            """
        QApplication.instance().setStyleSheet(qss)

    # ===============================
    # 关闭窗口时检查是否有转换线程
    # ===============================
    def closeEvent(self, event):
        if self.current_worker_thread and self.current_worker_thread.isRunning():
            reply = QMessageBox.question(
                self, '提示', "当前有转换任务进行中，确定要退出吗？",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                self.current_worker_thread.stop()
                self.current_worker_thread.wait()
                event.accept()
            else:
                event.ignore()
        else:
            event.accept()

# ==============================================
# 程序入口
# ==============================================

def main():
    app = QApplication(sys.argv)

    # 检查 ffmpeg 是否安装
    if not check_ffmpeg_installed():
        QMessageBox.critical(None, "FFmpeg 错误",
                             "FFmpeg 未安装或未添加到系统 PATH 环境变量中。\n请安装 FFmpeg 并确保可在命令行中访问。")
        return

    win = ConverterMainWindow()
    win.show()
    sys.exit(app.exec_())

def check_ffmpeg_installed():
    """检查 FFmpeg 是否安装"""
    try:
        subprocess.run([ffmpeg_executable, "-version"], capture_output=True, check=True)
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False

if __name__ == "__main__":
    main()
