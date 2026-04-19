#!/usr/bin/env bash
# -----------------------------------------------------------------------------
# 盐酸转换器 macOS 打包脚本
#
# 用法:
#   scripts/build_macos.sh [options]
#
# Options:
#   --download-ffmpeg   从 evermeet.cx 下载静态 ffmpeg/ffprobe 覆盖 resources/
#                       （需要联网；首次打包或想摆脱 Homebrew 依赖时用）
#   --dmg               打包完成后生成 DMG（需要 hdiutil，macOS 自带）
#   --clean             强制删除旧的虚拟环境再重新创建
#   -h | --help         显示本帮助
# -----------------------------------------------------------------------------
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

DOWNLOAD_FFMPEG=0
MAKE_DMG=0
CLEAN_VENV=0

for arg in "$@"; do
    case "$arg" in
        --download-ffmpeg) DOWNLOAD_FFMPEG=1 ;;
        --dmg)             MAKE_DMG=1 ;;
        --clean)           CLEAN_VENV=1 ;;
        -h|--help)
            sed -n '3,13p' "$0" | sed 's/^# \{0,1\}//'
            exit 0
            ;;
        *)
            echo "未知参数: $arg" >&2
            echo "使用 --help 查看帮助。" >&2
            exit 1
            ;;
    esac
done

# ---- helpers ----------------------------------------------------------------
log() { printf "\033[1;35m[build]\033[0m %s\n" "$*"; }
warn() { printf "\033[1;33m[warn]\033[0m %s\n" "$*" >&2; }
die() { printf "\033[1;31m[error]\033[0m %s\n" "$*" >&2; exit 1; }

# ---- sanity checks ----------------------------------------------------------
if [[ "$(uname -s)" != "Darwin" ]]; then
    die "本脚本只在 macOS 运行。Windows 请用 scripts/build_windows.bat。"
fi

PYTHON="${PYTHON:-}"
if [[ -z "$PYTHON" ]]; then
    if command -v python3 >/dev/null 2>&1; then
        PYTHON="python3"
    elif command -v python >/dev/null 2>&1; then
        PYTHON="python"
    else
        die "找不到 python3。请先安装 Python 3.9+：brew install python@3.11"
    fi
fi

PY_VERSION="$("$PYTHON" -c 'import sys; print("{}.{}".format(*sys.version_info[:2]))')"
log "使用 Python: $PY_VERSION ($PYTHON)"

PY_MAJOR="$(echo "$PY_VERSION" | cut -d. -f1)"
PY_MINOR="$(echo "$PY_VERSION" | cut -d. -f2)"
if [[ "$PY_MAJOR" -lt 3 || ( "$PY_MAJOR" -eq 3 && "$PY_MINOR" -lt 9 ) ]]; then
    die "需要 Python 3.9 或更高版本，当前 $PY_VERSION。"
fi

# ---- virtual env ------------------------------------------------------------
VENV_DIR="$PROJECT_ROOT/.venv-build"
if [[ "$CLEAN_VENV" == "1" && -d "$VENV_DIR" ]]; then
    log "清理旧 venv: $VENV_DIR"
    rm -rf "$VENV_DIR"
fi

if [[ ! -d "$VENV_DIR" ]]; then
    log "创建虚拟环境 $VENV_DIR"
    "$PYTHON" -m venv "$VENV_DIR"
fi

# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

log "升级 pip / setuptools / wheel"
pip install --quiet --upgrade pip setuptools wheel

log "安装运行依赖"
pip install --quiet -r requirements.txt

log "安装 PyInstaller"
pip install --quiet pyinstaller

# ---- optional: download a static ffmpeg -------------------------------------
if [[ "$DOWNLOAD_FFMPEG" == "1" ]]; then
    log "下载静态 ffmpeg / ffprobe (evermeet.cx, 含 libass)"
    TMP_DIR="$(mktemp -d)"
    trap 'rm -rf "$TMP_DIR"' EXIT
    curl -fsSL -o "$TMP_DIR/ffmpeg.zip"  "https://evermeet.cx/ffmpeg/getrelease/zip"
    curl -fsSL -o "$TMP_DIR/ffprobe.zip" "https://evermeet.cx/ffmpeg/getrelease/ffprobe/zip"
    mkdir -p resources
    (cd resources && unzip -oq "$TMP_DIR/ffmpeg.zip" && unzip -oq "$TMP_DIR/ffprobe.zip")
    chmod +x resources/ffmpeg resources/ffprobe
    log "已更新 resources/ffmpeg: $(./resources/ffmpeg -version | head -1)"
fi

# Warn if bundled ffmpeg won't even run on this box.
if [[ -x resources/ffmpeg ]]; then
    if ! ./resources/ffmpeg -version >/dev/null 2>&1; then
        warn "resources/ffmpeg 在本机无法执行（dylib 依赖缺失？）。"
        warn "运行期会自动回退到 PATH 上的 ffmpeg。"
        warn "若要彻底解决，请加 --download-ffmpeg 重跑。"
    fi
fi

# ---- clean previous artifacts -----------------------------------------------
log "清理旧的 build / dist / Main.app"
rm -rf build dist Main.app

# ---- run pyinstaller --------------------------------------------------------
log "开始 PyInstaller 打包"
pyinstaller Main.spec --clean --noconfirm

if [[ ! -d "dist/Main.app" ]]; then
    die "PyInstaller 未生成 dist/Main.app，请检查上面的输出。"
fi

APP_SIZE="$(du -sh dist/Main.app | cut -f1)"
log "打包完成: dist/Main.app ($APP_SIZE)"

# ---- optional: DMG ----------------------------------------------------------
if [[ "$MAKE_DMG" == "1" ]]; then
    DMG_PATH="dist/Convert-$(date +%Y%m%d).dmg"
    log "生成 DMG: $DMG_PATH"
    rm -f "$DMG_PATH"
    hdiutil create -srcfolder dist/Main.app -volname "Convert" \
        -format UDZO -quiet "$DMG_PATH"
    log "DMG 生成完毕: $DMG_PATH ($(du -sh "$DMG_PATH" | cut -f1))"
fi

log "✓ 全部完成。可以直接 'open dist/Main.app' 试运行。"
