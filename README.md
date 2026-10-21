# WingSetup

初始版本：`0.0.1`。 / Initial version: `0.0.1`.

通用跨平台安装包打包框架，使用 YAML 配置和 Python Hook 执行
`prepare → build → deploy → package`。支持 Linux、Windows、macOS 的二进制包和配方产物，
使用 Python 3.11+ 并通过 Pyright / Pylance strict。

A general cross-platform packaging framework using YAML configuration and Python hooks
for `prepare → build → deploy → package`. It supports native binary packages and recipe artifacts on Linux, Windows and macOS, requires Python 3.11+, and uses Pyright / Pylance strict typing.

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
| `src/wingsetup/backends/{deb,inno,macos,aur,makeself,script}.py` | 其他独立后端 / Other independent backends |
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
