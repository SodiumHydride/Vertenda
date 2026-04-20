# 盐酸转换器 · Vertenda

> **Vertenda** · [vɛrˈtɛn.da] · Latin gerundive of *vertere* — "that which is to be turned / converted". An all-in-one audio / video / subtitle converter with subtitle burn-in and cross-platform GPU acceleration (VideoToolbox on macOS, NVENC / Quick Sync / AMF on Windows). PyQt5 GUI + full-featured CLI, sharing one ffmpeg command layer.

多合一音频 / 视频 / 字幕转换器，带字幕烧录、批量队列、跨平台 GPU 硬件加速（macOS VideoToolbox，Windows NVENC / Quick Sync / AMF 自动识别）。GUI 与 CLI 共享同一套 ffmpeg 命令构造逻辑，业务代码不重复一行。

名字 **Vertenda** 取自拉丁语动形词 *vertere*（转、变），字面意思是"那些将被转换之物"——正好对应这个工具的本质。

License
Python
Platform
Qt

---

## 目录

- [功能一览](#功能一览)
- [快速开始](#快速开始)
- [CLI 用法](#cli-用法)
- [FFmpeg 管理策略](#ffmpeg-管理策略)
- [Windows 右键菜单（可选）](#windows-右键菜单可选)
- [项目结构](#项目结构)
- [打包](#打包)
- [设计决策](#设计决策)
- [贡献](#贡献)
- [Acknowledgments](#acknowledgments)
- [License](#license)

---

## 功能一览

### 转换核心


| 类别  | 格式                                                                     |
| --- | ---------------------------------------------------------------------- |
| 音频  | `mp3` · `wav` · `flac` · `aac` · `m4a` · `ogg` · `opus`                |
| 视频  | `mp4` · `mkv` · `mov` · `avi` · `flv` · `wmv` · `webm` · `ts` · `rmvb` |
| 字幕  | `srt` · `ass` · `ssa` · `vtt` · `lrc`                                  |


- **音频 ↔ 音频 / 视频 ↔ 视频** 互转，使用专业级编码器参数
- **视频 → 仅音频**：视频 Tab 下拉里的"仅音频 · MP3 / FLAC / ..."一键剥离，不用切 Tab
- **字幕互转**：纯 Python + ffmpeg 双路径，lrc 和 ass 之间会自动走多步转换
- **音视频合并**：从列表里取第一个音频和第一个视频合成
- **字幕烧录**：硬编码（永久烧入画面）/ 软封装（独立轨道），支持自定义样式对话框

### 质量与性能

- **质量预设**：快速 / 均衡 / 高质量 三档，统一控制 libx264/x265 preset+CRF、VideoToolbox 码率、NVENC/QSV/AMF 的 CQ/QP、AAC 码率、FLAC 压缩级别
- **跨平台硬件加速**：单个"硬件加速"开关，运行期自动识别可用编码器
  - **macOS** · VideoToolbox（`h264_videotoolbox` / `hevc_videotoolbox` / `prores_videotoolbox`）
  - **Windows** · 自动按 `NVENC > Quick Sync > AMF` 优先级探测 `ffmpeg -encoders`，选第一个可用的编码器族
  - **Linux / BSD** · 软编（VAAPI/NVENC 后续版本支持）
- **批量并发**：1–8 路或自动（按 CPU 核心数），每个任务独立取消
- **真正可取消**：取消按钮会 `terminate()` 子进程，2 秒没退就 `kill()`
- **视频缩放**：`1080p` / `720p` / `480p` / 自定义 `WxH`
- **时间裁剪**：`--trim-start` / `--trim-end`（秒）
- **音量归一化**：EBU R128 `loudnorm`

### UI / 工作流

- **富格式下拉**：`★ MP3 · 通用有损 · 320 kbps · 兼容性最佳` 式的分组提示
- **实时进度**：整批完成度 + 当前文件内部进度 + ETA + `[3/10] filename.mp4` 状态
- **文件队列**：拖拽添加、递归扫描目录、去重、右键"发送到字幕烧录"
- **冲突策略**：跳过 / 覆盖 / 重命名 / 询问
- **文件名模板**：`{base}` · `{date}` · `{target}` 等变量
- **任务历史**：每次转换记录可查、可重放
- **用户预设**：保存常用配置到命名预设（"YouTube 投稿" / "iOS 兼容" / …），一键切换
- **系统通知 + 完成后打开输出目录**
- **深色 / 浅色主题** + 自定义背景图 + 可调遮罩强度

---

## 快速开始

### 从源码运行

```bash
git clone https://github.com/<your-name>/Vertenda.git
cd Vertenda

python3 -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt

python Main.py
```

Python 3.9 以上皆可。首次启动会提示下载 ffmpeg（见 [FFmpeg 管理策略](#ffmpeg-管理策略)），或者你可以指向已有的 `ffmpeg`。

### 跑测试

```bash
python -m pytest tests/ -v
```

17 个测试文件，220 个测试用例，包含真实 ffmpeg 集成测试（合成音视频 → 转换 → probe），2-3 秒跑完，无需外部素材。

### 依赖

```
PyQt5>=5.15,<6
psutil>=5.9
pytest>=7.0
winotify>=1.1       # Windows only
```

以及运行期的 `ffmpeg` / `ffprobe`（首次启动可一键下载）。

---

## CLI 用法

GUI 与 CLI 共享同一套业务代码：**无参启动是 GUI，有参是 CLI**。

### 常用形式

```bash
# 单文件转换（自动识别输入类型）
python Main.py input.wav -f mp3
python Main.py input.mov -f mp4 --hw-accel --quality high
python Main.py input.srt -f lrc

# 指定输出位置
python Main.py input.mov -f mp4 -o /path/to/out.mp4
python Main.py input.mov -f mp4 -d /output/dir/      # 只指定输出目录
```

### 子命令

```bash
# 烧录字幕
python Main.py burn video.mp4 subs.srt -o out.mp4           # 硬编码（默认）
python Main.py burn video.mp4 subs.srt -o out.mkv --soft    # 软封装

# 合并音视频
python Main.py merge audio.mp3 video.mp4 -o merged.mp4

# 管理 FFmpeg 缓存
python Main.py install-ffmpeg                               # 主动下载
python Main.py install-ffmpeg --data-dir D:\MyTools         # 指定下载到别处
python Main.py uninstall-ffmpeg                             # 清除（只动自己下载的）

# 诊断 / 其它
python Main.py where                                        # 打印解析到的路径与 marker
python Main.py --version
python Main.py --gui                                        # 明确打开 GUI
```

> 打包后直接运行 `Vertenda` / `Vertenda.exe` 即可替换上面的 `python Main.py`。

### 运行时参数


| 参数                            | 说明                                                     |
| ----------------------------- | ------------------------------------------------------ |
| `-q, --quality`               | `fast` / `balanced` / `high`（默认 `balanced`）            |
| `--hw-accel`                  | 开启硬件加速（macOS VideoToolbox / Windows 自动选 NVENC·QSV·AMF） |
| `--conflict`                  | `skip` / `overwrite` / `rename`（默认 `overwrite`）        |
| `--filename-template`         | 输出文件名模板，默认 `{base}`                                    |
| `--concurrency`               | `auto` 或 `1`–`8`（默认 `auto`）                            |
| `--scale`                     | `1080p` / `720p` / `480p` / `WxH`                      |
| `--normalize`                 | 音量归一化（loudnorm EBU R128）                               |
| `--trim-start` / `--trim-end` | 裁剪起止时间（秒）                                              |


### 退出码


| 码   | 含义                  |
| --- | ------------------- |
| 0   | 成功                  |
| 2   | 用法错误（文件不存在、参数非法）    |
| 3   | 运行时错误（ffmpeg 失败、取消） |
| 4   | 未找到可用的 FFmpeg       |


---

## FFmpeg 管理策略

设计目标：**开箱即用 + 不污染系统 + 卸载干净**。

### 仓库层

`resources/ffmpeg`、`resources/ffmpeg.exe`（及对应 `ffprobe`）**不追踪到 git**：

- 二进制体积大会拖慢 clone
- 不同平台互不兼容（macOS Mach-O、Windows PE、Linux ELF），commit 一份只能覆盖一个平台
- 系统依赖的 ffmpeg（比如 Homebrew）往往携带动态库链接，换台机器就跑不起来

### 运行时的查找顺序

`converter/constants.py` 的 `_resolve_executable` 按以下顺序寻找 `ffmpeg` / `ffprobe`，**第一个能真正跑 `ffmpeg -version` 的就用**：

1. **应用内置**：`resources/ffmpeg`（PyInstaller 打包进 `_MEIPASS`）
2. **应用数据目录缓存**：`<App Data>/Vertenda/ffmpeg/ffmpeg`（首次运行下载到这里）
3. **系统 PATH**：`shutil.which("ffmpeg")`
4. **常见安装位置**（macOS `/opt/homebrew/bin`、`/usr/local/bin`；Windows `C:\Program Files\ffmpeg\bin` 等）

每一步都**真正执行一次 `-version`** 验证能跑，不只是看文件存在。bundled ffmpeg 因缺动态库无法运行时也能自动回落到系统路径。

### App Data 目录


| 平台      | 路径                                        |
| ------- | ----------------------------------------- |
| macOS   | `~/Library/Application Support/Vertenda/` |
| Windows | `%LOCALAPPDATA%\Vertenda\`                |
| Linux   | `~/.local/share/Vertenda/`                |


要彻底清理程序（包括自动下载的 ffmpeg 缓存），删掉这个目录即可。程序**从不**修改系统 PATH、不放启动项、不需要管理员权限。

### 首次启动：找不到 ffmpeg 怎么办

启动时若四种路径都找不到可用的 ffmpeg，弹出 **FirstRunDialog**，提供三个选择：

1. **自动下载（推荐）**：从对应平台的静态构建下载到 App Data 目录。
  - macOS：[evermeet.cx](https://evermeet.cx/ffmpeg/)（静态，含 libass）
  - Windows：[gyan.dev](https://www.gyan.dev/ffmpeg/builds/)（release-essentials，含 libass）
  - Linux：[johnvansickle.com](https://johnvansickle.com/ffmpeg/)（amd64 / arm64 静态）
2. **指定已有 FFmpeg…**：文件选择器选中已装好的 `ffmpeg`。程序会**复制**（不是软链）它和旁边的 `ffprobe` 到 App Data 目录。
3. **退出**。

下载时显示进度与状态文字。Apple Silicon 首次执行 x86_64 ffmpeg 时 Rosetta 2 需要翻译，"验证"阶段可能停留 10–20 秒，属正常现象。

### 自定义数据目录（Windows C 盘紧张？）

- **首次启动**：FirstRunDialog 上方显示"下载位置"和"更改…"按钮
- **任何时候**：设置 → 数据与存储 → 数据目录，改到其他磁盘
- 老位置的缓存**不会自动迁移**，换目录后需要时会重新下载。

### 安装 marker

下载完成后在缓存目录写 `.installed_by_convert.json`（文件名沿用内部标识，不随品牌改名）：

```json
{
  "schema": 1,
  "installed_at": "2026-04-19T14:00:00Z",
  "app_version": "2.0.0",
  "sources": ["https://evermeet.cx/ffmpeg/getrelease/zip", "..."],
  "ffmpeg_version": "ffmpeg version 8.1 ...",
  "platform": "darwin"
}
```

这个文件是 **"只有我们安装的才能删"的判据**。设置里的"清除 FFmpeg 缓存"按钮仅在 marker 存在时启用，避免误删 `brew install ffmpeg` 的副本。

### 卸载

刻意**不做**正式 installer，保持"拖走即干净"：

1. 设置 → 数据与存储 → **清除 FFmpeg 缓存**
2. （可选）**打开数据目录**，手动删剩余文件
3. 把 `Vertenda.app` 拖到废纸篓 / 删除 `Vertenda.exe` 所在目录

本程序**从不**修改：系统 PATH、Windows 注册表（除非你开启右键集成，此时也只写 `HKCU`）、`/usr/local/bin` 之类的系统目录、启动项 / 登录项。

---

## Windows 右键菜单（可选）

**设置 → 转换 → 右键集成** 勾选后，在 Windows 资源管理器里右键常见的音视频 / 字幕文件：

```
右键 video.mp4
 └─ 转换 (Kurisu) >
     ├─ 转为 MP3 (仅音频)
     ├─ 转为 MP4
     ├─ 转为 MKV
     └─ 用 Kurisu 打开
```

- 只写 `HKCU\Software\Classes\...`（用户注册表），不需要管理员权限
- 用 CommandStore + SubCommands 做二级菜单，右键只多"转换 (Kurisu)"一行，点开才展开
- 取消勾选立即 unregister，不留注册表残留
- **只在 Windows 上显示这个开关**

---

## 项目结构

```
Vertenda/
├── Main.py                      # 薄入口：决定 GUI / CLI 路由
├── Main.spec                    # PyInstaller 打包配置（路径可移植）
├── requirements.txt
├── converter/
│   ├── constants.py             # 扩展名、路径解析、SettingsKey
│   ├── cli.py                   # argparse + 子命令分发
│   ├── worker.py                # QThread 任务层
│   ├── queue.py                 # TaskCoordinator（并发调度 + 事件流）
│   ├── planning.py              # 批量输出路径规划（避免并发路径竞争）
│   ├── estimator.py             # 预估时长 / 大小 / 冲突
│   ├── presets.py               # 命名预设 + schema 迁移
│   ├── history.py               # 任务历史持久化
│   ├── format_meta.py           # 格式富元信息
│   ├── fs.py                    # 冲突策略、文件名模板、磁盘检查
│   ├── notify.py                # 系统通知（跨平台）
│   ├── ffmpeg/
│   │   ├── commands.py          # 命令构造（纯函数，GUI / CLI 共享）
│   │   ├── profiles.py          # 编码器配置（参数化为 QualitySpec）
│   │   ├── quality.py           # QualityPreset + QualitySpec
│   │   ├── probe.py             # ffprobe 工具
│   │   ├── runner.py            # 可取消的子进程执行器 + 进度解析
│   │   └── installer.py         # 首次运行 / CLI 的 ffmpeg 下载器
│   ├── subtitle/
│   │   ├── timestamps.py        # 秒 ↔ 时间戳
│   │   ├── parsers.py           # lrc / srt / vtt → Cue
│   │   ├── converters.py        # Cue ↔ 文件
│   │   ├── styling.py           # ASS 样式注入（不破坏源文件）
│   │   └── styling_config.py    # BurnStyle 数据类
│   ├── shell/
│   │   └── win_registry.py      # Windows 右键菜单 HKCU 写入
│   └── ui/
│       ├── main_window.py       # 主窗口 + overlay + 拖拽
│       ├── first_run_dialog.py  # 首次启动 ffmpeg 引导
│       ├── settings_dialog.py   # 外观 / 转换 / 数据 三页
│       ├── preset_dialog.py     # 预设管理
│       ├── history_dialog.py    # 历史回顾
│       ├── burn_style_dialog.py # 字幕烧录样式编辑
│       ├── estimate_dialog.py   # 批量转换前预估
│       ├── queue_panel.py       # 实时队列 UI
│       ├── result_panel.py      # 批量结果汇总
│       ├── file_list.py         # 拖拽 / 去重 / 右键
│       ├── tabs.py              # 四个 Tab 构造器
│       └── theme.py             # Dark / Light QSS
├── scripts/
│   ├── build_macos.sh           # macOS 打包（venv + pyinstaller + 可选 DMG）
│   └── build_windows.bat        # Windows 打包（chcp 65001 + py launcher）
└── tests/                       # 17 个测试文件，220+ 用例
```

---

## 打包

### macOS

```bash
scripts/build_macos.sh                     # 标准打包，生成 dist/Vertenda.app
scripts/build_macos.sh --download-ffmpeg   # 同时下载一份静态 ffmpeg 放进 resources/
scripts/build_macos.sh --dmg               # 再生成 DMG
scripts/build_macos.sh --clean             # 从零建 venv 重打一次
```

### Windows 10+

```cmd
scripts\build_windows.bat
scripts\build_windows.bat --download-ffmpeg
scripts\build_windows.bat --clean
```

- 脚本第一行 `chcp 65001` 切到 UTF-8，确保中文输出不乱码
- 脚本本身需用 UTF-8 编辑器（VS Code / Cursor 等）保存，避免被 Notepad 改成 ANSI/GBK 后导致乱码
- 自动探测 `py -3` 或 `python`，自建 `.venv-build`，不污染系统 Python

`Main.spec` 用 `SPECPATH` 动态解析路径，仓库放到哪里都能打包；按平台自动过滤掉对方平台的 ffmpeg 二进制，同一份仓库两边都能正确打包。

---

## 设计决策

### GUI 与 CLI 共享同一套命令构造

所有 ffmpeg 参数在 `converter/ffmpeg/commands.py` 里以纯函数形式返回 `list[str]`；`converter/ffmpeg/profiles.py` 负责编码器参数。UI 和 CLI 都只是这些纯函数的 caller，没有业务逻辑重复。

### 取消语义

每个 `SingleFileRunnable` 持有自己的 `CancelToken`。`cancel()` 会：

1. 立即置 `CANCELLING` 状态，解锁 pause 闩
2. `terminate()` 当前 `Popen`，2 秒后未退出则 `kill()`
3. 在 attach 之前就已 `cancel()` 的情况也会被记录，下一个 attach 立即终止

### 批量写路径竞争

多路并发写同一目录时，两个 runnable 同时 `resolve_output_path("foo.mp4")` 会都算出 `foo_1.mp4` 然后互相截断。`converter/fs.py:reserve_output_path` 把"磁盘存在"与"已被其它 runnable 预约"合并成一次原子判断，由 `TaskCoordinator` 共享预约集。

### 预设的 schema 迁移

每个 `TaskPreset` 带 `schema_version`；字段增删改时通过 `_MIGRATIONS` 链式升级旧记录，用户永远不会因为换版本看到空白或崩溃。

### 临时文件 / 字幕注入

`inject_burn_style(subtitle)` 永远走 `tempfile`，上下文管理器保证 ffmpeg 崩溃也能清理；永远不 `r+` 写用户传入的源文件。

### 子路径转义

`subtitles=path:force_style=...` 这个 filtergraph 对路径里的空格、冒号、单引号非常敏感。`_escape_subtitles_filter_path` 专门处理；有完整测试覆盖。

### Windows 硬件加速的检测策略

单开关暴露给用户、内部自动挑选。首次用到时跑一次 `ffmpeg -hide_banner -encoders`，按 **NVENC > QSV > AMF** 的优先级选第一个可用的族，结果在进程内缓存。选择这个顺序的理由：

- NVENC 在同码率下画质通常最好，驱动稳定性高
- QSV 几乎所有带核显的 Intel CPU 都支持，覆盖面广但画质一般
- AMF 只有 AMD 显卡用，且在 ffmpeg 的实现历史较新、参数文档较少

**一个刻意的保守决定**：Windows 上 `use_hw=True` 时我们**不传 `-hwaccel` 输入标志**，只用硬件编码器、不用硬件解码器。因为 `-hwaccel cuda` 在缺少对应解码器的 stock ffmpeg 上会直接 fail，而仅编码硬件化就能拿到大部分加速。全链路硬件（解 + 编）作为 v2.1 的增强项保留。

编码器参数统一成 CRF-like 数值（`-cq` / `-global_quality` / `-qp_`*），让快速/均衡/高质量三档在所有编码器上语义一致，用户不用记每种 GPU 的独特调参逻辑。

### 硬编码取舍

- **PyQt5 而非 PyQt6**：PyQt6 的 enum 全限定、signal 语法、高 DPI 模型都是破坏性变更；目前 PyQt5 够用且测试覆盖齐。欢迎 PR 迁移。
- **LRC 毫秒精度**：LRC 标准只到百分秒（cs），但实际存在写 ms 的文件。parser 根据小数位数自适应。
- **RMVB**：ffmpeg 官方不带 `librmvb`，打包不内置；需要用户自行提供支持该编码器的 ffmpeg。
- **Linux 暂无硬件加速**：VAAPI/NVENC on Linux 是可行的，但需要更精细的检测（`/dev/dri/`* 存在性 + 编码器列表交叉判定），作为未来版本的功能。

---

## 贡献

欢迎 Issue / PR。建议：

- 开 PR 前跑一次 `python -m pytest tests/ -v`，纯函数改动应该秒过
- UI 改动附截图；涉及 ffmpeg 命令构造时请补一个 `test_ffmpeg_commands.py` 用例
- 新功能若引入配置项，记得同步 `SettingsKey` 常量 + 必要时更新 `_MIGRATIONS`
- 不向仓库提交 `resources/ffmpeg`* 二进制；那是用户运行期或打包期才产生的
- 报 bug 时带上 `python Main.py where` 的输出，能省掉一半来回

---

## Acknowledgments

Vertenda 由人类作者与 AI 结对编程共同构建，工具链是 [Cursor](https://cursor.com) IDE。

AI 协作者在这个项目里有一个稳定的代号 **Kurisu**（取自牧濑红莉栖，*Steins;Gate* 的 Lab Member #004）——这也是为什么仓库里到处能看到这个名字：

- macOS bundle identifier `com.kurisu.vertenda`
- Qt organization name `Kurisu`
- Windows 资源管理器右键菜单 `转换 (Kurisu)`

把它当成一个一以贯之的内部梗 + 诚实的 credit line 就好。所有代码经过人类作者审阅、测试、调试；bug 归我，巧妙的部分归我们两个。

*Bugs are mine; clever bits are ours.*

---

## License

本项目以 [GNU General Public License v3.0](./LICENSE) 发布。

依据 GPL-3.0：任何再分发、修改、衍生作品必须同样以 GPL-3.0 开源，并带上源代码。

第三方依赖：

- **FFmpeg** · LGPL / GPL（由程序调用为外部进程；未静态链接）
- **PyQt5** · GPL-3.0 / 商业双许可（本项目使用 GPL-3.0 分支）
- **psutil** · BSD-3-Clause
- **winotify** · MIT

---

盐酸转换器 · Vertenda · v2.0.0 · Built with Kurisu · GPL-3.0