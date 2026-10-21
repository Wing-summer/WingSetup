# 基础示例 / Basic example

本目录包含一个 C 程序，用于理解四阶段流水线、Hook、AppImage、Flatpak binary
及 Flatpak SDK 打包。`custom_backend.py` 演示如何实现额外的归档后端，不属于默认三个目标。

This directory contains a C program demonstrating the four-stage pipeline,
hooks, AppImage, Flatpak binary and Flatpak SDK packaging. `custom_backend.py`
illustrates an additional archive backend; it is not one of the three default targets.

从仓库根目录运行 / Run from the repository root:

```sh
wingsetup check -c examples/basic/package.yml --all
wingsetup run -c examples/basic/package.yml --target appimage
wingsetup run -c examples/basic/package.yml --target flatpak-binary
wingsetup run -c examples/basic/package.yml --target flatpak-sdk
```

构建需要 C 编译器。AppImage 需要 linuxdeploy、appimagetool 和 desktop-file-validate；
Flatpak 需要 flatpak，SDK 模式还需要 flatpak-builder。示例使用系统安装的 KDE 6.10
Platform/SDK，实际环境可修改 YAML。包输出到本目录的 `dist/<target>/`。

Building requires a C compiler. AppImage requires linuxdeploy, appimagetool and
desktop-file-validate; Flatpak requires flatpak, with flatpak-builder for SDK mode.
The example selects system-installed KDE 6.10 Platform/SDK; adjust the YAML for
your environment. Bundles are written to this directory's `dist/<target>/`.

本示例不验证 Qt 部署；相关测试见 [Qt Widgets 示例](../qtwidgets/README.md)。
This example does not validate Qt deployment; see the [Qt Widgets example](../qtwidgets/README.md).

## 扩展目标 / Extended targets

`extended.yml` 增加 deb、AUR release/-git、管理脚本、Makeself .run/.sh 和自定义 tar 归档。
AUR release 使用本地 hello.c，可以离线导出 .SRCINFO；-git 是需要修改 URL 的模板，
不会在导出时拉取或编译源码。script 只导出脚本，不执行安装。Makeself 需要单独准备工具。

`extended.yml` adds deb, AUR release/-git, management scripts, Makeself .run/.sh and a custom tar archive.
The release recipe uses local hello.c and can export .SRCINFO offline. The -git
recipe is a template requiring a real URL; export neither fetches nor builds it.
Script export does not execute installers. Prepare Makeself separately.

```sh
wingsetup run -c examples/basic/extended.yml --target deb
wingsetup run -c examples/basic/extended.yml --target aur-release --target aur-git
wingsetup run -c examples/basic/extended.yml --target scripts
wingsetup run -c examples/basic/extended.yml --target shell
```

shell 示例入口只演示不覆盖现有目录的用户安装；它不是通用安装管理器。生成包不会执行该入口。
The shell entry demonstrates user installation without replacing an existing directory;
it is not a general installation manager. Package creation does not execute the entry.

这些配置中的每个目标都列入框架 CI 覆盖清单。脚本 Hook 使用只读 `paths` 获取项目路径，
接口说明见[配置文档](../../docs/usage.md)。

Every target in these configurations belongs to the framework CI coverage
manifest. The example hook uses read-only `paths` for project paths; see the
[configuration guide](../../docs/usage.md).
