# 跨平台架构与调研 / Cross-platform architecture and research

调研日期：2026-10-20。目标是统一构建、资源部署和产物报告，而不是把所有平台变成
Linux 安装树，也不是把每种最终产物都当作编译后的二进制包。

Research date: 2026-10-20. The goal is to unify builds, resource deployment and
artifact reporting without forcing every platform into a Linux tree or treating
every final product as a compiled binary package.

## 后端边界 / Backend boundaries

| backend | 平台 / Platform | 最终产物 / Final product | build 行为 / Build behavior |
| --- | --- | --- | --- |
| appimage | Linux | AppImage | 宿主项目构建 / Host project build |
| flatpak | Linux | .flatpak 与工作目录内的仓库 / .flatpak and retained repository | binary 宿主构建，sdk 内构建 / Host binary mode or SDK build |
| deb | Linux | .deb | 宿主项目构建 / Host project build |
| inno | Windows | Inno .exe、便携 ZIP / Inno .exe, portable ZIP | 宿主项目构建 / Host project build |
| macos | Darwin | .app 载荷 ZIP、ZIP、DMG / .app payload ZIP, ZIP, DMG | 原生 macOS 构建 / Native macOS build |
| aur | 有 bash/makepkg 的环境 / Environment with bash/makepkg | PKGBUILD + .SRCINFO 配方归档 / Recipe archive | 不编译 / No compilation |
| makeself | Linux / Darwin | 自解压 .run 或 .sh / Self-extracting .run or .sh | 构建显式 payload / Build an explicit payload |
| script | 任意 / Any | shell/Python 管理脚本归档 / Shell/Python manager archive | 不编译、不执行入口 / No build or entry execution |

每个后端有独立模块和 parse_options，registry 只保存工厂、解析器、平台、布局和产物类别。
core 负责四阶段与失败传播；validation 负责 YAML 边界；platforms 只描述路径，不运行工具。
旧 schema_version: 1 配置仍可使用；新增 target.platform 和 target.executable。

Each backend owns its module and parse_options. The registry stores factories,
parsers, platforms, layouts and artifact kinds. Core owns stages and failures,
validation owns the YAML boundary, and platforms describes paths without running
tools. Existing schema_version: 1 configurations remain usable; target.platform
and target.executable are new optional fields.

## 布局与资源 / Layouts and resources

| 布局 / Layout | app_dir | libraries / plugins |
| --- | --- | --- |
| AppImage | AppDir/usr/bin | AppDir/usr/lib、usr/plugins |
| Flatpak | root/files/bin | root/files/lib、files/plugins |
| deb | root/usr/lib/Name/bin | root/usr/lib/Name/lib、plugins |
| Windows | 暂存根目录 / Staging root | 暂存根目录、plugins / Staging root, plugins |
| macOS | Name.app/Contents/MacOS | Contents/Frameworks、Contents/PlugIns |
| 配方或便携 payload / Recipe or portable payload | 暂存根目录 / Staging root | 暂存根目录 / Staging root |

复制规则支持 root、prefix、app、resources、libraries、plugins。app 表示可执行文件相邻目录，
resources 表示平台推荐的资源位置，两者不能混同。已有应用若使用 applicationDirPath()
读取 lang/scripts，macOS 适配必须同步修改资源查找，不能把数据继续放入代码专用的
Contents/MacOS；应把数据部署至 Contents/Resources、业务插件部署至 Contents/PlugIns。
deb 由 /usr/bin 启动器进入私有 bin 目录，避免把业务资源直接铺在 /usr/bin。

Copy rules support root, prefix, app, resources, libraries and plugins. App means
executable-adjacent content, while resources means the platform resource location.
An application using applicationDirPath() for lang/scripts must update resource
lookups when ported to macOS. Data belongs in Contents/Resources and business
plugins in Contents/PlugIns, keeping data out of code-only Contents/MacOS. Deb uses
a /usr/bin launcher to reach a private bin directory rather than placing business
resources directly in /usr/bin.

macOS .app 是目录，保留在工作区；CI 的 app 格式输出为保留符号链接的 .app.zip。
Framework 版本链接必须保留，不能套用普通资源的解引用复制策略。
依据 [Qt macOS 部署文档](https://doc.qt.io/qt-6/macos-deployment.html)。

A macOS .app is a directory retained in the workspace. The CI app format emits a
symlink-preserving .app.zip. Framework version links must survive rather than use
ordinary resource dereferencing. See [Qt macOS deployment](https://doc.qt.io/qt-6/macos-deployment.html).

## 执行位置与验证 / Execution location and validation

四阶段始终保留前后 Hook。Flatpak SDK 不调用宿主 build；AUR/script 也不执行项目构建命令。
配方不包含公共的编译后资源，只添加其 recipe 和 target.resources。项目 deploy Hook 仍执行，
因此应用适配需按后端区分是否添加二进制。

All stages retain lifecycle hooks. Flatpak SDK skips host build, and AUR/script
skip project compilation commands. Recipes exclude common compiled resources and
copy their recipe plus target.resources. Project deploy hooks still run, so
application integrations must distinguish recipes before adding binaries.

AUR 使用项目维护的 PKGBUILD，不尝试另造 PKGBUILD 语言或用全局元数据猜依赖。
makepkg --printsrcinfo 会加载可信配方，但不执行完整构建；它必须由普通用户运行。
产物是配方包，不是可安装的 .pkg.tar.zst，也不会自动提交 AUR。
参见 [PKGBUILD](https://man.archlinux.org/man/PKGBUILD.5.en) 与 [makepkg](https://man.archlinux.org/man/makepkg.8.en)。

AUR uses project-maintained PKGBUILD files instead of inventing another recipe
language or inferring dependencies from global metadata. makepkg --printsrcinfo
loads trusted recipes without a full build and must run unprivileged. Its output
is a recipe archive, not an installable .pkg.tar.zst, and is never submitted to AUR
automatically. See [PKGBUILD](https://man.archlinux.org/man/PKGBUILD.5.en) and [makepkg](https://man.archlinux.org/man/makepkg.8.en).

Windows 使用 windeployqt 部署，之后由 ISCC 编译项目 ISS 模板；通用模板仅提供基本安装。
应用的既有 AppId、文件关联和语言必须放在应用模板中保留，不由框架猜测。
依据 [Qt Windows 部署](https://doc.qt.io/qt-6/windows-deployment.html) 和 [ISCC 命令行](https://jrsoftware.org/ishelp/topic_compilercmdline.htm)。

Windows deploys with windeployqt and compiles a project ISS template with ISCC.
The default template is minimal. Existing AppIds, associations and languages
belong in application templates rather than framework guesses. See [Qt Windows deployment](https://doc.qt.io/qt-6/windows-deployment.html)
and [ISCC command-line parameters](https://jrsoftware.org/ishelp/topic_compilercmdline.htm).

## 自解压与安装管理 / Self-extraction and installation management

Makeself 负责归档、校验和入口调用，应用自行提供 startup 脚本。打包过程只做 sh -n，
不执行安装器，也不调用 sudo。脚本本身的安装、升级和卸载策略由应用维护；script 后端
允许仅输出这些脚本。不能把“生成成功”当作安装管理行为已验证。
参见 [Makeself 官方说明](https://makeself.io/)。

Makeself handles archiving, integrity checks and entry invocation. Applications
provide startup scripts. Packaging runs sh -n without executing the installer or
sudo. Applications own installation, upgrade and uninstall policy; the script
backend can export only those scripts. Successful creation does not validate the
manager's behavior. See [Makeself](https://makeself.io/).

## 签名、公证与可复现输入 / Signing, notarization and reproducible inputs

macOS 默认 ad-hoc，不等于 Developer ID 签名。指定 sign_identity_env 后从 CI 环境读取身份；
notary_profile_env 还要求预配置 keychain profile。顺序为部署、嵌套代码/应用签名、验证、
notarytool 等待 Accepted、staple，再生成最终 ZIP；DMG 独立签名并公证。没有凭据不能
静默降级。Apple 私钥和密码不写入 YAML。真实验证必须在 macOS runner 完成。

macOS defaults to ad-hoc signing, not Developer ID signing. sign_identity_env reads
the identity from CI; notary_profile_env additionally requires a preconfigured
keychain profile. Deployment precedes nested/app signing, verification, an Accepted
notarytool result, stapling, and final ZIP creation. DMGs are signed and notarized
separately. Missing requested credentials cannot silently downgrade. Never put
Apple private keys or passwords in YAML. Real verification requires a macOS runner.

原生架构名统一为 x86_64/aarch64，macOS 额外支持 universal2；lipo 验证两种 slice。
这不表示 Python 自动实现交叉编译。构建命令须配置相应工具链与 CMake architecture。
依赖工具由 CI 准备，建议锁定下载 SHA-256；AppImage 可指定 runtime_file 避免隐式下载。

Native architecture names normalize to x86_64/aarch64, with universal2 additionally
supported on macOS and both slices verified by lipo. Python does not automatically
cross-compile; configure the toolchain and CMake architecture explicitly. CI
prepares tools; pin download SHA-256 values and use AppImage runtime_file to avoid
an implicit runtime download.

macOS 资源布局遵循 [Apple bundle 内容规则](https://developer.apple.com/documentation/bundleresources/placing-content-in-a-bundle)；
Windows 额外插件通过 [Qt 6.10 windeployqt](https://doc.qt.io/qt-6.10/windows-deployment.html) 的
--include-plugins 显式声明。

macOS resources follow [Apple bundle placement rules](https://developer.apple.com/documentation/bundleresources/placing-content-in-a-bundle).
Windows extra plugins use --include-plugins from
[Qt 6.10 windeployqt](https://doc.qt.io/qt-6.10/windows-deployment.html).
