# ContextCLI

Windows 资源管理器「快捷执行」右键菜单管理器：用图形界面配置 CLI 命令，一键注册到右键菜单，选中文件或文件夹即可执行。

## 功能

- ttk 图形化管理端：命令列表、编辑表单、实时测试、YAML 导入导出。
- 命令列表为空时右侧编辑表单禁用；新建或选中命令后自动启用。
- 工具栏「复制」可基于当前命令快速创建副本，副本插入原命令之后，名称自动加「副本」后缀。
- 测试验证的预览与输出区使用可拖动分隔条，预览高度可随时调整；「清空」可一键清除预览与上次运行输出。
- 按扩展名精确控制文件右键菜单，不匹配的扩展名不会出现菜单；扩展名留空表示适用于所有文件。
- 「仅目录」命令只出现在文件夹右键菜单；右键菜单顺序与命令列表顺序一致。
- 参数留空时不匹配扩展名，直接用系统默认方式启动执行程序（`os.startfile`）。
- 多选文件支持：资源管理器选中多个文件执行时，自动合并为一批顺序处理（不支持多选目录）。
- 执行前列出待处理文件的数量与文件名，确认后才开始。
- 文件夹输入支持按扩展名过滤、可选递归、批量顺序执行。
- 变量替换：`{input}`、`{input_name}`、`{input_ext}`，以及输出路径相关变量。
- 输出目录默认源文件目录，也可指定；支持输出文件名模板。
- 右键菜单统一收在「快捷执行」子菜单下，带闪电图标，一键注册/移除。
- 单文件执行弹控制台看实时输出；批量执行使用内置进度窗口；全部写日志。
- 适配 Windows 高 DPI（125% / 150% 等），界面、列表行高与窗口尺寸随系统缩放。

## 环境要求

- Windows 10 / 11
- [uv](https://docs.astral.sh/uv/)（推荐 0.9+）
- Python 3.12（由 uv 自动管理）

## 安装与运行

```bash
uv sync
uv run context-cli
```

首次启动会打开空配置的管理界面。配置和日志位于：

```
%APPDATA%\ContextCLI\commands.yaml
%APPDATA%\ContextCLI\logs\
```

也可以指定配置文件：

```bash
uv run context-cli --config D:\demo\commands.yaml
```

## 快速开始

1. 点击「新建」，填写：
   - 名称：右键菜单显示名，例如“视频转 MP4”。
   - 扩展名：`mp4, mkv, avi`（只填最终后缀，不带点）。
   - 执行程序：完整路径 `C:\ffmpeg\bin\ffmpeg.exe`，或 PATH 中的 `ffmpeg`。
   - 参数：例如 `-i "{input}" -c:v libx264 "{output}"`。
   - 输出目录：留空表示源文件所在目录。
   - 文件名模板：例如 `{input_name}.mp4`。
2. 点击右侧「▶ 测试验证」展开测试区域，选择样例文件，点击「预览」检查最终命令行，再点「运行测试」。测试区域默认折叠，用完可点「▼ 收起测试验证」收回；重新调试前可点「清空」清除上次预览与输出。
3. 需要基于现有命令创建变体时，选中命令后点击「复制」，副本会插在原命令后面，修改名称和参数后保存即可。
4. 点击「保存」。
5. 点击「注册右键菜单」。
6. 在资源管理器中右键选中匹配扩展名的文件，打开「快捷执行」子菜单。
7. 如需撤销，点击「移除右键菜单」。

> Windows 11 会把传统注册表右键菜单折叠到「显示更多选项」中。本项目使用传统菜单，因此在 Win11 上需要先点「显示更多选项」（或按 Shift+F10）。

## 变量

| 变量 | 含义 | 示例 |
|---|---|---|
| `{input}` | 输入文件完整路径 | `D:\素材\a.mkv` |
| `{input_name}` | 文件名，不含路径和最终后缀 | `a` |
| `{input_ext}` | 最终后缀，不含点，保留原大小写 | `mkv` |
| `{input_dir}` | 输入文件所在目录 | `D:\素材` |
| `{output_dir}` | 输出目录 | `D:\输出` |
| `{output_name}` | 输出文件名 | `a.mp4` |
| `{output}` | 输出完整路径 | `D:\输出\a.mp4` |

规则：

- 变量单次展开，不会递归替换。
- 未知变量会在执行前报错。
- 路径变量建议用双引号包裹，例如 `-i "{input}" "{output}"`。
- 参数留空：不匹配扩展名、不做变量展开，直接用系统默认方式启动执行程序。
- 参数非空：必须包含至少一个输入变量。
- 文件夹输入时，每个匹配文件分别生成一组变量。

## 输出路径

1. 输出目录留空：输出到输入文件所在目录。
2. 输出目录为绝对路径：直接使用。
3. 输出目录为相对路径：相对于选中的根（文件取其父目录，文件夹取该文件夹）。
4. 文件夹 + 递归 + 勾选「保留目录结构」：在输出目录下保留源文件的相对子目录。
5. 输出目录不存在时自动创建。
6. 输出文件名模板不能包含路径分隔符或 Windows 非法字符。

## YAML 配置

完整示例见 `examples/commands.example.yaml`。

```yaml
version: 1
settings:
  menu_title: 快捷执行
commands:
  - id: "video2mp4"
    name: "视频转 MP4"
    enabled: true
    comment: "ffmpeg 转码为 H.264 MP4"
    extensions: ["mp4", "mkv", "avi"]
    executable: "C:/ffmpeg/bin/ffmpeg.exe"
    arguments: '-i "{input}" -c:v libx264 -crf 23 "{output}"'
    recurse: true
    output_dir: ""
    output_name: "{input_name}.mp4"
    keep_structure: true
    show_console: true
```

字段说明：

| 字段 | 说明 |
|---|---|
| `id` | 稳定唯一 ID，由程序生成；注册表调用依赖它 |
| `name` | 右键菜单显示名 |
| `enabled` | 是否启用/注册 |
| `comment` | 用途与参数说明，仅界面展示 |
| `extensions` | 扩展名列表，不带点 |
| `executable` | 完整路径或 PATH 命令名 |
| `arguments` | 参数模板 |
| `recurse` | 文件夹输入时是否递归 |
| `output_dir` | 输出目录；空 = 源文件目录 |
| `output_name` | 输出文件名模板，默认 `{input_name}_out.{input_ext}` |
| `keep_structure` | 指定输出目录且递归时保留子目录结构 |
| `show_console` | 单文件执行时是否弹出控制台 |

> 导入的 YAML 会被当作可执行配置，请确认来源可信。

## 右键菜单原理

仅写入当前用户注册表（HKCU），不需要管理员权限：

```
HKCU\Software\Classes\SystemFileAssociations\.mp4\shell\ContextCLI
HKCU\Software\Classes\*\shell\ContextCLI          （扩展名为空的命令）
HKCU\Software\Classes\Directory\shell\ContextCLI
```

- 每个有启用命令的扩展名生成一个「快捷执行」菜单，不匹配的扩展名不出现。
- 文件夹菜单列出全部启用命令，运行时再按扩展名过滤文件。
- 菜单项调用 `ContextCLI.exe --run <command_id> "<选中路径>"`。
- 菜单带闪电图标（`Icon` 值指向 exe 内嵌图标），子键用 `0000_` 数字前缀锁定显示顺序。
- `MultiSelectModel=Player`：多选文件时资源管理器按文件逐个启动本程序，程序内部通过命名互斥体把同一批启动合并为一次批量执行。
- 注册/卸载后调用 `SHChangeNotify` 刷新资源管理器。
- 重新注册会先清理旧的 `ContextCLI` 键，卸载也会扫描并清理残留。

## 执行行为

- 参数为空：直接用系统默认方式启动执行程序，不传参。
- 执行前先弹窗列出待处理文件数量与文件名，确认后才开始。
- 工作目录：命令可执行文件所在目录。
- 单文件 + 「显示控制台」：打开新控制台窗口（`subprocess.run`），失败时弹窗提示。
- 单文件 + 不显示控制台：后台捕获输出，成功静默，失败弹窗。
- 多选文件/文件夹：内置进度窗口，先列出完整文件清单，点「开始执行」后运行，支持停止，结束后显示汇总。
- 所有执行均写入 `%APPDATA%\ContextCLI\logs\`，保留 1 天；运行前会自动清理过期日志。

## 打包

```bash
uv run pyinstaller packaging/context_cli.spec --noconfirm
```

产物：

```
dist\ContextCLI\ContextCLI.exe
```

打包版为 windowed onedir 程序，注册表会指向该 exe。将整个 `dist\ContextCLI` 目录移动到固定位置后再注册；移动后重新注册即可。

## 开发与测试

```bash
uv sync
uv run pytest
uv run python -m compileall src
```

目录结构：

```
src/context_cli/
  __main__.py        入口与参数分派
  config.py          路径与常量
  models.py          命令/配置模型
  variables.py       变量解析
  storage.py         YAML 读写
  jobs.py            文件收集与输出规划
  runner.py          子进程执行与日志
  registry.py        右键菜单注册/卸载
  ui/                ttk 界面
tests/               单元测试
packaging/           PyInstaller 配置
```

## 常见问题

**菜单没有出现？**

- 确认命令已启用并保存，再点一次「注册右键菜单」。
- 确认文件扩展名在列表中。
- Windows 11 请点「显示更多选项」。
- 关闭并重新打开资源管理器窗口，或重启 explorer.exe。

**提示找不到执行程序？**

- 填写完整路径，或确保命令在 PATH 中。
- 注册前程序会检查所有启用命令的执行程序，缺失时会列出问题并中止。

**ffmpeg 输出太快看不清？**

- 批量模式会保留进度窗口和日志；单文件控制台模式失败时会弹窗提示日志路径。

**如何彻底清理注册表？**

在程序中点「移除右键菜单」。如需手动检查：

```
HKCU\Software\Classes\SystemFileAssociations\*\shell\ContextCLI
HKCU\Software\Classes\Directory\shell\ContextCLI
```

## 已知限制

- 多选仅支持文件；不支持多选目录（目录请单个选择）。
- 不支持 Windows 11 一级现代右键菜单（需 COM Shell 扩展）。
- 不支持管道、重定向等 shell 语法，也不支持 `.bat` / `.cmd` 脚本（直接通过 CreateProcess 启动 exe）。
- 扩展名仅支持最终后缀，不支持 `tar.gz` 这类复合后缀。
- 仅支持当前用户（HKCU），不支持全用户安装。
