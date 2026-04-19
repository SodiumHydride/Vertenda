# 盐酸转换器 · Kurisu Edition

多合一音频 / 视频 / 字幕转换器，带字幕烧录与 macOS GPU 硬件加速。

原来是 2000 行的单文件 PyQt5 项目，现在拆分成清晰的模块，修掉一堆 P0 级的陷阱，套上一层现代化的 UI，并补齐了测试基线。

## 功能

- **音频转换**: mp3 / wav / flac / aac / ogg / opus 互转，使用专业级参数
- **视频转换**: mp4 / mkv / mov / avi / flv / wmv / webm / ts / rmvb 互转
- **视频 → 仅提取音频**: 视频 Tab 下拉里的"仅音频 · MP3 / FLAC / ..."一键剥离
- **字幕转换**: srt / vtt / ass / ssa / lrc 互转（lrc 特殊情况会做多步转换）
- **音视频合并**: 取列表中第一个音频和第一个视频合成
- **字幕烧录**: 硬编码（永久烧入画面）/ 软封装（独立轨道），支持粉色+黑边样式
- **质量预设**: 快速 / 均衡 / 高质量 三档，统一控制 libx264/x265/VideoToolbox/AAC
- **macOS VideoToolbox 硬件加速**: 可在设置中开关
- **真正可取消**: 取消按钮会立即 terminate 子进程，不再是心理安慰
- **实时进度 · 批量显示**: 主进度 / 当前文件内部进度 / ETA / "[3/10] filename.mp4" 状态
- **富格式下拉**: `★ MP3 · 通用有损 · 320 kbps · 兼容性最佳` 式的友好提示
- **记住上次选择**: 每个 Tab 的格式、烧录模式、输出目录自动持久化
- **右键联动**: 视频列表 → "发送到字幕烧录"，少一次拖拽
- **从目录批量添加**: 一次递归扫整个文件夹

## 目录结构

```
Convert/
├── Main.py                      # 薄入口 (<50 行)
├── Main.spec                    # PyInstaller 打包配置
├── requirements.txt
├── converter_config.ini         # 运行时产生，已加入 .gitignore
├── resources/                   # 资源：ffmpeg/ffprobe/icons/default_bg
├── converter/
│   ├── constants.py             # 扩展名、路径常量、分类助手、SettingsKey
│   ├── format_meta.py           # 格式元信息（标签、描述、推荐标记）
│   ├── worker.py                # QThread：任务调度层 + 进度/ETA 信号
│   ├── ffmpeg/
│   │   ├── profiles.py          # 编码器配置（参数化为 QualitySpec）
│   │   ├── quality.py           # QualityPreset 枚举和 QualitySpec
│   │   ├── commands.py          # 命令构造（纯函数）
│   │   ├── probe.py             # ffprobe 工具
│   │   └── runner.py            # 可取消的子进程执行器
│   ├── subtitle/
│   │   ├── timestamps.py        # 秒 ↔ 时间戳（纯函数）
│   │   ├── parsers.py           # 解析 lrc/srt/vtt → Cue
│   │   ├── converters.py        # Cue ↔ 文件
│   │   └── styling.py           # ASS 样式注入（不破坏源文件）
│   └── ui/
│       ├── main_window.py       # 主窗口 + overlay 绘制 + 持久化
│       ├── settings_dialog.py   # 背景/主题/字体/质量预设/overlay 强度
│       ├── tabs.py              # 每个 Tab 的构造器 + 富下拉框
│       ├── file_list.py         # 拖拽、去重、目录扫描、右键菜单
│       └── theme.py             # Dark / Light QSS
├── scripts/
│   ├── build_macos.sh           # macOS 打包 (venv + pyinstaller + 可选 DMG)
│   └── build_windows.bat        # Windows 打包 (chcp 65001 + py launcher)
└── tests/
    ├── test_timestamps.py
    ├── test_parsers.py
    ├── test_ffmpeg_commands.py
    ├── test_format_meta.py
    ├── test_quality.py
    ├── test_constants.py
    └── test_integration_ffmpeg.py
```

## 快速开始

### 运行

```bash
python3 -m pip install -r requirements.txt
python3 Main.py
```

### 跑测试

```bash
python3 -m pytest tests/ -v
```

78 个测试，包括真实 ffmpeg 集成测试（合成音视频 → 转换 → probe）。2.5 秒跑完，无需外部素材。

### 打包

**macOS**:

```bash
scripts/build_macos.sh                     # 标准打包，生成 dist/Main.app
scripts/build_macos.sh --download-ffmpeg   # 顺带下载一份静态 ffmpeg 覆盖 resources/
scripts/build_macos.sh --dmg               # 再生成 DMG
scripts/build_macos.sh --clean             # 从零建 venv 重打一次
```

**Windows** (Windows 10+ 或更新):

```cmd
scripts\build_windows.bat
scripts\build_windows.bat --download-ffmpeg
scripts\build_windows.bat --clean
```

- 脚本第一行 `chcp 65001` 切到 UTF-8，确保中文输出不乱码。
- 请用 VS Code / Cursor 等能稳定保存 UTF-8 的编辑器，不要用记事本改脚本（会被改成 ANSI/GBK）。
- 自动探测 `py -3` 或 `python`，自建 `.venv-build` 虚拟环境，不污染系统 Python。

spec 文件用 `SPECPATH` 动态解析路径，仓库放到哪里都能打包。

## 本次重构解决了什么

### P0（修复了才能睡着觉）

1. **真正可取消的转换**: 原先 `stop()` 只是设置了 `_running=False` flag，子进程根本不受影响。现在 `CancelToken.cancel()` 会主动 `terminate()`，2 秒后还没退就 `kill()`。
2. **不再破坏用户源字幕**: 原先当输入就是 `.ass` 时，`inject_ass_style` 会用 `r+` 模式篡改用户的原文件。现在永远用 `tempfile`，上下文管理器保证清理。
3. **临时文件不再泄漏**: `StyledSubtitle` 实现了 `__exit__`，无论 ffmpeg 是否崩溃都会清理。
4. **force_style 语法修复**: 原先 `-vf subtitles=xxx:force_style=FontName=Arial,` 多了个尾部逗号，字幕样式实际没起作用；另一个分支还有完整的样式但被半路抛弃。现在只有一处定义。
5. **subtitles= 路径转义**: 原先包含空格 / 冒号 / 单引号的路径会把 filtergraph parser 炸掉。现在有 `_escape_subtitles_filter_path`。
6. **死代码清理**: 原先 `ffmpeg_convert` 和 `ffmpeg_convert_cmd` 几乎完全重复，前者从头到尾没人用。现在只有一份。
7. **测试基线**: 45 个单测，覆盖所有纯函数逻辑，回归一眼就能看见。

### P1（用起来明显更舒服）

- **单一配置源**: 所有编码参数集中在 `ffmpeg/profiles.py`。以前要改比特率得找两处。
- **日志节流**: 150ms 内的日志合并发送，长任务不再卡 UI。
- **异常收窄**: `except: ...` 替换为明确的 `OSError` / `SubprocessError` / `ValueError`，错误上下文写进日志。
- **去重 O(n²) → O(1)**: `FileListWidget` 用 set 做路径缓存。
- **文件图标 + 大小**: 列表项直接显示文件大小，不用自己去 Finder 看。
- **拖拽进度提示**: 列表为空时显示 "拖拽文件到这里"。
- **现代化 QSS**: 紫色主色、圆角 8-12px、柔和边框、带 hover 的按钮态。比原来的 4CAF50 绿色进度条养眼多了。
- **状态栏**: 显示"就绪 / 处理中 / 已完成"等反馈。
- **打开输出目录按钮**: 跑完直接点按钮进 Finder，不用找路径。

### 第二轮新增（体验打磨）

- **格式元信息**: 下拉框显示 `★ MP3 · 通用有损 · 320 kbps · 兼容性最佳`。推荐项用星标，鼠标悬停还有 tooltip。
- **质量预设**: 快速 / 均衡 / 高质量 单一开关 → 统一控制 libx264 preset+CRF、libx265 preset+CRF、VideoToolbox bitrate、AAC bitrate、FLAC compression level。
- **视频 Tab 支持"仅提取音频"**: 下拉框分组展示，选 "仅音频 · MP3" 就走 extract 路径，不用切 Tab。
- **批量进度精细化**:
  - 粗进度条: 整批完成度
  - 细进度条: 当前文件内部进度
  - 状态标签: `[3/10]  filename.mp4`
  - 时间标签: `00:01:23`（当前文件播放位置）
  - ETA 标签: `剩余 ~ 2m15s`（前 1 秒不预估）
- **从目录添加**: 递归扫整个文件夹，自动过滤扩展名。
- **右键联动**: "发送到字幕烧录 (视频)"等，一次拖拽多处复用。
- **智能 overlay**: 背景图之上叠加主题色遮罩（可调 0–100%），保证面板可读的同时保留壁纸。
- **记住上次选择**: 四个 Tab 的格式、烧录模式、输出格式都持久化。
- **输出目录安全检查**: 与源文件同目录时弹确认框，不再冷冰冰拒绝。
- **窗口标题栏加副标题和质量徽章**，扫一眼就知道当前设置。

### P2

- `Main.spec` 用 `SPECPATH` 动态解析路径，不再硬编码 `/Users/teark/Documents/Convert/...`。
- 设置键名集中在 `SettingsKey` 类里，拼写错误编译期可见。
- `.gitignore` 已包含 build / __pycache__ / .DS_Store / 用户配置。

## FFmpeg 管理策略

设计目标：**开箱即用 + 不污染系统 + 卸载干净**。

### 仓库层

`resources/ffmpeg` 和 `resources/ffmpeg.exe`（以及对应 `ffprobe`）不追踪到 git：
- 二进制体积大，会让 clone 变慢；
- 不同平台的 ffmpeg 互不兼容（macOS Mach-O、Windows PE、Linux ELF），commit 一份只能覆盖一个平台；
- 旧版本打包时 commit 过 Homebrew 依赖的 ffmpeg，结果换机器就跑不起来。

### 运行时的查找顺序

`converter/constants.py` 的 `_resolve_executable` 按以下顺序找 ffmpeg / ffprobe，第一个能跑的就用：

1. **应用内置** `resources/ffmpeg`（PyInstaller 打包进 `_MEIPASS`）
2. **应用数据目录缓存** `<App Data>/Convert/ffmpeg/ffmpeg`（首次运行自动下载到这里）
3. **系统 PATH** 上的 `ffmpeg`
4. **常见安装位置**（macOS：`/opt/homebrew/bin`、`/usr/local/bin`；Windows：`C:\Program Files\ffmpeg\bin` 等）

每一步都真正跑一次 `ffmpeg -version` 验证能执行，而不是只看文件存在。所以即使 bundled 的 ffmpeg 因为缺 dylib 无法运行，也能自动回落到其它路径。

### App Data 目录

| 平台 | 路径 |
|---|---|
| macOS | `~/Library/Application Support/Convert/` |
| Windows | `%LOCALAPPDATA%\Convert\` |
| Linux | `~/.local/share/Convert/` |

要彻底清理程序（包括自动下载的 ffmpeg 缓存），只要删掉这个目录。程序从不修改系统 PATH、不放快捷方式在别处、不需要管理员权限。

### 首次启动：找不到 ffmpeg 怎么办

程序启动时如果上述四种路径都找不到可用的 ffmpeg，弹出 **FirstRunDialog**，提供三个选择：

1. **自动下载（推荐）**：从对应平台的静态源下载，解压到 App Data 目录。
   - macOS: [evermeet.cx](https://evermeet.cx/ffmpeg/) (静态，含 libass)
   - Windows: [gyan.dev](https://www.gyan.dev/ffmpeg/builds/) (release-essentials, 含 libass)
   - Linux: [johnvansickle.com](https://johnvansickle.com/ffmpeg/) (amd64 / arm64 静态)
2. **指定已有 FFmpeg…**：打开文件选择器，用户指向自己已经装好的 ffmpeg。程序会把它和旁边的 ffprobe **复制**（不是链接）到 App Data 目录，下次启动直接用。
3. **退出**：放弃启动。

下载时显示进度条和状态文字（"正在下载 / 解压 / 验证"）。Apple Silicon 上首次执行 x86_64 ffmpeg 需要 Rosetta 2 翻译，首启动会停留 10-20 秒在"验证"阶段，**这是正常的**。

### 打包时预置 ffmpeg（避免用户看到 FirstRunDialog）

`scripts/build_*.{sh,bat} --download-ffmpeg` 会在打包前把对应平台的静态 ffmpeg 下载到 `resources/`，PyInstaller 会连同打包进 `.app`/`.exe`。这样最终用户拿到的安装包**内置了可用的 ffmpeg**，首次启动直接进入主界面。

`Main.spec` 会按平台过滤：mac 打包时排除 `resources/ffmpeg.exe`，Windows 打包时排除 `resources/ffmpeg`（macOS Mach-O 二进制）。同一份仓库两边都能正确打包。

## 已知保留的设计决策

1. **保留 PyQt5 而不升级到 PyQt6**：用户没要求，升级需要处理 enum 全限定名、信号类型变化等破坏性改动，属于"你没要求我做，但做了一定炸"的雷区。
2. **LRC 时间戳毫秒精度**：LRC 标准是百分秒（cs），但市面上也有程序写 ms。parser 现在根据小数位数自适应，保持宽容。
3. **RMVB 编码器**：原版用 `librmvb`，ffmpeg 官方不带这个编码器，需要用户自己编译。保持原样。

## 后续值得做的事（没在这次 PR 里）

- 换 PyQt6 / PySide6，获得更好的 HiDPI 和多显示器支持
- 多文件并发处理（当前批量任务是串行的）
- 批量音视频合并，而不是只取第一个
- 字幕样式的 UI 配置项（当前硬编码粉色）
- 用 `QSettings` 的原生方式替代 INI 文件，跨平台配置更干净
