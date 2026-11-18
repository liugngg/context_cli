# ContextCLI 项目规划

> Windows 资源管理器「快捷执行」右键菜单 CLI 管理器
>
> 需求来源：`project_requestment.txt`
> 规划定稿：2026-11-16
> 当前状态：v1 已实现；核心测试、GUI、打包与注册表闭环验证通过（2026-11-16）

---

## 1. 项目目标

用 Python + tkinter/ttk 编写一个 Windows 桌面程序，让用户通过图形界面配置 CLI 命令，并一键注册到资源管理器右键菜单「快捷执行」下：

- 右键选中文件或文件夹，即可调用配置好的 CLI 命令；
- 按文件扩展名精确控制菜单是否出现；
- 支持变量替换、输出路径规划、文件夹批量/递归处理；
- 配置可用 YAML 保存、导入、导出；
- 可单独测试命令，也可随时注册/移除右键菜单。

## 2. 范围

### 2.1 v1 包含

- ttk 图形化管理端：命令列表、编辑表单、测试面板、注册状态。
- Runner 执行端：由右键菜单静默调用，读取 YAML 并执行命令。
- 变量：`{input}`、`{input_name}`、`{input_ext}`，以及扩展的目录/输出变量。
- 单文件与单文件夹输入；文件夹支持按扩展名过滤、可选递归。
- 输出目录默认源文件目录，也可指定；输出文件名模板化。
- 右键菜单：文件按扩展名注册，文件夹统一注册；全部收在「快捷执行」子菜单下。
- YAML 持久化、导入导出、原子保存与备份。
- Windows 10/11，仅当前用户（HKCU），无需管理员权限。
- uv 管理依赖与虚拟环境；PyInstaller 打包为 windowed onedir 程序。

### 2.2 v1 不包含

- 资源管理器多选批量处理（仅支持单选；文件夹处理承担批量场景）。
- Windows 11 一级现代右键菜单（需 COM Shell 扩展）。
- HKLM 全用户安装、开机自启、自动更新。
- 管道、重定向等 shell 语法；产品定位是直接调用 CLI 可执行文件。
- 命令编排、任务队列、并发执行、定时任务。
- 多语言界面（仅中文）。
- `tar.gz` 这类复合后缀（Windows 扩展名按最终后缀处理，见 §6.3）。

## 3. 已确认决策

| 主题 | 决策 |
|---|---|
| 多选 | 支持多选文件（`MultiSelectModel=Player` + 互斥体合并）；不支持多选目录 |
| 输出配置 | 提供 `{output_dir}`、`{output_name}`、`{output}` 变量 |
| 执行反馈 | 执行前列出待处理文件清单确认；单文件弹控制台看实时输出，失败弹窗；批量用内置进度窗口；全部写日志 |
| 空参数 | 参数留空时用 `os.startfile` 直接启动执行程序，不匹配扩展名 |
| 控制台模式 | 单文件 + 显示控制台用 `subprocess.run()` 阻塞执行，输出直接进新控制台 |
| Win11 菜单 | 接受传统菜单折叠进「显示更多选项」，不做 COM 扩展 |
| 菜单图标 | 打包 exe 内嵌闪电图标，注册表写 `Icon` 值 |
| 工作目录 | 子进程 `cwd` 默认为**命令可执行文件所在目录** |
| 项目管理 | uv（`pyproject.toml` + `uv.lock` + `.python-version`） |
| 打包 | PyInstaller **onedir + windowed**，产物 `ContextCLI.exe` |
| 注册表范围 | 仅 `HKCU`，无管理员权限 |
| 界面语言 | 中文 |

## 4. 技术栈与环境

- Python 3.12（uv 管理的 CPython 3.12.12，已验证自带 tkinter 8.6）
- uv 0.9.28
- GUI：tkinter + ttk（标准库）
- YAML：PyYAML
- 注册表：`winreg` + `ctypes`（`SHChangeNotify`）
- 子进程：`subprocess`
- 测试：pytest
- 打包：PyInstaller

### 4.1 uv 配置

`pyproject.toml` 关键内容：

```toml
[project]
name = "context-cli"
requires-python = ">=3.12"
dependencies = ["pyyaml>=6.0"]

[project.scripts]
context-cli = "context_cli.__main__:main"

[dependency-groups]
dev = ["pytest>=8.0", "pyinstaller>=6.0"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/context_cli"]
```

常用命令：

| 用途 | 命令 |
|---|---|
| 同步依赖 | `uv sync` |
| 启动 GUI | `uv run context-cli` |
| 模拟右键调用 | `uv run context-cli --run <id> "<path>"` |
| 运行测试 | `uv run pytest` |
| 打包 | `uv run pyinstaller packaging/context_cli.spec --noconfirm` |

### 4.2 存储位置

```
%APPDATA%\ContextCLI\commands.yaml     # 命令配置（另有 .bak 备份）
%APPDATA%\ContextCLI\state.yaml        # 注册状态（预留）
%APPDATA%\ContextCLI\logs\             # 每次运行日志，保留 1 天
```

## 5. 总体架构

```
资源管理器右键
   │  ContextCLI.exe --run "<command_id>" "<选中路径>"
   ▼
┌────────────────┐        ┌──────────────────────────────────┐
│  __main__.py   │───────▶│ Runner（无管理界面）              │
│ 参数分派        │        │ 1. 读取 YAML，按 id 查找命令      │
└───────┬────────┘        │ 2. 单文件：校验扩展名             │
        │ 无参数           │ 3. 文件夹：扫描并按扩展名过滤      │
        ▼                 │ 4. 规划输出路径、展开变量          │
┌────────────────┐        │ 5. 顺序执行子进程                  │
│ GUI 管理端      │        │ 6. 控制台/进度窗口 + 日志 + 失败提示│
│ 列表/表单/测试  │        └──────────────────────────────────┘
│ 注册/卸载       │
└───────┬────────┘
        ▼
 models / storage / variables / jobs / runner / registry
```

**设计原则**

- 单一可执行文件、双模式：无参数进 GUI，`--run` 进 Runner。
- 业务逻辑（core）与界面（ui）分离，便于单元测试。
- 所有路径、命令执行均使用 Unicode；不经过 shell。
- 配置读取失败、变量未知、可执行文件缺失等错误必须在执行前明确指出。

## 6. 数据模型与 YAML

### 6.1 YAML 示例

```yaml
version: 1
settings:
  menu_title: 快捷执行
commands:
  - id: "vid2mp4"
    name: "视频转 MP4"
    enabled: true
    comment: "ffmpeg 转码 H.264；-crf 23 控制画质，越小越清晰"
    extensions: ["mp4", "mkv", "avi", "mov"]
    executable: "C:\\ffmpeg\\bin\\ffmpeg.exe"
    arguments: '-hide_banner -i "{input}" -c:v libx264 -crf 23 "{output}"'
    recurse: true
    output_dir: ""
    output_name: "{input_name}.mp4"
    keep_structure: true
    show_console: true
```

### 6.2 字段说明

| 字段 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `id` | string | 自动生成 | 稳定唯一 ID；菜单调用靠它定位，重命名不影响 |
| `name` | string | 必填 | 右键菜单显示名 |
| `enabled` | bool | `true` | 是否注册到菜单、是否参与执行 |
| `comment` | string | 空 | 用途与参数说明，仅 GUI 展示 |
| `extensions` | list[str] | 必填 | 扩展名列表，不带点，大小写不敏感；留空 = 所有文件 |
| `executable` | string | 必填 | 完整路径或 PATH 中的命令名 |
| `arguments` | string | 必填 | 参数模板；非空时必须包含至少一个输入变量，留空 = 直接启动不传参 |
| `directories_only` | bool | `false` | 勾选后仅出现在文件夹菜单，不处理单个文件 |
| `output_dir` | string | 空 | 空 = 源文件目录；可写绝对/相对路径，支持输入变量 |
| `output_name` | string | `{input_name}_out.{input_ext}` | 输出文件名模板，不支持目录分隔符 |
| `keep_structure` | bool | `true` | 指定输出目录且递归时保留相对子目录结构 |
| `show_console` | bool | `true` | 单文件执行时是否弹出控制台 |

### 6.3 扩展名规则

- 必填，至少一个；空列表不再表示“全部文件”，避免 `*` 菜单与扩展名菜单重复。
- 只支持 Windows 最终后缀：`mp4`、`mkv`、`jpg`；不支持 `tar.gz` 这类复合后缀。
- 存储时统一小写、去除前导点、去重。
- 匹配规则：文件名 `.lower().endswith("." + ext)`，大小写不敏感。
- 含 `\ / : * ? " < > |` 等非法字符的扩展名直接判为配置错误。

## 7. 变量系统

### 7.1 变量表

| 变量 | 含义 | 示例 |
|---|---|---|
| `{input}` | 当前输入文件完整路径 | `D:\素材\a.mkv` |
| `{input_name}` | 文件名，不含路径与最终后缀 | `a` |
| `{input_ext}` | 最终后缀，不含点 | `mkv` |
| `{input_dir}` | 输入文件所在目录 | `D:\素材` |
| `{output_dir}` | 规划后的输出目录 | `D:\输出` |
| `{output_name}` | 模板展开后的输出文件名 | `a.mp4` |
| `{output}` | 输出完整路径 | `D:\输出\a.mp4` |

### 7.2 展开规则

- 单次正则替换，替换结果不会被再次展开，避免路径中花括号引发递归替换。
- 未知变量在**规划阶段**报错，不启动进程。
- 输入变量用于生成输出模板；输出变量不可再用于输出模板自身。
- 变量原样展开，引号由参数模板负责；默认示例均使用双引号包裹路径。
- GUI 提供「预览」展示最终命令行，执行前可核对。
- 文件夹输入时，每个匹配文件分别生成一组变量。

## 8. 输出路径规划

1. `output_dir` 为空：输出到输入文件所在目录。
2. `output_dir` 为绝对路径：直接使用。
3. `output_dir` 为相对路径：相对于“选中的根”（文件输入取其父目录，文件夹输入取该文件夹）。
4. 文件夹 + 递归 + `keep_structure=true`：在输出目录下保留相对子目录结构。
5. `output_name` 展开后不得为空，不得含路径分隔符或 Windows 非法字符，不得以空格/点结尾。
6. 输出目录在真正执行前自动创建。
7. 同名文件是否覆盖由 CLI 自己决定，程序不额外询问。
8. 若展开后的 `{output}` 与 `{input}` 完全相同，GUI 在保存/测试时给出警告（不强制阻止）。

## 9. 右键菜单设计

### 9.1 注册表结构

文件（每个有启用命令的扩展名一份）：

```
HKEY_CURRENT_USER\Software\Classes\SystemFileAssociations\.mp4\shell\ContextCLI
    MUIVerb          = "快捷执行"
    SubCommands      = ""
    MultiSelectModel = "Player"
    Icon             = "C:\...\ContextCLI.exe,0"
    └─ shell\0000_vid2mp4
         MUIVerb          = "视频转 MP4"
         MultiSelectModel = "Player"
         └─ command
              (默认) = "C:\...\ContextCLI.exe" --run "vid2mp4" "%1"
```

文件夹：

```
HKEY_CURRENT_USER\Software\Classes\Directory\shell\ContextCLI
    MUIVerb          = "快捷执行"
    SubCommands      = ""
    MultiSelectModel = "Player"
    Icon             = "C:\...\ContextCLI.exe,0"
    └─ shell\<index前缀>_<command_id>
         ...
         └─ command
              (默认) = "C:\...\ContextCLI.exe" --run "<id>" "%1"
```

- 注册键名固定使用 `ContextCLI`，显示名用 `MUIVerb=快捷执行`，改名不影响注册结构。
- 子键名用 `{索引:04d}_{命令ID}` 前缀锁定菜单显示顺序与命令列表一致。
- `MultiSelectModel=Player`：多选文件时资源管理器按文件逐个启动本程序；程序内部用命名互斥体合并同一批启动（首个实例等待收集，其余实例把路径写入 `%APPDATA%\ContextCLI\pending\<命令ID>\` 后退出）。
- 文件夹没有可静态判断的扩展名，因此列出全部启用命令；Runner 扫描后若无匹配文件，提示“未找到匹配文件”。
- 任一扩展名没有启用命令时，不创建该扩展名的菜单，实现“不匹配就不出现”。
- 注册/卸载后调用 `SHChangeNotify(SHCNE_ASSOCCHANGED)` 刷新资源管理器。
- 重新注册前清理所有旧的 `ContextCLI` 键，包括已删除扩展名留下的残留。
- 卸载时扫描并删除 `SystemFileAssociations\*\shell\ContextCLI`、`Directory\shell\ContextCLI`，不依赖本地状态文件。
- 开发模式（未打包）注册前缀为 `.venv\Scripts\pythonw.exe -m context_cli`，避免控制台窗口；正式使用以打包 exe 为准。

### 9.2 菜单文本

- 子菜单名 = 命令 `name`。
- `&` 按 Windows 菜单规则转义为 `&&`，避免被当作快捷键。
- 命令 ID 使用稳定随机串，只出现在注册表键名与命令行参数中。

### 9.3 Windows 11 限制

Windows 11 默认把传统注册表菜单折叠到「显示更多选项」（Shift+F10）。v1 接受该行为，不做 COM Shell 扩展；Win10 直接显示。

## 10. 执行引擎

### 10.1 输入处理

- 文件输入：校验扩展名；不匹配则报错退出。
- 文件夹输入：按 `recurse` 决定顶层或递归扫描，过滤扩展名，按路径排序。
- 无匹配文件：提示用户，不启动任何进程。
- 执行顺序：串行，避免多个 ffmpeg 同时占满 CPU。

### 10.2 命令构造

1. 解析 `executable`：完整路径优先；否则 `shutil.which()` 搜索 PATH；失败则报错。
2. `cwd` = 可执行文件所在目录。
3. 参数模板展开变量。
4. 最终命令行 = 引号包裹的可执行文件路径 + 空格 + 展开后的参数。
5. 使用 `subprocess.Popen(command_line, shell=False)`；不解析管道与重定向。

### 10.3 执行场景

执行前先用 `MessageBoxW` 列出待处理文件数量与文件名（最多 12 个，超出显示总数），用户确认后才开始。

| 场景 | 输出方式 | 失败反馈 |
|---|---|---|
| 参数为空 | `os.startfile` 直接启动执行程序，不传参、不匹配扩展名 | 启动失败弹窗 |
| 单文件 + `show_console=true` | `subprocess.run` + `CREATE_NEW_CONSOLE`，输出直接进新控制台 | 弹窗显示退出码与日志路径 |
| 单文件 + `show_console=false` | 管道捕获，写日志 | 弹窗显示退出码与日志路径；成功静默 |
| 多选文件 / 文件夹 | 内置 Tk 进度窗口：先列完整清单，点「开始执行」后运行，实时输出、进度、停止按钮 | 汇总成功/失败数量，保留窗口供查看 |

- 停止操作使用 `taskkill /PID <pid> /T /F` 结束进程树（仅捕获模式需要）。
- GUI 测试面板始终捕获输出并实时显示，不受 `show_console` 限制。
- 每次运行生成独立日志：时间、命令、工作目录、最终命令行、输出、退出码、耗时。
- 日志保留 1 天；每次运行前自动清理过期日志，应用启动时也会清理。

## 11. GUI 设计

```
┌ 快捷执行 CLI 管理器 ─────────────────────────────────────────┐
│ [新建] [复制] [删除] [上移] [下移]  [导入 YAML] [导出 YAML]    │
│ ┌─命令列表────────┬─命令编辑───────────────────────────────┐ │
│ │ ☑ 视频转 MP4     │ 名称 [____]  启用 ☑                     │ │
│ │ ☐ 图片压缩       │ 注释 [_____________________________]   │ │
│ │ ☑ 音频提取       │ 扩展名 [mp4, mkv, avi]                  │ │
│ │                 │ 执行程序 [ffmpeg.exe_______] [浏览]     │ │
│ │                 │ 参数   [___________________________]   │ │
│ │                 │ 变量按钮: {input} {input_name} ...      │ │
│ │                 │ 输出目录 [默认=源文件目录____] [浏览]    │ │
│ │                 │ 文件名模板 [{input_name}.mp4________]   │ │
│ │                 │ ☑ 遍历子文件夹  ☑ 保留目录结构  ☑ 控制台│ │
│ └─────────────────┴────────────────────────────────────────┘ │
│ ┌─测试验证──────────────────────────────────────────────────┐ │
│ │ 样本 [________________] [选文件] [选文件夹]               │ │
│ │ 预览 ffmpeg -i "D:\a.mkv" ... "D:\a.mp4"                 │ │
│ │ [预览] [运行测试] [停止] [清空]   输出: ................. │ │
│ └──────────────────────────────────────────────────────────┘ │
│ [保存] [注册右键菜单] [移除右键菜单]     状态: 已注册 ✓        │
└──────────────────────────────────────────────────────────────┘
```

### 11.1 交互规则

- 测试验证区域默认折叠，点击「▶ 测试验证」展开，点击「▼ 收起测试验证」收回；测试运行中不允许收起。
- 命令列表：启用状态、名称、扩展名；双击启用列切换，双击行加载。
- 工具栏「复制」：基于当前表单内容创建副本，插入原命令之后，名称自动追加「副本」并避开重名；副本同样需要保存后生效。
- 编辑表单：支持变量一键插入参数框；执行程序与输出目录提供浏览按钮。
- 测试面板「清空」：清除预览和输出文本，保留样本路径与状态，便于排除上次结果重新调试。
- 切换命令/新建/删除/关闭窗口时，检测未保存修改，询问“保存/放弃/取消”。
- 保存：校验 → 原子写 YAML → 若之前已注册则自动重新注册。
- 测试：使用**当前表单内容**（不要求先保存），支持文件或文件夹样本，先预览匹配数量与命令行，再执行。
- 导入 YAML：确认后替换当前列表；提示“配置中的命令将被执行”。
- 导出 YAML：先应用当前表单，再另存。
- 状态栏：未注册 / 已注册 / 已过期（exe 路径或菜单内容变化），可一键重新注册。

### 11.2 校验规则

- 名称、执行程序、扩展名、参数必填。
- 参数必须包含至少一个输入变量。
- 未知变量直接报错。
- 输出模板不得生成非法文件名。
- 注册前解析所有启用命令的可执行文件；任一失败则列出问题并中止注册。
- 注册表写入失败时显示具体键路径与系统错误。

## 12. 日志与错误处理

- 日志目录：`%APPDATA%\ContextCLI\logs\`。
- 文件名：`YYYYMMDD-HHMMSS-<命令名>-<id>.log`。
- 记录：配置读取结果、匹配文件数、每个任务的输入/输出/工作目录/命令行/退出码/耗时、捕获输出。
- 控制台模式下无法捕获子进程输出，日志记录元数据并注明“输出见控制台”。
- 失败弹窗使用 Win32 `MessageBoxW`，不依赖 Tk，能在 pythonw 下工作。
- YAML 解析失败、命令 ID 不存在、可执行文件缺失、输出目录创建失败等均在启动子进程前报错。

## 13. 目录结构

```
D:\Git-Project\context_cli\
├─ PLAN.md
├─ README.md
├─ pyproject.toml
├─ uv.lock
├─ .python-version
├─ .gitignore
├─ examples/
│  └─ commands.example.yaml
├─ src/context_cli/
│  ├─ __init__.py
│  ├─ __main__.py          # 入口：GUI / --run / --register / --unregister
│  ├─ config.py            # 路径与常量
│  ├─ models.py            # Command / AppConfig
│  ├─ variables.py         # 变量解析与展开
│  ├─ storage.py           # YAML 读写、校验、备份、迁移
│  ├─ jobs.py              # 文件收集、输出规划、命令行构造
│  ├─ runner.py            # 子进程执行、日志、流式输出
│  ├─ registry.py          # 右键菜单注册/卸载/状态检测
│  └─ ui/
│     ├─ __init__.py
│     ├─ main_window.py    # 主窗口与状态管理
│     ├─ command_form.py   # 命令编辑表单
│     ├─ scrollable_frame.py # 可滚动表单容器
│     ├─ test_panel.py     # 测试与实时输出
│     └─ progress_window.py# 批量执行进度窗口
├─ tests/
│  ├─ test_variables.py
│  ├─ test_models.py
│  ├─ test_storage.py
│  ├─ test_jobs.py
│  ├─ test_runner.py
│  └─ test_registry.py
└─ packaging/
   ├─ context_cli.spec
   └─ launcher.py
```

## 14. 测试与验收

### 14.1 自动化测试

- 变量：基础替换、未知变量、单次替换、路径含花括号。
- 模型：扩展名归一化、大小写匹配、必填校验、输入变量检查。
- 存储：YAML 往返、缺失文件、损坏 YAML、备份、重复 ID 修复。
- 规划：单文件匹配/不匹配、文件夹递归/非递归、扩展名过滤、输出目录默认/绝对/相对、保留结构、非法输出名。
- 执行：用当前 Python 解释器作为测试命令，验证 cwd=可执行文件目录、参数传递、退出码、输出捕获、日志生成。
- 注册表：仅测试扩展名映射、命令行字符串、菜单文本转义；**自动化测试不写真实注册表**。

### 14.2 手动验收清单

1. `uv sync` 成功；`uv run context-cli` 打开 GUI。
2. 新建 ffmpeg 命令，测试单文件转码成功。
3. 测试文件夹：非递归/递归、自定义输出目录、保留目录结构。
4. 注册右键菜单；资源管理器中匹配扩展名出现「快捷执行」，不匹配不出现。
5. 从右键菜单执行单文件与文件夹，观察控制台/进度窗口与日志。
6. 修改命令名称或扩展名并保存，菜单自动更新。
7. 移除右键菜单，确认相关注册表键清理干净。
8. 导出/导入 YAML，重启程序配置恢复。
9. 打包 `ContextCLI.exe`，重复步骤 4-7。

## 15. 里程碑

| 阶段 | 内容 | 状态 |
|---|---|---|
| M0 | 需求确认与规划定稿 | 完成 |
| M1 | uv 骨架、数据模型、YAML、变量引擎、单元测试 | 完成（54 项测试通过） |
| M2 | 文件收集与输出规划、执行引擎、`--run` 模式 | 完成（单文件/文件夹冒烟通过） |
| M3 | ttk GUI：列表、表单、测试面板 | 完成（预览→执行→实时输出链路通过） |
| M4 | 注册表注册/卸载/状态检测/菜单刷新 | 完成（注册→检测→卸载无残留） |
| M5 | PyInstaller 打包、端到端验收、README | 完成（onedir 构建与打包版 Runner 通过） |

## 16. 风险与限制

| 风险 | 应对 |
|---|---|
| Win11 菜单被折叠 | 已确认接受；README 说明 Shift+F10 |
| 资源管理器菜单缓存 | 写注册表后调用 `SHChangeNotify`；极端情况重启 explorer |
| PyInstaller 杀软误报/启动慢 | 使用 onedir、不做 UPX 压缩 |
| 中文/空格/长路径 | 全程 Unicode、预览兜底；>260 字符路径需后续加 manifest |
| CLI 输出编码不一致 | 按 UTF-8 → 本地代码页 → mbcs 顺序尝试解码，失败用替换字符 |
| 复合后缀 `tar.gz` | v1 不支持，仅按最终后缀匹配 |
| 导入的 YAML 含恶意命令 | 导入时明确警告；程序本身不联网、不提权 |
| 注册表残留 | 卸载采用扫描清理；重新注册前先清理 |
| 开发模式注册依赖 `.venv` | GUI 标注开发模式；发布使用打包 exe |

## 17. 后续可扩展

- 多选合并/队列执行。
- Windows 11 一级现代菜单（IExplorerCommand COM 扩展）。
- 每命令自定义工作目录。
- 可选 shell 模式（管道、重定向）。
- 所有文件通配（需解决 `*` 菜单与扩展名菜单的去重）。
- 复合后缀支持。
- 菜单图标、命令分组、拖拽排序。
- 配置云同步/版本迁移。

## 18. 规划修订记录

| 日期 | 修订 |
|---|---|
| 2026-11-16 | 定稿：单选、输出变量、控制台+失败弹窗、Win11 折叠、uv、cwd=命令目录 |
| 2026-11-16 | 明确扩展名列表必填（取消“空=全部文件”）；v1 不支持复合后缀 |

## 19. 实施结果（2026-11-16）

- `uv sync` 成功；Python 3.12.12 + tkinter 8.6，venv 中存在 `pythonw.exe`。
- `uv run pytest -q`：**54 passed**。
- 单文件 Runner：临时配置调用 Python CLI，验证参数传递、`cwd=可执行文件目录`、输出路径规划与日志写入。
- 文件夹批量：内置进度窗口处理 2 个文件，成功后自动关闭，退出码 0。
- GUI：主窗口正常创建；测试面板完成“预览 → 执行 → 实时输出 → 完成汇总”。
- 注册表闭环：临时菜单「快捷执行测试」注册成功，状态为 `registered`，文件命令指向打包 exe，文件夹标题正确；卸载后状态为 `not_registered`，无残留。
- PyInstaller：onedir + windowed 构建成功；`dist/ContextCLI/ContextCLI.exe --run` 冒烟通过。
- 布局调整：测试验证区域默认折叠、可展开；表单支持垂直滚动；状态栏固定可见，不再被主区域挤出窗口。
- 高 DPI 适配：启动时声明系统级 DPI 感知，按实际 DPI 设置 `tk scaling`；主窗口、批量进度窗口、Treeview 列宽/行高/表头内边距均按缩放系数计算。Treeview 行高改为基于 `TkDefaultFont` 行高，修复高分辨率下命令列表只显示上半行的问题。
- 高 DPI 冒烟：当前 125% 缩放（120 DPI）下窗口 1475×930，行高 30 px > 字体行高 20 px；模拟 150%（144 DPI）时窗口 1770×900，行高 36 px > 行高 24 px；状态栏可见、测试区默认折叠、表单可滚动。
- 体验调整（2026-11-17）：测试验证的预览与输出区改用可拖动分隔条，预览高度可调；命令列表为空或未选中命令时右侧表单禁用，新建命令后自动启用；日志保留期改为 1 天，每次运行前自动清理过期日志。
- 体验调整（2026-11-17）：工具栏新增「复制」，基于当前表单创建副本并插入原命令之后；测试面板新增「清空」，一键清除预览与输出。
- 功能扩展（2026-11-18）：控制台模式改用 `subprocess.run()`；参数为空用 `os.startfile` 直接启动；支持多选文件（互斥体合并，`MultiSelectModel=Player`，73 项测试含 3 进程合并冒烟）；执行前弹窗列出待处理文件清单；右键菜单与 exe 嵌入闪电图标（`packaging/make_icon.py` 生成）。
- 当前注册状态：`not_registered`；临时测试菜单「快捷执行测试」已清理，无残留。
- 未完成的人工验收：受自动化环境限制，尚未在资源管理器中实际右键点击菜单；建议发布前手动确认一次菜单显示与执行。
- 下一步：完成资源管理器人工验收；确认后可发布，或按 §17 继续扩展。

