# GitHub CI 集成 / GitHub CI integration

## 分层 / Layers

- `.github/workflows/ci.yml`：Linux、Windows、macOS 的 Python 3.11/3.14 单元与 strict 检查。
  / Unit and strict checks on Linux, Windows and macOS with Python 3.11/3.14.
- `action.yml`：把框架装入 .venv-ci，运行一个目标，输出包、校验文件和报告路径。
  / Install the framework in .venv-ci, run one target and return bundle/checksum/report paths.
- `.github/workflows/package.yml`：可复用 workflow_call，分别 checkout 应用与框架，准备 Qt/MSVC，
  调用应用自己的 setup 脚本和本地 action，再上传产物。
  / Reusable workflow_call checking out application/framework, preparing Qt/MSVC, invoking
  an application setup script and local action, then uploading artifacts.

四阶段日志实时写入日志文件并输出到 CI；失败目录保留 failure.log。每次运行写入
artifacts.json；composite action 还输出目标级汇总，包含 backend、host、arch、kind 和 SHA-256。
不把整个 build 缓存目录当作可发布产物。

Stage output streams to both logs and CI. Failed work directories retain failure.log.
Each run records artifacts.json; the composite action also emits a target summary
with backend, host, arch, kind and SHA-256. Entire build cache directories are not
misrepresented as release artifacts.

## 复用方式 / Reuse

应用工作流先 checkout 已审阅的框架 ref 到 framework，再使用本地 action：
An application workflow checks out a reviewed framework ref into framework, then
uses its local action:

```yaml
- uses: ./framework
  id: package
  with:
    config: application/packaging/package.yml
    target: macos
- uses: actions/upload-artifact@v7
  with:
    name: package-macos
    path: ${{ steps.package.outputs.artifact-paths }}
    if-no-files-found: error
```

此片段是步骤示意，不是独立工作流。setup-python、Qt、原生工具和签名 keychain 必须事先准备。
框架仓库 URL 尚由发布者确定，因此不在示例中虚构仓库地址。可复用工作流要求调用方显式传入
application_repository/ref、framework_repository/ref、runner、config 和 target。

This is a step illustration, not a standalone workflow. Prepare Python, Qt, native
tools and signing keychains first. The publisher determines the framework repository
URL, so examples do not invent one. The reusable workflow requires explicit
application_repository/ref, framework_repository/ref, runner, config and target.

调用 reusable workflow 的 uses 路径必须是静态 ref，不能用表达式拼仓库名。将其发布位置
固定后，由应用写明完整路径；工作流内部的 checkout 输入可以是参数。
依据 [GitHub 工作流复用文档](https://docs.github.com/en/actions/how-tos/reuse-automations/reuse-workflows)。

The uses path calling a reusable workflow must be a static ref, not an expression
assembling a repository name. Applications specify the full published path once
it is known; internal checkout inputs may remain parameterized. See [GitHub workflow reuse](https://docs.github.com/en/actions/how-tos/reuse-automations/reuse-workflows).

## 可复用组件选择 / Component choices

| Action | 用途 / Purpose |
| --- | --- |
| actions/checkout@v7 | 递归子模块与独立框架 checkout / Recursive submodules and separate framework checkout |
| actions/setup-python@v7 | 明确 Python 版本，依赖仍装在 venv / Explicit Python version; dependencies remain in venv |
| jurplel/install-qt-action@v4 | Qt 工具链与其内置缓存 / Qt toolchain and its built-in cache |
| ilammy/msvc-dev-cmd@v1 | Windows 原生编译环境 / Windows native compiler environment |
| actions/upload-artifact@v7 | 仅上传真实产物与校验信息 / Upload actual artifacts and verification metadata |
| actions/cache@v5（应用侧可选 / optional application-side） | 按工具锁文件缓存下载工具 / Cache downloaded tools by lock file |

这些选择参考维护者的官方说明：[checkout](https://github.com/actions/checkout)、
[setup-python](https://github.com/actions/setup-python)、[Qt action](https://github.com/jurplel/install-qt-action)、
[artifact](https://github.com/actions/upload-artifact)。生产环境可进一步固定为审阅过的 commit SHA。

These choices follow maintainer documentation: [checkout](https://github.com/actions/checkout),
[setup-python](https://github.com/actions/setup-python), [Qt action](https://github.com/jurplel/install-qt-action),
and [artifact](https://github.com/actions/upload-artifact). Production deployments may further
pin reviewed commit SHAs.

## runner、权限与凭据 / Runners, permissions and credentials

原生打包必须选择对应 OS；Linux 上的模拟命令测试不等于 Windows/macOS 构建。
macos-latest 当前是 arm64；Intel 可显式选择 macos-15-intel 或 macos-26-intel，
不能仅凭 latest 假定架构。参见 [GitHub runner 表](https://docs.github.com/en/actions/reference/runners/github-hosted-runners)。

Native packaging requires the corresponding OS. Mocked commands on Linux do not
validate Windows/macOS builds. macos-latest currently denotes arm64; Intel can use
explicit macos-15-intel or macos-26-intel labels. Do not infer architecture from
latest alone. See [GitHub's runner table](https://docs.github.com/en/actions/reference/runners/github-hosted-runners).

默认权限 contents: read，不自动发布 release、推送 AUR 或执行安装器。带签名凭据的 job
只应运行可信 ref；keychain 由应用 bootstrap 或受控 runner 准备。框架只读取签名身份和
notary profile，缺少凭据时报错。应用特定证书与 Apple 签名属于不同机制，不能默认串联。

Permissions default to contents: read. No release publishing, AUR pushes or installer
execution occurs automatically. Credentialed jobs should run trusted refs only;
application bootstrap or controlled runners provision the keychain. The framework
reads identities and notary profiles and fails if requested credentials are missing.
Application-specific certificates and Apple signing are separate mechanisms and
must not be chained implicitly.

可复用 action 不安装系统依赖。可复用 workflow 的 setup_script 是应用拥有的显式准备入口，
可以在临时 runner 上装工具；本机运行时仍应把无需权限的依赖放入工作区。
归档后的包保留其权限和链接；不要直接上传散开的 .app 或可执行文件树后假设下载仍保留权限。

The reusable action installs no system dependencies. The reusable workflow's
setup_script is an explicit application-owned preparation entry that may install
tools on ephemeral runners. Local unprivileged dependencies should remain in the
workspace. Archives preserve permissions and links; uploading loose .app or
executable trees does not guarantee that downloaded files retain permissions.

Linux 原生打包和 Flatpak 用例分别覆盖最新 LTS Ubuntu 26.04 与最老仍受标准支持的
LTS Ubuntu 22.04。此选择依据 [Ubuntu 生命周期](https://ubuntu.com/about/release-cycle)，
固定 runner 标签便于审阅；LTS 支持到期或新 LTS 发布后应更新清单与矩阵。
macOS 分别使用 `macos-15` Apple Silicon arm64 和 `macos-15-intel` x86_64 原生 runner。
无需本地 Apple 电脑；提交后由 GitHub runner 完成打包、签名校验和归档内程序启动测试。

Native Linux and Flatpak cases run on both the newest LTS, Ubuntu 26.04, and the
oldest LTS under standard support, Ubuntu 22.04, following the
[Ubuntu lifecycle](https://ubuntu.com/about/release-cycle). Explicit runner labels
make the policy reviewable; update the manifest and matrices when support expires
or a new LTS arrives. macOS uses separate native `macos-15` Apple Silicon arm64 and
`macos-15-intel` x86_64 runners. A local Apple computer is unnecessary: GitHub runners
perform packaging, signature checks, and launches from the archives after submission.

Linux Qt 示例使用各 Ubuntu 仓库的 Qt 开发包、Linguist、SVG 和 Wayland 模块，
不向 Ubuntu 22.04 注入新 glibc 基线的 Qt 官方二进制。参见
[Qt Linux 二进制兼容说明](https://doc.qt.io/qt-6.10/linux.html)。Flatpak 仍使用 manifest
指定的 KDE 6.10 runtime/SDK，宿主 LTS 与沙箱 runtime 分别记录。
两个基线各自构建并运行，不代表新版系统生成的包可以在旧 LTS 运行；发布兼容旧系统的包
应在最老基线构建，再做跨版本启动验收。Deepin/KDE Neon 不在本矩阵中。

The Linux Qt fixture uses each Ubuntu archive's Qt development packages, Linguist,
SVG, and Wayland modules, avoiding newer-glibc Qt installer binaries on Ubuntu 22.04.
See [Qt's Linux binary compatibility guidance](https://doc.qt.io/qt-6.10/linux.html).
Flatpak retains the manifest's KDE 6.10 runtime/SDK; host LTS and sandbox runtime are
separate baselines. Each endpoint builds and runs independently: packages built on
a newer system are not thereby compatible with the older LTS. Build releases for
older systems on the oldest baseline and perform cross-version launch acceptance.
Deepin/KDE Neon are outside this matrix.

## 示例测试基准 / Example test baseline

`ci/examples.json` 是覆盖约定，工作流以显式矩阵列出每个用例。plan job 验证这些
矩阵与每个示例配置目标、八种内置后端一致，并输出计划覆盖表。完整流程和职责见 [.github/README.md](../.github/README.md)。

`ci/examples.json` defines the coverage contract; explicit workflow matrices list
each case. The plan job checks alignment with every example target and all eight
built-in backends, then publishes the planned coverage table. See [.github/README.md](../.github/README.md) for workflow responsibilities.

| 测试组 / Group | 示例及产物 / Examples and outputs |
| --- | --- |
| Linux / Ubuntu 22.04 + 26.04 | basic AppImage、deb、Makeself .run/.sh、自定义 tar；Qt Widgets AppImage / basic AppImage, deb, Makeself .run/.sh, custom tar; Qt Widgets AppImage |
| Flatpak / Ubuntu 22.04 + 26.04 | basic binary、basic SDK、Qt Widgets SDK / basic binary, basic SDK, Qt Widgets SDK |
| Windows x86_64 | Qt Widgets Inno .exe 与便携 ZIP / Qt Widgets Inno .exe and portable ZIP |
| macOS arm64 + Intel x86_64 | Qt Widgets .app.zip、ZIP、DMG / Qt Widgets .app.zip, ZIP, DMG |
| Arch 容器 / container | basic AUR release/-git 配方及 Python/shell 管理脚本归档 / basic AUR release/-git recipes and Python/shell management archive |

每个包都检查 SHA-256 和 sidecar；可启动载荷从生成包解出后运行，AppImage 使用无 FUSE
启动，Flatpak 从构建树运行且不安装。macOS 的 ZIP 用 ditto 保留链接，DMG 只读挂载。
Windows Inno 仅生成与校验；启动测试来自同次部署生成的 ZIP，不声称安装器已执行。
AUR 只验证配方及 .SRCINFO，不抓取模板仓库或编译 .pkg.tar.zst。

Each artifact is checked against SHA-256 and its sidecar. Launchable payloads run
after extraction; AppImage uses FUSE-free launching and Flatpak runs from its build
tree without installation. macOS ZIP extraction preserves links with ditto and
DMGs mount read-only. Windows Inno is generated and checksum-checked; launching
uses the ZIP from the same deployment, without claiming installer execution.
AUR checks recipe contents and .SRCINFO without fetching template repositories
or building .pkg.tar.zst packages.

Qt 启动测试移除宿主 Qt 插件和库环境变量，并从 PATH 排除 Qt SDK，检查翻译、资源、
动态插件及私有库。每个目标输出 validation.json，成功仅表示所记录的检查完成。
凭据相关的 Developer ID、公证以及 universal2 不属于公共 CI 的实际运行矩阵。

Qt launch tests remove host Qt plugin/library overrides and exclude the Qt SDK
from PATH, then verify translations, resources, dynamic plugins, and private
libraries. Each target emits validation.json recording completed checks. Developer
ID signing, notarization, and universal2 are outside the public
CI execution matrix.

Python 环境准备统一为 `ci/environment.py`，包依赖只安装在 `.venv-ci`。Linux 工具由
`ci/tools.lock.json` 校验后放入 `.tools/ci`，本地可执行
`python ci/prepare.py linux --tools-only`，不会安装系统依赖。

`ci/environment.py` centralizes Python setup with dependencies confined to
`.venv-ci`. Linux tools are verified against `ci/tools.lock.json` and stored in
`.tools/ci`. Locally, `python ci/prepare.py linux --tools-only` prepares downloads
without installing system dependencies.

## 最终验收检查 / Final acceptance check

示例工作流最后的 `all-examples` job 收集每个用例上传的小型执行记录，Summary 逐项
显示状态、产物格式、SHA-256 和启动结果。缺失、失败、记录过期或产物格式不全均失败；
只有本次 run/attempt/commit 的 24/24 用例及其前置任务全部成功才通过。该 job
不下载所有大型安装包，也不根据“配置存在”推断测试通过。可将其加入分支保护。

The example workflow's final `all-examples` job collects small execution receipts
and summarizes each case's status, output formats, SHA-256 checks, and launches.
Missing, failed, stale, or incomplete evidence fails acceptance. Only 24/24 cases
from the current run/attempt/commit, together with successful prerequisite jobs,
pass. The job does not download every large package or infer success from the
presence of configuration. It can serve as a required branch-protection check.

记录下载使用 [actions/download-artifact](https://github.com/actions/download-artifact)
的过滤与合并功能；这里的汇总机制尚需远端实际运行验证。
Receipt collection uses filtering and merging from
[actions/download-artifact](https://github.com/actions/download-artifact). Remote
execution is still required to validate the workflow end to end.

Qt AppImage 现在同时要求 offscreen 和实际 Wayland 启动。Linux CI 显式准备 qtwayland
模块和 headless Weston，使用独立运行目录及私有 socket；任何 Wayland 启动失败或
执行记录缺少 wayland=true，最终汇总均失败。它验证 Wayland 客户端启动，不等同于所有
GPU、桌面合成器或输入法的兼容性矩阵。

Qt AppImage now requires both offscreen and actual Wayland launches. Linux CI
prepares the distro Qt Wayland module and headless Weston, using a private runtime
directory and socket. A failed launch or missing wayland=true evidence fails
final aggregation. This verifies Wayland client startup rather than every GPU,
desktop compositor, or input-method combination.

Ubuntu 22.04 的 SVG 开发包为 `libqt6svg6-dev`，26.04 使用 `qt6-svg-dev`；
准备脚本读取 runner 的 `/etc/os-release` 选择包名。22.04 的插件随 `libqt6svg6` 提供，
26.04 显式安装独立的 `qt6-svg-plugins` 包。
测试比较配置文件路径时使用解析后的规范路径，兼容 macOS `/var` 到 `/private/var`
和 Windows 临时目录别名。

Ubuntu 22.04 names the SVG development package `libqt6svg6-dev`, while 26.04 uses
`qt6-svg-dev`. Provisioning selects the name from the runner's `/etc/os-release`. Jammy includes
SVG plugins in `libqt6svg6`; 26.04 installs the separate `qt6-svg-plugins` package. Tests compare resolved
configuration paths, accommodating macOS `/var` to `/private/var` and Windows
temporary-directory aliases.

Qt Widgets 的 Linux 构建显式安装 `libgl-dev`、`libopengl-dev` 和 `libegl-dev`，
提供 QtGui/WrapOpenGL 的头文件及链接库；仅有 `libgl1`、`libegl1` 运行库不能满足
CMake 的开发依赖检查。这些包仅由临时 CI runner 的准备步骤安装。

Linux Qt Widgets builds explicitly install `libgl-dev`, `libopengl-dev`, and
`libegl-dev` for QtGui/WrapOpenGL headers and link libraries. The `libgl1` and
`libegl1` runtime packages alone do not satisfy CMake development checks. Only
the disposable CI runner provisioning step installs these packages.

Qt Linguist 命令行程序来自独立的 `qt6-l10n-tools` 包，两个 LTS 均显式安装。
准备脚本通过 `qmake6 -query QT_HOST_BINS` 定位工具目录并实际运行 `lconvert`、
`lrelease`、`lupdate` 的帮助命令，避免只有 CMake 导入声明却没有对应可执行文件。

Qt Linguist executables come from the separate `qt6-l10n-tools` package, installed
explicitly on both LTS endpoints. Provisioning locates tools with
`qmake6 -query QT_HOST_BINS` and runs the help commands of `lconvert`, `lrelease`,
and `lupdate`, rejecting installations with CMake imports but missing executables.
