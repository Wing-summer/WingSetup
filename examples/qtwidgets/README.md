# Qt Widgets 示例 / Qt Widgets example

本目录演示 CMake 构建、Qt Widgets、编译后的中文翻译、外部脚本/主题/配置、
动态加载的 `.wingplg` 及其私有共享库。目录布局模拟按可执行文件位置查找资源的应用。

This directory demonstrates CMake builds, Qt Widgets, compiled Chinese
translations, external scripts/themes/configuration, a dynamically loaded
`.wingplg`, and its private shared library. Its layout models applications that
locate resources relative to their executable.

从仓库根目录运行 / Run from the repository root:

```sh
wingsetup check -c examples/qtwidgets/package.yml --all --compatible
wingsetup run -c examples/qtwidgets/package.yml --target appimage
wingsetup run -c examples/qtwidgets/package.yml --target flatpak-sdk
QT_QPA_PLATFORM=offscreen examples/qtwidgets/dist/appimage/WidgetsDemo-0.1.0-x86_64.AppImage --appimage-extract-and-run --smoke
```

AppImage 构建需要 CMake、C++ 编译器、Qt 6 Widgets/LinguistTools 及 Qt 部署插件。
请使 YAML 的 QMAKE 与构建工具链一致。Flatpak 在 KDE 6.10 SDK 内构建，不借用宿主 Qt。

The AppImage build requires CMake, a C++ compiler, Qt 6 Widgets/LinguistTools and
the Qt deployment plugin. Match QMAKE in YAML to the build toolchain. Flatpak
builds inside KDE 6.10 SDK without using host Qt.

`--smoke` 实际检查全部资源、翻译、插件与私有库；成功输出 `WIDGETS_DEPLOY_OK`。
图形界面采用 offscreen 平台测试，不代表已验证所有桌面环境或完整应用。

`--smoke` checks all resources, translations, the plugin and its private library;
success prints `WIDGETS_DEPLOY_OK`. Offscreen testing does not validate every
desktop environment or a complete downstream application.

本地 Arch 工具兼容性和额外依赖记录见[开发与验收](../../docs/development.md)。
See [development and validation](../../docs/development.md) for local Arch tool
compatibility and additional dependencies.

## Windows / macOS

配置还包含 windows、macos 和 macos-intel 目标，必须在对应原生系统运行。CMake 为 Windows 安装
DLL/插件，在 macOS 生成 .app，数据放入 Contents/Resources、业务插件放入 Contents/PlugIns。macos 目标为 aarch64，macos-intel 为 x86_64，各自在匹配的 GitHub macOS runner 构建和启动验证。
无需本地 Mac；原生验证结果以对应 Actions 用例实际执行记录为准。

The configuration also includes windows, macos, and macos-intel targets requiring their native
OS. CMake installs DLLs/plugins on Windows and builds a .app using Contents/Resources for data and Contents/PlugIns for business
plugins on macOS. The macos target uses aarch64 and macos-intel uses x86_64. Separate matching GitHub
macOS runners build and launch both. No local Mac is required; actual Actions
receipts establish native validation.

```sh
wingsetup run -c examples/qtwidgets/package.yml --target windows
wingsetup run -c examples/qtwidgets/package.yml --target macos
wingsetup run -c examples/qtwidgets/package.yml --target macos-intel
```

Windows 的 windeployqt 显式包含 qwindows/qoffscreen；启动前验证归档携带 offscreen 插件，
不会借用宿主 Qt。macOS 的代码目录不存放 .qm、JSON 或脚本资源，以满足 bundle 签名规则。
冒烟测试运行 Qt 事件循环，但不显示窗口；超时会保留插件诊断。

Windows deployment explicitly includes qwindows/qoffscreen. Archive checks require
the offscreen plugin without borrowing host Qt. macOS code directories contain
no .qm, JSON, or script resources, following bundle signing rules. Smoke tests
exercise the Qt event loop without showing a window; timeouts retain plugin diagnostics.

AppImage 显式启用 xcb、wayland、offscreen。Qt SDK 需包含匹配的 Wayland 模块；
Windows 示例展示安装目录、权限、发布者与 Inno 专属排除。完整字段见
[平台定制](../../docs/usage.md)。

AppImage explicitly enables xcb, wayland, and offscreen; prepare the matching Qt
Wayland SDK module. Windows demonstrates installation directory, privileges,
publisher, and installer-only exclusions. See [platform customization](../../docs/usage.md).

Linux CI 分别使用 Ubuntu 22.04 与 26.04 的发行版 Qt，包含 Wayland、SVG 和翻译工具。
两个 LTS 分别构建并启动验证，不能据此推断新版构建产物兼容旧版 glibc。

Linux CI uses distro Qt on Ubuntu 22.04 and 26.04, including Wayland, SVG, and
translation tools. Both LTS endpoints build and launch independently; this does
not imply that newer-system artifacts work with an older glibc.

## RPM、Arch 与多架构 / RPM, Arch, and multiple architectures

配置增加 `rpm`、`arch`、`rpm-arm64`、`rpm-riscv64`；基础示例另有 `deb-arm64`、
`deb-riscv64`。匹配架构的 Linux 环境负责编译，arm64 是 aarch64 的别名。
`arch` 目标生成真实 `.pkg.tar.zst`，与 AUR 配方导出不同。运行前准备系统工具；
框架不会自动安装。字段及边界见 [使用说明](../../docs/usage.md)。

Configurations add `rpm`, `arch`, `rpm-arm64`, and `rpm-riscv64`; the basic fixture
also has `deb-arm64` and `deb-riscv64`. A matching Linux environment performs
compilation; arm64 aliases aarch64. The `arch` target generates a real
`.pkg.tar.zst`, distinct from AUR recipes. Prepare native tools first; the framework
never installs them automatically. See [usage](../../docs/usage.md) for options and boundaries.

## 安装选项验收 / Installation preferences fixture

共享 installation 使用独占 `.wingsetup-demo` / `.wingsetup-obsolete` 扩展名与同名 URL
scheme；第二项用于验证升级清理。ICO/ICNS 从本示例 BSD 许可的 SVG 图标生成，不修改 EXE。
Windows 的额外选项默认未勾选，只有显式临时 runner 验收选择并运行它们；不接管默认应用。
完整说明见 [安装指南](../../docs/installation.md)。

Shared installation preferences use exclusive .wingsetup-demo/.wingsetup-obsolete
extensions and matching URL schemes; the second entries exercise upgrade cleanup.
ICO/ICNS assets derive from this fixture's BSD-licensed SVG without modifying the
EXE. Extra Windows options are initially unchecked; only explicit ephemeral-runner
acceptance selects and executes them, without taking over defaults. See the
[installation guide](../../docs/installation.md).
