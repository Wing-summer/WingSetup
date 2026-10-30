# 使用与配置 / Usage and configuration

## 命令行 / Command line

```sh
wingsetup check -c examples/basic/package.yml --all
wingsetup run -c examples/basic/package.yml --target appimage
wingsetup run -c examples/basic/package.yml --target flatpak-binary
wingsetup run -c examples/basic/package.yml --target flatpak-sdk
```

`--target` 可重复，按指定顺序执行；`--all` 按 YAML 顺序执行。首个失败停止后续目标。
check 不创建工作目录，也不导入项目 Hook；自定义后端仍需加载，其导入必须无副作用。

Repeat `--target` to select targets in order; `--all` follows YAML order. The first
failure stops remaining targets. Check creates no workspace and imports no project
hooks, but custom backends must still be loaded and must have side-effect-free imports.

每次运行创建 `workspace/<target>-<random>/`，保留构建目录、部署目录、命令日志和失败日志。
Flatpak 仓库保存在其中的 repository；产物和 `.sha256` 位于 `output/<target>/`。
已有同名产物会报错；不提供断点续跑，工作目录需手动清理。

Each run creates `workspace/<target>-<random>/`, retaining build and deployment
directories, command logs and failure logs. Flatpak repositories are retained in
repository; bundles and `.sha256` files go to `output/<target>/`. Existing outputs
cause an error. There is no resume support; clean work directories manually.

## 配置模型 / Configuration model

参见[基础配置](../examples/basic/package.yml)、[基础 manifest](../examples/basic/org.example.Hello.yml)
和 [Qt 配置](../examples/qtwidgets/package.yml)。
See the [basic configuration](../examples/basic/package.yml), [basic manifest](../examples/basic/org.example.Hello.yml)
and [Qt configuration](../examples/qtwidgets/package.yml).

| 区域 / Section | 字段与含义 / Fields and meaning |
| --- | --- |
| 根 / Root | schema_version（必须为 1 / must be 1）、application、project、targets、workspace、output |
| application | id（反向域名 / reverse DNS）、name（文件名安全短名 / filename-safe short name）、version、summary、license、executable、desktop、icon（仅 Linux 桌面后端必需 / required only by Linux desktop backends） |
| project | source、hooks（`file.py:ClassName`）、commands（参数列表的列表 / list of argument lists）、resources、tools |
| resource | source、destination、relative_to（root/prefix/app/resources/libraries/plugins） |
| target | backend、arch、options、resources、platform、executable（目标覆盖 / target override）、tools |
| AppImage options | linuxdeploy、appimagetool、plugins、libraries、environment、dependency_dirs、runtime_file |
| Flatpak options | mode（binary/sdk）、runtime、sdk、runtime_version、branch（默认 / default stable）、installation（默认 / default user）、finish_args、manifest |

配置路径相对 YAML，manifest 的 source 路径相对 manifest。入口和资源 source、AppImage
libraries 允许以 `{source}/`、`{build}/`、`{work}/` 开头。入口指构建产物，不是安装位置；
check 允许其尚未生成。命令默认在 project.source 执行，展开 `{source}`、`{build}`、
`{work}`、`{deploy}`、`{prefix}`、`{app}`、`{resources}`、`{libraries}`、`{plugins}`；复杂 shell 行为应显式使用脚本或 `sh -c`。

Configuration paths are relative to YAML; manifest source paths are relative to
the manifest. Executables, resource sources and AppImage libraries may start with
`{source}/`, `{build}/` or `{work}/`. The executable denotes build output, not an
installed location, and need not exist during check. Commands run in project.source
by default and expand `{source}`, `{build}`, `{work}`, `{deploy}`, `{prefix}` and
`{app}`, `{resources}`, `{libraries}` and `{plugins}`. Use a script or explicit `sh -c` for shell behavior.

拒绝未知字段、错误类型和不安全的复制目标；版本必须为字符串。原生目标支持本机
x86_64/aarch64，macOS 还支持 universal2 校验，配方支持 any。desktop 的 Exec 以入口文件名开头，Icon 等于应用 ID；
图标使用 SVG 或 256×256 PNG。名称与版本须满足文件名安全校验。

Unknown fields, invalid types and unsafe copy destinations are rejected. Versions
must be strings. Native targets use x86_64/aarch64, macOS also supports universal2, and recipes support any. Desktop Exec
starts with the executable filename and Icon equals the application ID. Use SVG
or 256×256 PNG icons. Names and versions must pass filename-safety validation.

## 资源与 Hook / Resources and hooks

| relative_to | AppImage | Flatpak |
| --- | --- | --- |
| root（默认 / default） | AppDir | 构建根目录 / build root |
| prefix | AppDir/usr | files（运行时 / at runtime /app） |
| app | AppDir/usr/bin | files/bin（运行时 / at runtime /app/bin） |

```yaml
project:
  resources:
    - source: '{build}/lang'
      destination: lang
      relative_to: app
```

公共资源先于 `targets.<name>.resources` 复制，目标规则可覆盖公共文件，随后调用项目 deploy。
目标须保持在部署树内；拒绝绝对目标、`..` 和目标树中的符号链接，源链接按内容复制。
Hook 是可信宿主代码，不是安全沙箱。

Common resources are copied before `targets.<name>.resources`; target rules may
overwrite common files, followed by project deploy. Destinations must remain in
the deployment tree. Absolute destinations, `..` and destination-tree symlinks
are rejected; source links are dereferenced. Hooks are trusted host code, not a sandbox.

用户继承 ProjectHooks，通过 `project.hooks: hooks.py:Hooks` 加载。每阶段执行
`pre_<stage> → backend.<stage> → after_<stage>`，共有八个前后 Hook；任何失败都跳过
本阶段 after 和后续阶段。pre_prepare 时构建和部署目录尚未初始化。

Subclass ProjectHooks and load it with `project.hooks: hooks.py:Hooks`. Each stage
runs `pre_<stage> → backend.<stage> → after_<stage>`, giving eight lifecycle hooks.
Any failure skips that stage's after hook and all later stages. Build and deployment
directories are not initialized during pre_prepare.

AppImage 和 Flatpak binary 先执行 commands，再调用项目 build。deploy 复制入口、
desktop、图标和资源，调用项目 deploy，然后完成后端部署。SDK 模式由 manifest 编译，
不执行 commands 或项目 build；前后 Hook 保留，项目 deploy 在 SDK 编译后、cleanup/finish 前运行。
所有 Python Hook 均在宿主运行。

AppImage and Flatpak binary execute commands before project build. Deploy copies
the executable, desktop file, icon and resources, invokes project deploy, then
finishes backend deployment. SDK mode builds through the manifest without commands
or project build; lifecycle hooks still run, and project deploy runs after SDK
compilation but before cleanup/finish. All Python hooks run on the host.

`ctx.prefix_dir`、`ctx.app_dir` 和 `ctx.copy_app()` 支持可执行文件相邻资源。CMake 项目可在
Hook 中执行 `cmake --install {build} --prefix {prefix}`；绝对安装规则不会因此自动重定位。
示例见 [Qt Hook](../examples/qtwidgets/hooks.py)。

Use `ctx.prefix_dir`, `ctx.app_dir` and `ctx.copy_app()` for executable-adjacent
resources. CMake projects may run `cmake --install {build} --prefix {prefix}` in a
hook; this does not relocate absolute install rules. See the [Qt hook](../examples/qtwidgets/hooks.py).

自定义后端继承 PackageBackend，实现 check、deploy、package，返回 Artifact 元组，
必要时覆盖 prepare/build。通过 `backend: custom_backend.py:ArchiveBackend` 加载，
参见[示例](../examples/basic/custom_backend.py)。新增 options 须扩展类型模型和解析器，不接受任意未校验字典。

Custom backends subclass PackageBackend, implement check, deploy and package,
and return an Artifact tuple; override prepare/build as needed. Load one with
`backend: custom_backend.py:ArchiveBackend`; see the [example](../examples/basic/custom_backend.py).
New options must extend typed models and parsing rather than accept unchecked dictionaries.

## 后端依赖 / Backend requirements

AppImage 需要 linuxdeploy、appimagetool、desktop-file-validate，以及每个启用的
`linuxdeploy-plugin-<name>`。含 `/` 的工具路径相对 YAML，否则在 PATH 查找。
`options.environment` 将字符串值传给 linuxdeploy；Qt 使用匹配构建的 QMAKE。
`dependency_dirs` 是部署根目录内的目录，用于 `--deploy-deps-only` 扫描动态加载的 ELF，
例如 `.wingplg`。额外共享库使用 libraries；普通资源复制不等于依赖部署。

AppImage requires linuxdeploy, appimagetool, desktop-file-validate and every enabled
`linuxdeploy-plugin-<name>`. Tool paths containing `/` are relative to YAML; other
names use PATH. `options.environment` passes string values to linuxdeploy; Qt
requires QMAKE matching the build. `dependency_dirs` names deployed directories
for `--deploy-deps-only` scanning of dynamically loaded ELF files such as `.wingplg`.
Use libraries for additional shared libraries; copying resources does not deploy their dependencies.

Flatpak 需要 flatpak 和 desktop-file-validate，SDK 模式另需 flatpak-builder。示例使用
system 安装的 KDE 6.10 Platform/SDK。扩展、base 和额外依赖需用户预先准备，框架不添加
`--install-deps-from`；manifest 仍可能下载声明的构建源码。

Flatpak requires flatpak and desktop-file-validate, plus flatpak-builder in SDK mode.
Examples select system-installed KDE 6.10 Platform/SDK. Prepare extensions, bases
and other dependencies yourself; the framework never adds `--install-deps-from`,
although manifests may download declared build sources.

binary 使用 build-init/build-finish，SDK 使用 build-only/finish-only；两者最终均
build-export/build-bundle。SDK manifest 的应用 ID、runtime、SDK、版本和 command 须与
YAML 匹配；SDK 权限写入 manifest，binary 权限写入 finish_args，默认不授权网络和宿主目录。

Binary mode uses build-init/build-finish; SDK mode uses build-only/finish-only.
Both use build-export/build-bundle. SDK manifest application ID, runtime, SDK,
version and command must match YAML. SDK permissions belong in the manifest;
binary permissions use finish_args. Network and host directories are not granted by default.

binary 的 ABI 兼容性由项目保证；框架检查 ELF 架构和执行权限，不提供完整 ABI 分析。
`.flatpak` 不内含 runtime。Qt SDK 模式使用 runtime 的 Qt，不混入宿主 Qt 插件。
平台签名与新后端见[架构文档](architecture.md)。自动更新、Flathub 发布和 GUI 不属于当前范围。

Projects must ensure binary ABI compatibility; the framework checks ELF architecture
and executable permissions, not complete ABI compatibility. `.flatpak` bundles
exclude runtimes. Qt SDK mode uses runtime Qt without host Qt plugins. See [architecture](architecture.md) for platform signing and additional backends.
Automatic updates, Flathub publishing and a GUI remain outside the current scope.

## 验证 / Validation

```sh
.venv/bin/pyright
.venv/bin/python -m pytest -q
```

单元测试替代外部命令，不能代替真实打包。真实验证需检查包、校验值和启动行为。
AppImage 可用 `--appimage-extract-and-run`；Flatpak 安装测试需用户明确授权后再执行。
Qt 资源验证参见 [Qt 示例](../examples/qtwidgets/README.md)，本地记录见[开发文档](development.md)。

Unit tests replace external commands and cannot substitute for real packaging.
Validate bundles, checksums and launch behavior separately. AppImage supports
`--appimage-extract-and-run`; Flatpak installation tests require explicit user
authorization. See the [Qt example](../examples/qtwidgets/README.md) and [local validation record](development.md).

## 新后端与发现接口 / Additional backends and discovery

`list --json` 不执行工具或导入项目 Hook，可供 CI 查询目标的 platform、arch、layout 和 kind。
`--compatible` 按本机 OS 筛选目标；它不代替依赖检查。Windows/macOS 目标可以省略
application.desktop/icon，通过 target.executable 指定 .exe 或 .app。配方可以省略真实二进制。

`list --json` runs no tools or project hooks and exposes platform, arch, layout and
kind for CI. `--compatible` filters by host OS without replacing dependency checks.
Windows/macOS targets may omit application.desktop/icon and use target.executable
for .exe or .app. Recipes do not require a real binary.

```sh
wingsetup list -c examples/qtwidgets/package.yml --json
wingsetup check -c examples/qtwidgets/package.yml --all --compatible
wingsetup run -c examples/basic/extended.yml --target aur-release --target scripts
```

| options 区域 / Options section | 字段 / Fields |
| --- | --- |
| deb | package_name、maintainer、depends、section、revision、control_files |
| inno | formats（inno/zip）、windeployqt、iscc、script、qt_args |
| macos | formats（app/zip/dmg）、macdeployqt、extra_executables、sign_identity_env、notary_profile_env |
| aur | recipe（包含 PKGBUILD 的目录 / directory containing PKGBUILD）、generate_srcinfo（默认 true / defaults to true） |
| makeself | payload、startup、tool、suffix（run/sh）、interpreter（sh/bash，默认 sh / defaults to sh） |
| script | recipe、entry（默认 install.sh / defaults to install.sh） |

AUR 的 generate_srcinfo=false 要求 recipe 已含 .SRCINFO；配方必须可信。Inno 项目模板支持
@PAYLOAD@、@APP_ID@、@APP_NAME@、@VERSION@、@EXECUTABLE@。macOS 的 extra_executables
相对 .app 根目录；其他路径相对 YAML。签名环境变量缺失会失败，而不是静默输出未签名包。

AUR generate_srcinfo=false requires an existing .SRCINFO in the trusted recipe.
Inno project templates support @PAYLOAD@, @APP_ID@, @APP_NAME@, @VERSION@ and
@EXECUTABLE@. macOS extra_executables are relative to the .app root; other paths
are relative to YAML. Missing signing variables fail instead of silently emitting
an unsigned package.

资源 relative_to 还支持 resources、libraries、plugins，含义见[布局表](architecture.md)。
每次运行的 artifacts.json 区分 package 与 recipe；CI 集成见 [ci.md](ci.md)。

Resource relative_to additionally supports resources, libraries and plugins; see
the [layout table](architecture.md). Each run's artifacts.json distinguishes
package from recipe; see [CI integration](ci.md).

project.tools 声明宿主构建所需工具，target.tools 声明目标额外工具；名称在 PATH 中查找，
带路径分隔符的值相对 YAML。check 和 prepare 均检查这些声明。配方及 Flatpak SDK 模式
跳过 project.tools，因为它们不执行宿主项目构建，但始终检查 target.tools。

project.tools declares host build tools; target.tools declares additional target
requirements. Names use PATH, while values containing path separators are relative
to YAML. Both check and prepare validate them. Recipes and Flatpak SDK mode skip
project.tools because they do not build the host project; target.tools always applies.

## 只读脚本路径 / Read-only script paths

Hook 和自定义后端可导入全局 `paths` 对象，属性均为只读 `Path`。属性随当前目标解析，
不会创建目录；仅在 `run_target` 内（包括扩展加载和前后 Hook）可访问，运行结束或失败后
恢复外层上下文，运行外访问报错。不要在导入时缓存某一个路径供后续目标复用。

Hooks and custom backends can import the global `paths` object. Its read-only
properties return `Path` values resolved for the current target without creating
directories. They are available only inside `run_target`, including extension
loading and lifecycle hooks. Completion or failure restores the enclosing context;
access outside a run raises an error. Do not cache an individual path at import
time for reuse across later targets.

```python
from wingsetup import BuildContext, ProjectHooks, paths


class Hooks(ProjectHooks):
    """Deploy project-owned generated resources beside the entry point."""

    def deploy(self, ctx: BuildContext) -> None:
        """Copy the generated resources into the current application directory.

        Args:
            ctx: Current target context providing safe deployment copy helpers.
        """
        ctx.copy_app(paths.CURRENT_BUILD_DIR / "generated-assets", "assets")
```

| 属性 / Property | 含义 / Meaning |
| --- | --- |
| CURRENT_SOURCE_DIR | project.source 的绝对目录 / Absolute project.source directory |
| CURRENT_CONFIG_DIR | YAML 所在目录 / YAML directory |
| CURRENT_SCRIPT_DIR | 项目 Hook 所在目录；未配置时为 YAML 目录 / Project hook directory, or YAML directory without hooks |
| CURRENT_WORK_DIR | 本次独立工作目录 / Isolated invocation directory |
| CURRENT_BUILD_DIR | 本次编译输出目录 / Invocation build directory |
| CURRENT_DEPLOY_DIR | 暂存安装树根目录 / Staged installation root |
| CURRENT_INSTALL_PREFIX | 暂存树内的平台安装前缀 / Platform installation prefix inside staging |
| CURRENT_APP_DIR | 可执行文件相邻目录 / Executable-adjacent directory |
| CURRENT_RESOURCES_DIR | 平台资源目录 / Platform data directory |
| CURRENT_LIBRARIES_DIR | 私有共享库目录 / Private shared library directory |
| CURRENT_PLUGINS_DIR | 平台插件目录 / Platform plugin directory |
| CURRENT_OUTPUT_DIR | 当前目标的最终产物目录 / Final artifact directory for the current target |

这些路径与 `ctx` 的配置和布局一致；资源目标仍需相对部署树指定，不能用绝对路径绕过
`ctx.copy()` 的目标检查。只读属性用于减少路径拼接，不是对可信 Python Hook 的安全沙箱。

These paths match the context configuration and layout. Copy destinations must
remain relative to staging; absolute paths cannot bypass `ctx.copy()` checks.
Read-only properties simplify path composition; they do not sandbox trusted Python hooks.

## 进度与彩色输出 / Progress and colored output

CLI 显示目标计数、四阶段 ASCII 进度条、前后 Hook、正在运行的后端方法、命令与工作目录、
资源复制、耗时和产物路径。成功使用绿色，操作使用青色，警告使用黄色，错误使用红色；
不使用 emoji。进度条统计已成功完成的阶段，不预测编译时间或下载字节数。
后置 Hook 成功后阶段才完成，失败时显示具体回调并停止后续阶段。

The CLI shows target counts, a four-stage ASCII progress bar, lifecycle hooks,
backend operations, commands and working directories, resource copies, elapsed
time, and output paths. Success is green, operations cyan, warnings yellow, and
errors red; no emoji are added. Bars count successfully completed stages rather
than predicting compilation time or downloaded bytes. A stage completes only
after its after hook succeeds. Failures identify the callback and stop later stages.

```sh
wingsetup run -c examples/basic/package.yml --target appimage --color auto
wingsetup check -c examples/basic/package.yml --all --color never
wingsetup list -c examples/basic/package.yml --json --color always
```

`--color auto` 在终端和 GitHub Actions 启用颜色；重定向时默认纯文本。`NO_COLOR`
或 `TERM=dumb` 关闭自动颜色；`FORCE_COLOR=0` 也可关闭，其他值启用。显式
`--color always/never` 优先于自动检测。状态输出到 stderr，`list --json` 的 stdout
始终是纯 JSON，强制颜色也不会污染它。commands.log 不包含终端转义码。

`--color auto` enables color in terminals and GitHub Actions, using plain text for
ordinary redirection. `NO_COLOR` or `TERM=dumb` disables automatic color.
`FORCE_COLOR=0` also disables it; other values enable it. Explicit
`--color always/never` takes precedence over detection. Status goes to stderr;
stdout for `list --json` stays pure JSON even with forced color. commands.log
contains no terminal escape sequences.

外部命令输出逐行显示，不改变 CommandRunner 返回的原始内容；每 15 秒提供仍在运行及
耗时提示。界面按行追加，不覆盖第三方工具输出，也不生成缺乏依据的百分比。
直接从 Python 调用 run_target 时，默认使用相同的自动颜色与进度提示。

External command lines stream without modifying the raw content returned by
CommandRunner. A heartbeat reports continued execution and elapsed time every
15 seconds. Output appends lines without overwriting third-party messages or
inventing percentages. Direct Python calls to run_target use the same automatic
color and progress presentation.

项目 Hook 可通过 `from wingsetup import get_console` 获取同一个输出策略，然后使用
`get_console().write("Deploying private plugins", "info")` 输出项目自身进度，颜色选择
与 CLI 一致。不要把进度消息写入需要被解析的命令返回内容。

Project hooks can import `get_console` from wingsetup and call
`get_console().write("Deploying private plugins", "info")` for application-specific
progress under the same CLI color policy. Keep status messages separate from
command return values that other code parses.

## 平台定制与排除 / Platform customization and exclusions

AppImage 的 Qt 平台现为显式配置。wayland 会从 QMAKE 对应的 SDK 查找 libqwayland*.so，
并部署客户端 shell、图形及装饰集成插件，再扫描 ELF 依赖。支持不同 Qt 6 版本的平台
文件名变化，不要求用户手写 libqwayland-generic.so 等固定名称。构建 SDK 必须已安装
匹配的 Qt Wayland 模块。此选项不强制应用总是使用 Wayland，运行时仍由 Qt/环境选择。

AppImage Qt platforms are explicit. wayland locates libqwayland*.so in the SDK
selected by QMAKE, deploys client shell/graphics/decoration integration plugins,
and scans ELF dependencies. This accommodates Qt 6 platform filename changes
without hard-coding libqwayland-generic.so. Prepare the matching Qt Wayland SDK
module first. Bundling does not force Wayland at runtime; Qt/environment selection
still applies.

```yaml
targets:
  appimage:
    backend: appimage
    arch: x86_64
    exclude: ['**/*.pdb', '**/*.a']
    options:
      plugins: [qt]
      qt_platforms: [xcb, wayland, offscreen]
      environment:
        QMAKE: qmake6
      exclude_libraries: ['libexample-system-only.so*']
```

exclude_libraries 作为 --exclude-library 传给 linuxdeploy；它不是 ABI 验证或平台保证，
应只排除目标系统承诺提供的库。不要随意排除 QtWaylandClient 或必需集成插件。
官方 Qt 插件仍可通过 environment 配置其他模块、QML 搜索等高级行为，参见
[linuxdeploy Qt 插件](https://github.com/linuxdeploy/linuxdeploy-plugin-qt)。

exclude_libraries passes --exclude-library to linuxdeploy. It does not validate ABI
or guarantee platform compatibility; exclude only libraries guaranteed by the
target system. Do not remove QtWaylandClient or required integration plugins.
The environment mapping remains available for advanced module and QML settings;
see the [linuxdeploy Qt plugin](https://github.com/linuxdeploy/linuxdeploy-plugin-qt).

资源规则支持 platforms 和 exclude。platforms 使用 Linux/Windows/Darwin；省略时应用于
所有平台。不匹配时在读取源文件之前跳过，因此公共 YAML 可以引用其他系统才有的资源。
资源 exclude 只在该规则的目录复制时生效，以源目录为基准；不会删除已有目标文件。

Resource rules support platforms and exclude. Platforms use Linux/Windows/Darwin;
omission applies everywhere. Unmatched rules skip before source access, allowing
shared YAML to reference platform-specific files. Resource exclude filters only
that directory copy relative to its source and does not remove existing destinations.

```yaml
project:
  resources:
    - source: assets/windows
      destination: assets
      relative_to: app
      platforms: [Windows]
      exclude: ['cache', '*.tmp']
targets:
  windows:
    backend: inno
    platform: Windows
    arch: x86_64
    exclude: ['**/*.pdb', '**/*.a']
    options:
      formats: [zip, inno]
      setup_icon: assets/setup.ico
      default_dir: '{autopf}\MyApplication'
      privileges: admin
      app_id: org.example.StableInstaller
      desktop_shortcut: true
      file_excludes: ['*.log']
      setup:
        AppPublisher: Example
        WizardStyle: modern
        UsePreviousAppDir: 'yes'
        LicenseFile: LICENSE
```

以上是字段示意，应合并到完整配置并提供真实 .ico。安装目录是 Inno 常量表达式，
不相对 YAML 转为宿主路径；图标、LicenseFile 等编译输入则相对 YAML。默认仍是最低
权限和用户目录。改目录不会自动提权，privileges 必须显式选择 lowest/admin。setup 的
值必须为字符串，yes/no 应加引号。常用默认模板值通过独立字段控制，setup 不允许覆盖
这些字段或输出目录、架构；其余原生 [Setup] 指令由 Inno 编译器校验。

This is a field illustration to merge into a complete configuration with a real
.ico. Installation directories are Inno constant expressions, not host paths
resolved against YAML. Compiler inputs such as icons and LicenseFile are relative
to YAML. Defaults remain lowest privileges and a user directory. Changing the
directory does not elevate privileges; explicitly choose lowest/admin. Setup
values must be strings, including quoted yes/no. Managed options, output paths,
and architecture cannot be overridden through setup. Inno validates other native
[Setup] directive names and values.

自定义 ISS 若同时使用这些安装选项，必须在 [Setup] 内加入 @SETUP_DIRECTIVES@，
否则框架报错而非忽略。该占位符插入完整的受控设置，不应再重复 AppId 等指令。
模板自行管理 [Files]/[Icons]，不能同时设置 file_excludes/desktop_shortcut。原有
@PAYLOAD@ 等占位符保留。图标与目录语义参见
[SetupIconFile](https://jrsoftware.org/ishelp/topic_setup_setupiconfile.htm)、
[DefaultDirName](https://jrsoftware.org/ishelp/topic_setup_defaultdirname.htm)。

A custom ISS consuming typed installer options must include @SETUP_DIRECTIVES@
inside [Setup], or the framework fails instead of silently ignoring them. The
placeholder inserts complete managed settings; do not duplicate AppId and similar
directives. Custom templates own [Files]/[Icons] and cannot also set file_excludes
or desktop_shortcut. Existing placeholders such as @PAYLOAD@ remain supported.
See [SetupIconFile](https://jrsoftware.org/ishelp/topic_setup_setupiconfile.htm)
and [DefaultDirName](https://jrsoftware.org/ishelp/topic_setup_defaultdirname.htm).

| 配置 / Setting | 生效范围与时机 / Scope and timing |
| --- | --- |
| resource.platforms / resource.exclude | 平台筛选与单次资源复制 / Platform selection and individual resource copying |
| target.exclude | 以暂存部署根为基准，pre_package 后、最终签名和产物生成前删除匹配项 / Relative to deployment root, after pre_package and before final signing/package generation |
| inno.file_excludes | 原生 Inno [Files] 规则，仅影响安装器，不影响 ZIP / Native Inno [Files] filter affecting only the installer, not ZIP |
| appimage.exclude_libraries | linuxdeploy 依赖收集 / linuxdeploy dependency collection |
| inno.qt_args / macos.qt_args | windeployqt/macdeployqt 选项，如排除插件类型 / Native Qt tool options such as plugin exclusions |
| flatpak SDK manifest cleanup | SDK 的部署清理，由 manifest 管理 / SDK cleanup owned by its manifest |

排除 glob 使用 / 分隔、区分大小写：*.pdb 匹配任意深度的文件名，**/*.pdb 也匹配根目录。
目录名匹配时省略/删除整个目录；不允许绝对路径、反斜杠和 ..。target.exclude 不跟随链接
删除外部内容，并拒绝删除入口、AppRun 等必要文件；排除私有库仍需项目自行验证运行。
macOS 在排除和 after_deploy 完成后执行最终签名，避免签名后修改内容。

Globs use / separators and are case-sensitive. *.pdb matches basenames at any depth;
**/*.pdb also matches root files. Selecting a directory omits/removes its whole
tree. Absolute paths, backslashes, and .. are rejected. Target exclusion does not
follow links to remove external contents and rejects required entries such as
AppRun. Projects must still verify private-library exclusions. macOS final signing
occurs after filtering and after_deploy, avoiding changes to already signed contents.

macos.qt_args 不允许覆盖 -codesign、-sign-for-notarization、-no-codesign、
-executable 或 -dmg；请使用专用签名、额外代码和 formats 选项，保持最终签名顺序。

macos.qt_args cannot override -codesign, -sign-for-notarization, -no-codesign,
-executable, or -dmg. Use the dedicated signing, extra-code, and formats settings
to preserve final signing order.

## RPM 与 Arch 二进制包 / RPM and Arch binary packages

```yaml
targets:
  rpm:
    backend: rpm
    arch: x86_64
    options:
      package_name: example-app
      release: '1'
      depends: ['libc.so.6()(64bit)']
      url: https://example.org
  arch:
    backend: arch
    arch: x86_64
    options:
      package_name: example-app
      release: '1'
      depends: [glibc]
      url: https://example.org
```

两者均部署到 `usr/`：主程序位于 `usr/bin`，元数据位于 `usr/share`，资源和私有库由
资源规则或项目 Hook 补齐。两后端的 options 仅接受 `package_name`、`release`、
`depends`、`url`；前者必填，其余分别默认 `'1'`、空列表、空 URL（省略字段）。
版本来自 `application.version`，依赖名和版本表达式应使用目标发行版的包管理语法。

Both backends stage under `usr/`: executables in `usr/bin`, metadata in `usr/share`,
and resources/private libraries supplied by copy rules or project hooks. Their
options accept only `package_name`, `release`, `depends`, and `url`. The name is
required; remaining fields default to `'1'`, an empty list, and an omitted URL.
Versions come from `application.version`. Dependency names and version expressions
must follow the destination distribution's package-manager syntax.

RPM 使用工作目录内独立的 spec、构建树及 RPM 数据库，调用 `rpmdb` 和 `rpmbuild -bb`。
固定 RPM 4 输出格式以兼容旧工具；保留 RPM 的 ELF 自动依赖生成并附加显式 `depends`。
不安装包、不使用系统 RPM 数据库、不自动签名；不执行 strip/debug 拆分及发行版的
安装后处理，保持已有部署内容。调用方应在发布前审阅发行版策略与实际安装兼容性。

RPM uses a private spec, build tree, and RPM database via `rpmdb` and `rpmbuild -bb`.
It requests RPM 4 format for older-reader compatibility, retains ELF dependency
generation, and adds explicit `depends`. It does not install packages, use the
system RPM database, or sign automatically. Strip/debug splitting and distro
post-install processing are disabled to preserve prebuilt payloads. Review distro
policy and actual installation compatibility before release.

Arch 调用普通用户的 `makepkg`/`fakeroot`，从本地 SHA-256 校验的 payload 生成包，
写入 `.PKGINFO`、`.BUILDINFO`、`.MTREE`。不调用 `--syncdeps` 或 `--install`，
依赖由用户准备。保留已部署文件，不再次 strip 或移除静态库。宿主需有
`makepkg`、`fakeroot`、`bsdtar`、`zstd`、`desktop-file-validate` 与 `/etc/makepkg.conf`；
root 执行会在检查阶段拒绝。RPM 需 `rpmbuild`、`rpmdb`、`desktop-file-validate`。

Arch invokes unprivileged `makepkg`/`fakeroot` using a local checksummed payload,
producing `.PKGINFO`, `.BUILDINFO`, and `.MTREE`. It never uses `--syncdeps` or
`--install`; users prepare dependencies. Deployed files are preserved without
stripping or removing static libraries. Requirements are `makepkg`, `fakeroot`,
`bsdtar`, `zstd`, `desktop-file-validate`, and `/etc/makepkg.conf`; checks reject
root execution. RPM requires `rpmbuild`, `rpmdb`, and `desktop-file-validate`.

Linux 的 `arch` 接受 `x86_64`、`aarch64`（`arm64` 自动规范化）和 `riscv64`。
程序在匹配架构的原生或 QEMU 用户空间编译，框架检查 ELF e_machine；仅改架构标签
不会进行交叉编译，也不能验证全部 ABI。Debian 的架构标签分别是 `amd64`、`arm64`、`riscv64`。
当前 Arch 包测试使用官方 Arch Linux x86_64；aarch64/riscv64 的 Arch 移植版不在矩阵中。
AppImage/Flatpak 仍要求该架构可用的打包工具/runtime；本次不提供 RISC-V AppImage/Flatpak。

Linux `arch` accepts `x86_64`, `aarch64` (`arm64` normalizes automatically), and
`riscv64`. Compile in a matching native or QEMU userspace; ELF e_machine is checked.
Changing the label does not cross-compile code or prove ABI compatibility. Debian
labels are `amd64`, `arm64`, and `riscv64`. Arch package CI uses official Arch Linux
x86_64; Arch ports for aarch64/riscv64 are outside the matrix. AppImage/Flatpak still
require tools/runtimes for their architecture; this change supplies no RISC-V
AppImage/Flatpak baseline.

依据 / References: [RPM build](https://rpm.org/docs/4.20.x/man/rpmbuild.8.html),
[makepkg](https://man.archlinux.org/man/makepkg.8),
[makepkg configuration](https://man.archlinux.org/man/makepkg.conf.5).

## 共享安装配置 / Shared installation preferences

顶层和目标均接受可选 installation，详见 [安装集成指南](installation.md)。
显式后端设置优先，未支持的行为跳过并写入 installation.json；旧配置行为保持。

Top-level and target mappings accept optional installation preferences; see the
[installation guide](installation.md). Explicit backend settings take precedence;
unsupported behavior is skipped and recorded in installation.json. Legacy behavior is preserved.
