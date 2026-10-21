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
