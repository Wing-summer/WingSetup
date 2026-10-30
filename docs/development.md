# 开发与验收 / Development and validation

依赖与基础检查见[贡献指南](../CONTRIBUTING.md)。CI 在 Python 3.11 和 3.14 上运行
strict 检查和单元测试。完整打包需额外工具；生成包、沙箱启动和安装后的桌面启动是独立验证。

See [contributing](../CONTRIBUTING.md) for dependencies and basic checks. CI runs
strict typing and unit tests on Python 3.11 and 3.14. Real packaging requires
additional tools. Bundle creation, sandbox launching and installed desktop
launching are separate validation steps.

## 本地工作区 / Local workspace

以下仅记录当前工作区，不代表克隆后自动具备这些工具。依赖位于 `.venv`，下载工具位于
`.tools`；无 FUSE 的包装脚本位于 `.tools/bin`。这些目录不进入发布包。

The following describes this workspace only, not prerequisites automatically
provided by cloning. Dependencies live in `.venv`, downloaded tools in `.tools`,
and FUSE-free wrappers in `.tools/bin`. These directories are excluded from distributions.

```sh
source .venv/bin/activate
export PATH="$PWD/.tools/bin:$PATH"
wingsetup check -c examples/basic/package.yml --all
```

linuxdeploy 使用 commit `07333c6`（build 369），appimagetool 使用 commit `854e19e`
（build 313）；Qt 部署插件也解包到本地。appimagetool 可能联网下载 runtime。
Flatpak 使用 `--disable-rofiles-fuse`，不要求其缓存阶段启用 FUSE。

linuxdeploy uses commit `07333c6` (build 369), and appimagetool uses commit `854e19e`
(build 313). The Qt plugin is also extracted locally. appimagetool may download
its runtime over the network. Flatpak uses `--disable-rofiles-fuse` so its cache
stage does not require FUSE.

本机 KDE JPEG XR 图像插件缺少的依赖已解包到 `.tools/jxrlib`；Qt AppImage 构建时可以使用：
The missing dependencies of this machine's KDE JPEG XR image plugin were extracted
to `.tools/jxrlib`; the Qt AppImage build can use:

```sh
export LD_LIBRARY_PATH="$PWD/.tools/jxrlib/usr/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
wingsetup run -c examples/qtwidgets/package.yml --target appimage
```

Qt 示例设置 `NO_STRIP=1`，因为上游工具附带的旧 strip 无法解析部分 Arch ELF 的
`.relr.dyn` 节。保留符号会增加包体积，不改变依赖收集；部署需要与构建匹配的 Qt 工具链。

The Qt example sets `NO_STRIP=1` because the bundled older strip cannot parse
`.relr.dyn` in some Arch ELF files. Retaining symbols increases bundle size without
changing dependency collection. Deployment must use a Qt toolchain matching the build.

## 验收记录 / Validation record

2026-10-20：重组前的 18 项测试及 strict 检查通过。Qt Widgets AppImage 与 Flatpak SDK
包均生成并校验 SHA-256，offscreen 启动均输出
`WIDGETS_DEPLOY_OK: translation, resources, .wingplg, private library`。
AppImage 测试清除了宿主 LD_LIBRARY_PATH/QT_PLUGIN_PATH。Flatpak 仅在构建树运行，
未安装到系统，也未验证安装后的桌面启动。后续结构和文档调整以当前测试结果为准。

2026-10-20: Before the example reorganization, 18 tests and strict typing passed.
Qt Widgets AppImage and Flatpak SDK bundles were generated and SHA-256 checked.
Both offscreen launches printed
`WIDGETS_DEPLOY_OK: translation, resources, .wingplg, private library`.
The AppImage test cleared host LD_LIBRARY_PATH/QT_PLUGIN_PATH. Flatpak ran only
from its build tree, without installation or installed desktop-launch validation.
Use current test results for subsequent structural and documentation changes.

对于直接指向入口二进制的 AppRun 链接，框架改为脚本执行 usr/bin 中的入口，避免解包运行
改变 Qt 的 applicationDirPath()。自定义启动脚本保留不变。

The framework replaces AppRun links pointing directly to the entry binary with a
script executing the entry under usr/bin, preventing extract-and-run from changing
Qt applicationDirPath(). Custom launcher scripts are preserved.

## 重构后复验 / Post-refactor verification

2026-10-20：跨平台后端重构后 strict 检查及 31 项测试通过，工作流通过 actionlint。
基础 deb、AUR release/-git、脚本归档、Makeself .run 及 Flatpak binary 实际生成；deb 解包入口和 .run
解包入口启动成功，包 SHA-256 与 Makeself 内部校验通过。Qt Widgets AppImage 和
Flatpak SDK 重新生成，清除宿主部署环境后的 AppImage 及 Flatpak 构建树 offscreen
启动再次输出完整的 WIDGETS_DEPLOY_OK。Flatpak 有无 D-Bus portal 的桌面行为未验收。

2026-10-20: After the cross-platform backend refactor, strict checks and 31 tests
passed, and actionlint validated workflows. Basic deb, AUR release/-git recipes,
script archives, Makeself .run and Flatpak binary were generated with real tools. Extracted deb
and .run entries launched; package SHA-256 and Makeself integrity checks passed.
Qt Widgets AppImage and Flatpak SDK bundles were rebuilt. AppImage offscreen
launching with host deployment variables cleared, and Flatpak build-tree launching,
again produced the complete WIDGETS_DEPLOY_OK marker. Desktop portal behavior
with or without a D-Bus session was not validated.

Windows、macOS、Developer ID 签名及公证目前仅有模拟工具测试，尚未在真实 runner 运行。
Linux CI 初始基线为 Ubuntu 24.04，macOS 首批为 Apple Silicon arm64；本机 Arch 的
成功运行不代表已完成 Ubuntu 基线或所有发行版兼容验收。

Windows, macOS, Developer ID signing and notarization currently have mocked tool
tests, without execution on native runners. Initial Linux CI targets Ubuntu 24.04;
macOS starts with Apple Silicon arm64. Local success on Arch does not validate
the Ubuntu baseline or compatibility with every distribution.

## 0.0.1 示例 CI 验证 / 0.0.1 example CI validation

2026-10-20：新增只读路径与示例覆盖清单后，全部 Python 文档覆盖检查、strict 与
36 项测试通过，三套工作流通过 actionlint。新 CI 驱动在本机 Arch 实际验证了 12 个
Linux/配方案例：basic/Qt AppImage、三种 Flatpak 示例、deb、Makeself .run/.sh、
自定义归档、AUR release/-git 和管理脚本。每个案例记录 validation.json。

2026-10-20: After adding read-only paths and the example coverage manifest, Python
documentation coverage checks, strict typing, and 36 tests passed. actionlint
validated all three workflows. The new CI driver verified 12 Linux/recipe cases
on local Arch: basic/Qt AppImage, three Flatpak examples, deb, Makeself .run/.sh,
custom archives, AUR release/-git, and management scripts. Each case records
validation.json.

这些结果不表示 Ubuntu 24.04 runner 已执行。Windows Inno/ZIP 与 macOS app/ZIP/DMG
已纳入清单，但尚未运行远端 CI。安装器入口未执行；Apple 凭据、公证及
Intel/universal2 不包含在本次真实验证中。

These results do not establish execution on an Ubuntu 24.04 runner. Windows
Inno/ZIP and macOS app/ZIP/DMG belong to the manifest but have not run remotely.
Installer entry points were not executed. Apple credentials, notarization, and
Intel/universal2 remain outside this real validation.

## Wayland 与配置扩展验证 / Wayland and configuration extension validation

2026-10-23：新 Qt AppImage 已在本机现有 Wayland 会话与 offscreen 平台运行，两次均输出
完整 WIDGETS_DEPLOY_OK。运行时清除了宿主 LD_LIBRARY_PATH/QT_PLUGIN_PATH，产物包含
Qt Wayland QPA、客户端集成插件及收集到的依赖。此次本机未安装 Weston；GitHub 的独立
headless Weston 路径仍需下次 CI 执行。Inno/macOS 新配置通过模拟工具回归验证，
不声称已经在原生系统编译和运行全部新选项。

2026-10-23: The new Qt AppImage ran in the existing local Wayland session and with
offscreen; both produced the complete WIDGETS_DEPLOY_OK marker. Host
LD_LIBRARY_PATH/QT_PLUGIN_PATH overrides were cleared. The artifact contains Qt
Wayland QPA, client integration plugins, and collected dependencies. Weston was
not installed locally; the isolated GitHub headless path still needs its next CI
run. New Inno/macOS settings passed mocked-tool regressions, without claiming
complete native compilation and execution of every new option.

## Intel 与双 LTS 矩阵 / Intel and dual-LTS matrix

当前计划矩阵为 24 个示例用例：Linux 12、Flatpak 6、原生 Windows/macOS 3、配方 3。
新增 macos-intel 目标与 Ubuntu 22.04/26.04 两端验证；本地 Arch 只执行静态检查与单元测试，
新增 runner 的原生打包、Wayland、签名与 DMG 启动结果仍以 GitHub Actions 实际记录为准。
前面的日期记录描述当时的验证范围，不表示新增矩阵已执行。

The current plan contains 24 example cases: 12 Linux, six Flatpak, three native
Windows/macOS, and three recipes. It adds macos-intel and both Ubuntu 22.04/26.04
endpoints. Local Arch checks cover static validation and unit tests; actual GitHub
Actions receipts must establish packaging, Wayland, signing, and DMG launches on
the new runners. Earlier dated records retain their historical verification scope
and do not claim execution of the expanded matrix.

## RPM 与 Arch 本地验收 / Local RPM and Arch verification

本次新增的基础 C、Qt Widgets 示例均在本机 x86_64 实际生成 `.rpm` 和 `.pkg.tar.zst`，
检查包内架构/元数据并解包启动。Qt 两种包均输出
`WIDGETS_DEPLOY_OK: translation, resources, .wingplg, private library`。
RPM 工具及兼容库按包仓库 SHA-256 校验后解压到 `.tools/rpm-local`，未安装系统软件或产物。
这些本地结果不表示 Fedora/Arch 的系统安装或新增 ARM/RISC-V 远端用例已通过。

Both basic C and Qt Widgets fixtures produced real `.rpm` and `.pkg.tar.zst`
packages on the local x86_64 host, followed by metadata/architecture inspection,
extraction, and launches. Both Qt packages emitted
`WIDGETS_DEPLOY_OK: translation, resources, .wingplg, private library`.
RPM tools and compatibility libraries were verified using repository SHA-256
metadata and extracted into `.tools/rpm-local`; no system software or output
packages were installed. Local results do not establish Fedora/Arch installation
acceptance or success of the new remote ARM/RISC-V cases.

## 通用安装配置验收（2026-10-30） / Shared installation validation (2026-10-30)

共享配置及 Inno 集成通过 Linux、Windows、Darwin 三种目标平台的 Pyright strict 检查。
官方 Inno Setup 6.7.3 编译器在工作区隔离的 Wine 环境中成功编译用户安装、机器安装和带项目回调的自定义 ISS；
此验证仅编译安装器，未执行安装、升级或卸载。

Shared preferences and Inno integration passed Pyright strict for Linux, Windows,
and Darwin target platforms. The official Inno Setup 6.7.3 compiler successfully
compiled user-scope, machine-scope, and custom ISS installers with a project callback
in a workspace-isolated Wine environment. This compiled installers only; it did not
execute installation, upgrade, or removal.

Qt Widgets 的 AppImage、RPM 和 Arch 包已在本机实际生成，完成解包、清理宿主部署环境后的程序启动，
并在临时目录验证 desktop/MIME 数据库。发布 wheel 已检查包含 Inno 运行时代码。
Windows 的安装、覆盖升级、卸载与注册表清理，以及 macOS 的原生归档、签名和启动，仍须由对应 CI runner 验收；
这些远端结果不计入本地成功记录。Windows 示例汇总要求三项安装生命周期证据，可复用 Action 不执行安装器。

Qt Widgets AppImage, RPM, and Arch packages were generated locally, extracted,
and launched with host deployment variables cleared; desktop/MIME databases were
validated in temporary directories. The release wheel was checked for the Inno
runtime resource. Windows installation, replacement upgrade, removal, and registry
cleanup, along with native macOS archive, signature, and launch checks, still require
the corresponding CI runners. These remote checks are not counted as local successes.
The Windows example result gate requires all three installation lifecycle receipts;
the reusable Action does not execute installers.

## 发布接口验证（2026-10-30） / Release interface verification (2026-10-30)

本地完成最小 C 程序的原生编译、通用归档、发布文件命名、跨任务清单汇总、SHA-256 重算及解包启动；
Qt 默认模式与源提交固定的矩阵输出也已检查。示例覆盖清单扩展为 41 项。
FreeBSD VM、riscv64 容器及其他平台的新发布编排尚未在远端执行；不代表全部发布目标已经产出或通过原生验收。

A minimal C application completed native compilation, portable archiving, release
filename generation, job receipt aggregation, SHA-256 recomputation, and extracted
launch locally. Matrix output was checked for default Qt mode and source commit
pinning. Example coverage now declares 41 cases. The new FreeBSD VM, riscv64
container, and other release orchestration paths have not run remotely; this does
not claim that every release target has been generated or natively validated.
