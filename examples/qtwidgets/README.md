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

配置还包含 windows 和 macos 目标，必须在对应原生系统运行。CMake 为 Windows 安装
DLL/插件，在 macOS 生成 .app，数据放入 Contents/Resources、业务插件放入 Contents/PlugIns。配置中的 macOS 目标默认 aarch64；
Intel 用户需修改 arch 并使用匹配工具链。当前 Linux 验收不代表这两个原生目标已通过 CI。

The configuration also includes windows and macos targets requiring their native
OS. CMake installs DLLs/plugins on Windows and builds a .app using Contents/Resources for data and Contents/PlugIns for business
plugins on macOS. The macOS target defaults to aarch64; Intel users must adjust
arch and toolchain. Linux validation does not imply these native targets passed CI.

```sh
wingsetup run -c examples/qtwidgets/package.yml --target windows
wingsetup run -c examples/qtwidgets/package.yml --target macos
```

Windows 的 windeployqt 显式包含 qwindows/qoffscreen；启动前验证归档携带 offscreen 插件，
不会借用宿主 Qt。macOS 的代码目录不存放 .qm、JSON 或脚本资源，以满足 bundle 签名规则。
冒烟测试运行 Qt 事件循环，但不显示窗口；超时会保留插件诊断。

Windows deployment explicitly includes qwindows/qoffscreen. Archive checks require
the offscreen plugin without borrowing host Qt. macOS code directories contain
no .qm, JSON, or script resources, following bundle signing rules. Smoke tests
exercise the Qt event loop without showing a window; timeouts retain plugin diagnostics.
