# WingSetup

初始版本：`0.0.1`。 / Initial version: `0.0.1`.

通用跨平台安装包打包框架，使用 YAML 配置和 Python Hook 执行
`prepare → build → deploy → package`。支持 Linux、Windows、macOS 的二进制包和配方产物，以及 FreeBSD 通用归档，
使用 Python 3.11+ 并通过 Pyright / Pylance strict。

A general cross-platform packaging framework using YAML configuration and Python hooks
for `prepare → build → deploy → package`. It supports native binary packages and recipe artifacts on Linux, Windows and macOS,
plus portable FreeBSD archives, requires Python 3.11+, and uses Pyright / Pylance strict typing.

## 打包格式与 CPU 架构 / Package formats and CPU architectures

下表列出后端实现与适用架构；使用时仍需对应的构建工具、依赖及 runtime/SDK。
架构支持不表示每种组合都已完成原生 CI 验收，已配置的测试范围见后表。

The table lists implemented backends and applicable architectures. Matching build tools,
dependencies, and runtimes/SDKs are required. Architecture support does not mean every
combination has passed native CI; declared test coverage is listed separately below.

| 平台 / Platform | 后端 / Backend | 产物 / Outputs | CPU 架构 / CPU architectures |
| --- | --- | --- | --- |
| Linux | `appimage` | `.AppImage`、可选 / optional `.AppImage.zsync` | `x86_64`, `aarch64`; 需要对应架构工具 / matching tools required |
| Linux | `flatpak` | `.flatpak`、本地仓库 / local repository | `x86_64`, `aarch64`; 需要匹配的 runtime/SDK / matching runtime/SDK required |
| Linux | `deb` | `.deb` | `x86_64`, `aarch64`, `riscv64` |
| Linux | `rpm` | `.rpm` | `x86_64`, `aarch64`, `riscv64` |
| Linux | `arch` | `.pkg.tar.zst` 二进制包 / binary package | `x86_64`, `aarch64`, `riscv64`; 需要相应 makepkg 环境 / matching makepkg environment required |
| Linux | `archive` | `.tar.gz` | `x86_64`, `aarch64`, `riscv64` |
| Linux / macOS | `makeself` | 自解压 / self-extracting `.run`, `.sh` | Linux: `x86_64`, `aarch64`, `riscv64`; macOS: `x86_64`, `aarch64`, `universal2` |
| Windows | `inno` | Inno Setup `.exe`、便携 / portable `.zip` | `x86_64` (x64), `aarch64` (ARM64) |
| macOS | `macos` | `.dmg`, `.app.zip`, `.zip`，包含 / containing `.app` | `x86_64` (Intel), `aarch64` (Apple Silicon), `universal2` |
| macOS | `archive` | CLI / 通用归档 / portable `.tar.gz`, `.zip` | `x86_64`, `aarch64`, `universal2` |
| FreeBSD | `archive` | `.tar.gz` | 首批发布配置 / initial release configuration: `x86_64`; 其他架构需自备工具链并验收 / other architectures require their own toolchain and validation |
| 配方 / Recipes | `aur` | PKGBUILD、`.SRCINFO`，release / `-git` 配方 / recipes | `any` 或配方声明的目标架构 / architectures declared by the recipe |
| 脚本 / Scripts | `script` | 项目自有管理脚本归档 / project-owned management script archive | `any` 或脚本声明的目标架构 / architectures declared by the scripts |

YAML 中统一使用 `x86_64`、`aarch64`、`riscv64`、`universal2`；`amd64` / `x64` 会归一化为
`x86_64`，`arm64` 归一化为 `aarch64`。`universal2` 仅用于 macOS，要求程序及依赖同时包含
Intel 和 Apple Silicon 代码；`any` 仅用于配方。当前不支持 32 位 x86 / ARM 或 Windows MSI。
原生后端需要匹配的宿主与架构；QEMU / FreeBSD VM 在其内部执行构建，不只是改名或重压缩。

Use `x86_64`, `aarch64`, `riscv64`, or `universal2` in YAML. Aliases `amd64` / `x64`
normalize to `x86_64`, and `arm64` to `aarch64`. macOS-only `universal2` requires both
Intel and Apple Silicon slices in the program and dependencies; `any` is reserved
for recipes. 32-bit x86 / ARM and Windows MSI are not supported. Native backends
require matching hosts and architectures; QEMU / FreeBSD VMs build inside the guest,
rather than simply renaming or recompressing foreign binaries.

### 已声明的示例 CI 范围 / Declared example CI coverage

| 平台 / Platform | 架构 / Architecture | 已配置用例 / Configured cases |
| --- | --- | --- |
| Linux / Ubuntu 22.04, 26.04 | `x86_64` | AppImage、Flatpak、deb、RPM、tar.gz、自解压包 / self-extracting archives |
| Linux / Arch 构建环境 / build environment | `x86_64` | `.pkg.tar.zst`、AUR 配方与脚本检查 / AUR recipe and script checks |
| Linux / Ubuntu 22.04, 26.04 ARM runner | `aarch64` | deb、RPM / deb and RPM |
| Linux / QEMU riscv64 | `riscv64` | deb、RPM / deb and RPM |
| Windows | `x86_64` | Qt 便携 ZIP、Inno 安装/升级/卸载 / Qt portable ZIP and Inno installation/upgrade/removal |
| macOS | `aarch64`, `x86_64` | Qt 应用归档、DMG、签名检查与启动 / Qt app archives, DMG, signature checks and launch |

以上是当前 41 项用例的配置范围，不是最新一次远端运行结果。Windows ARM64、macOS universal2、
FreeBSD 及其他未列出的格式/架构组合尚未纳入该示例验收矩阵；发布工作流中的支持不等于已通过测试。
详见 [CI 矩阵](docs/ci.md)和[发布构建指南](docs/release.md)。

These are the configured scopes of the current 41 cases, not results from the latest
remote run. Windows ARM64, macOS universal2, FreeBSD, and other unlisted format/architecture
combinations are outside this example acceptance matrix. Release workflow support does
not imply completed testing. See the [CI matrix](docs/ci.md) and [release guide](docs/release.md).

## 安装 / Installation

所有 Python 依赖均安装到虚拟环境，不安装到系统 Python。
Install all Python dependencies in a virtual environment, not system Python.

```sh
uv venv .venv --python python3
uv pip install --python .venv/bin/python -e '.[dev]'
source .venv/bin/activate
```

也可以用 `python3 -m venv .venv` 创建环境，激活后执行
`python -m pip install -e '.[dev]'`。框架仅检查外部工具，不自动安装系统包或 runtime/SDK。

Alternatively, create the environment with `python3 -m venv .venv`, activate it,
and run `python -m pip install -e '.[dev]'`. The framework checks external tools
but does not install system packages or runtimes/SDKs automatically.

Windows 可用 `py -3 -m venv .venv` 创建环境，在 PowerShell 执行
`.venv\Scripts\Activate.ps1`，然后运行 `python -m pip install -e '.[dev]'`。
macOS/Linux 使用上述 POSIX 路径；原生后端需要对应系统与工具链。

On Windows, create the environment with `py -3 -m venv .venv`, activate it in
PowerShell with `.venv\Scripts\Activate.ps1`, then run
`python -m pip install -e '.[dev]'`. macOS/Linux use the POSIX paths above.
Native backends require their matching OS and toolchain.

## 两个示例 / Two examples

| 目录 / Directory | 用途 / Purpose |
| --- | --- |
| [examples/basic](examples/basic/README.md) | 基础 C 程序、原生包与配方及自定义后端 / A basic C program, native packages, recipes and a custom backend |
| [examples/qtwidgets](examples/qtwidgets/README.md) | 跨平台 Qt Widgets、翻译、资源与动态插件 / Cross-platform Qt Widgets, translations, resources and dynamic plugins |

```sh
wingsetup list -c examples/qtwidgets/package.yml --json
wingsetup check -c examples/basic/package.yml --all
wingsetup run -c examples/basic/package.yml --target appimage
wingsetup run -c examples/qtwidgets/package.yml --target flatpak-sdk
```

## 项目结构 / Project structure

| 路径 / Path | 职责 / Responsibility |
| --- | --- |
| `src/wingsetup/backends/appimage.py` | AppImage 后端 / AppImage backend |
| `src/wingsetup/backends/flatpak.py` | Flatpak 后端 / Flatpak backend |
| `src/wingsetup/backends/{archive,deb,rpm,arch,inno,macos,aur,makeself,script}.py` | 其他独立后端 / Other independent backends |
| `src/wingsetup/registry.py`, `platforms.py` | 后端能力与平台布局 / Backend capabilities and platform layouts |
| `src/wingsetup/backends/common.py` | 共享部署与校验 / Shared deployment and validation |
| `src/wingsetup/core.py` | 流水线、Hook 和命令执行 / Pipeline, hooks and command execution |
| `src/wingsetup/script_paths.py` | 目标绑定的只读全局路径 / Target-bound read-only global paths |
| `src/wingsetup/config.py`, `model.py`, `cli.py` | 配置、类型模型和 CLI / Configuration, typed models and CLI |
| `tests/`, `docs/` | 测试和文档 / Tests and documentation |

具体应用的集成由应用自己的打包目录维护，本仓库只保留通用示例。
Application-specific integrations belong in each application's packaging folder;
this repository contains only general examples.

## 文档与贡献 / Documentation and contributing

- [架构与调研 / Architecture and research](docs/architecture.md)
- [GitHub CI / GitHub CI integration](docs/ci.md)
- [使用与配置 / Usage and configuration](docs/usage.md)
- [开发与验收 / Development and validation](docs/development.md)
- [贡献指南 / Contributing](CONTRIBUTING.md)
- [仓库协作规范 / Repository guidance](AGENTS.md)
- [变更记录 / Changelog](CHANGELOG.md)

```sh
.venv/bin/pyright
.venv/bin/python -m pytest -q
```

## 许可证 / License

采用 [BSD 3-Clause](LICENSE)，许可证保留标准英文原文。下载的工具、
Qt、runtime 和被打包应用仍遵循各自许可证。

Licensed under [BSD 3-Clause](LICENSE), provided in its standard English form.
Downloaded tools, Qt, runtimes and packaged applications retain their own licenses.

## 安装集成 / Installer integration

可选 installation 配置共享图标、文件/URL 关联及安装偏好，目标可覆盖；不支持的功能逐产物
报告为 ignored。Windows 继续 Inno Setup，不新增 MSI；PATH、自启、右键和桌面快捷方式为
默认不勾选的可选项。完整配置与能力边界见 [安装集成指南](docs/installation.md)。

Optional installation preferences share icons, file/URL handlers, and installer
behavior with target overrides. Unsupported features are reported per output as
ignored. Windows retains Inno Setup without MSI. PATH, startup, Explorer menus,
and desktop shortcuts are initially unchecked choices. See the
[installation guide](docs/installation.md) for configuration and capability boundaries.

## 全平台发布构建 / Multi-platform release builds

调用共享工作流即可按项目构建配置运行全部任务，默认全部启用 Qt 模式，最后输出文件名、
SHA-256、`SHA256SUMS.txt` 和 `release.json`。详见[发布指南](docs/release.md)。

The reusable workflow executes all configured project builds in Qt mode by default
and returns filenames, SHA-256 values, `SHA256SUMS.txt`, and `release.json`.
See the [release guide](docs/release.md).
