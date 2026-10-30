# 发布构建 / Release builds

默认运行全部 build 配置，且全部启用 Qt 模式：`builds: all`、`mode: qt`。
共享工作流负责编排多个 runner；根目录 Action 用于已经准备好的单个 runner。
发布步骤单独授权，打包工作流不创建 Release，也不访问签名凭据。

All declared builds run in Qt mode by default: `builds: all`, `mode: qt`.
Use the reusable workflow to orchestrate multiple runners; use the root Action on
one already prepared runner. Publishing is separately authorized: the packaging
workflow neither creates releases nor accesses signing credentials.

## 调用 / Invocation

在应用仓库中添加以下工作流，将 `PIN` 替换为经过审核的同一个 WingSetup 提交。
配置与 Hook 是可信代码；不要将不受信任 PR 的配置放进有写权限或凭据的发布任务。

Add this workflow in the application repository. Replace both occurrences of `PIN`
with the same reviewed WingSetup commit. Configuration and hooks are trusted code;
do not run untrusted PR configuration in publishing jobs with write access or secrets.

```yaml
name: Packages
on:
  workflow_dispatch:
permissions:
  contents: read
jobs:
  packages:
    uses: Wing-summer/WingSetup/.github/workflows/package.yml@PIN
    with:
      framework-ref: PIN
      # Omit repository/ref to build the triggering application commit.
      repository: owner/application
      ref: v1.0.0
      build-config: mkinstaller/build.yml
      builds: all
      mode: qt
  release:
    needs: packages
    runs-on: ubuntu-24.04
    permissions:
      contents: write
    steps:
      - uses: actions/download-artifact@v8
        with:
          name: ${{ needs.packages.outputs.artifact-name }}
          path: release
      - name: Verify release files
        working-directory: release
        run: sha256sum --check SHA256SUMS.txt
      - name: Upload to an existing release
        env:
          GH_TOKEN: ${{ github.token }}
          GH_REPO: ${{ github.repository }}
          TAG: v1.0.0
        run: gh release upload "$TAG" release/*
```

Release 必须已存在；没有 `--clobber`，同名文件不会被覆盖。跨仓库构建时，输出仍属于调用方工作流，
发布仓库由调用方决定。私有源仓库需要调用方有读取权限；本版不传递 PAT。

The release must already exist. Without `--clobber`, existing assets are not replaced.
Cross-repository builds still produce artifacts in the caller's workflow; the caller
chooses the publishing repository. Private sources require caller read access; this
version does not forward a PAT.

## 构建配置 / Build configuration

`mkinstaller/build.yml` 将 runner、包配置及准备命令关联起来。以下是可改造的结构，
`prepare.py` 和目标名由应用仓库提供；不是对任意 C++ 仓库无需配置的承诺。

`mkinstaller/build.yml` links runners, package configurations, and preparation commands.
The following is an adaptable structure. The application owns `prepare.py` and the
target names; arbitrary C++ repositories still require project deployment configuration.

```yaml
schema_version: 1
builds:
  linux-x86_64:
    runner: ubuntu-24.04
    config: mkinstaller/linux-x86_64.yml
    targets: [appimage, deb, flatpak, arch, rpm, archive]
    prepare: [[python, mkinstaller/prepare.py, linux, x86_64]]
    qt_version: '6.8.3'
    qt_modules: qtsvg qtwayland
    qt_prepare: [[python, mkinstaller/prepare.py, qt, x86_64]]
  linux-aarch64:
    runner: ubuntu-24.04-arm
    config: mkinstaller/linux-aarch64.yml
    targets: [appimage, deb, flatpak, arch, rpm, archive]
    prepare: [[python, mkinstaller/prepare.py, linux, aarch64]]
    qt_prepare: [[python, mkinstaller/prepare.py, qt, aarch64]]
  linux-riscv64:
    runner: ubuntu-24.04
    system: riscv64
    config: mkinstaller/linux-riscv64.yml
    targets: [deb, rpm, archive]
    prepare: [[python3, mkinstaller/prepare.py, linux, riscv64]]
    qt_prepare: [[python3, mkinstaller/prepare.py, qt, riscv64]]
  windows-x64:
    runner: windows-latest
    config: mkinstaller/windows-x64.yml
    targets: [windows]
    qt_version: '6.8.3'
    qt_arch: win64_msvc2022_64
    qt_modules: qtsvg
    prepare: [[python, mkinstaller/prepare.py, windows, x64]]
  windows-arm64:
    runner: windows-11-arm
    config: mkinstaller/windows-arm64.yml
    targets: [windows]
    prepare: [[python, mkinstaller/prepare.py, windows, arm64]]
    qt_prepare: [[python, mkinstaller/prepare.py, qt, arm64]]
  macos-universal:
    runner: macos-15
    config: mkinstaller/macos.yml
    targets: [macos]
    qt_version: '6.8.3'
    qt_modules: qtsvg
    qt_prepare: [[python, mkinstaller/prepare.py, qt, universal2]]
  macos-cli-universal:
    runner: macos-15
    config: mkinstaller/macos-cli.yml
    targets: [cli]
    qt_version: '6.8.3'
    qt_prepare: [[python, mkinstaller/prepare.py, qt, universal2]]
  freebsd-x86_64:
    runner: ubuntu-24.04
    system: freebsd
    config: mkinstaller/freebsd.yml
    targets: [archive]
    prepare: [[pkg, install, -y, cmake, ninja]]
    qt_prepare: [[pkg, install, -y, qt6-base, qt6-svg]]
```

`targets` 按声明顺序运行，`builds` 可传逗号分隔 ID 选择子集。`prepare` 总是执行；
`qt_prepare` 仅 Qt 模式执行。`qt_version` 非空时复用 install-qt-action，适用于其支持的宿主；
FreeBSD 和 riscv64 等环境使用准备命令提供 Qt。`WINGSETUP_QT=true/false` 供项目脚本判断。
准备脚本写入 `GITHUB_PATH` 的工具路径会立即应用到当前构建；其他环境请由配置路径或 Hook 明确设置。
参数列表不经过隐式 shell；需要 shell 时显式调用。操作系统依赖只会由显式准备命令在 CI 中安装。

Targets execute in declared order. Select subsets with comma-separated build IDs.
`prepare` always runs; `qt_prepare` runs only in Qt mode. A nonempty `qt_version`
reuses install-qt-action on supported hosts. Prepare commands supply Qt for FreeBSD,
riscv64, or other unsupported SDK distributions. Scripts receive `WINGSETUP_QT=true/false`.
Tool directories written to `GITHUB_PATH` by preparation scripts apply immediately;
other environment settings belong in explicit configuration paths or hooks.
Commands use argument arrays without an implicit shell; explicitly invoke a shell
when required. OS dependencies are installed only through explicit CI preparation.

通用 tar.gz 使用 `backend: archive`、`platform: Linux/FreeBSD/Darwin`，可指定
`options.payload`；没有 payload 时复制入口文件。资源、Qt 插件、共享库和相对加载路径由部署 Hook 负责。
FreeBSD 在独立 VM 内编译并回传产物，`system: riscv64` 使用 Ubuntu runner 上的 QEMU 容器；Linux 文件不能只改名成 FreeBSD 文件。
macOS universal2 必须由构建命令设置 `CMAKE_OSX_ARCHITECTURES=arm64;x86_64`，
所有依赖也须包含双架构；框架会继续校验 Mach-O。GUI 使用 macos 后端的 dmg，CLI 可使用 archive 并设置 `options.format: zip`，保留链接与资源分支。
Windows `formats: [zip, inno]`，保持已确认的 EXE 安装器范围，不生成 MSI。

Use `backend: archive` with `platform: Linux/FreeBSD/Darwin` for portable tar.gz files.
An optional `options.payload` selects a complete tree; otherwise the entry is copied.
Deployment hooks own resources, Qt plugins, shared libraries, and relative loader paths.
FreeBSD builds inside its own VM and copies files back; `system: riscv64` uses a QEMU container on an Ubuntu runner; renaming Linux binaries does
not produce FreeBSD software. For macOS universal2, build commands must set
`CMAKE_OSX_ARCHITECTURES=arm64;x86_64`, and every dependency must contain both slices;
Mach-O validation remains enabled. Use the macos backend's dmg for GUI apps and archive
for CLI payloads (`options.format: zip` produces a symlink-preserving macOS CLI ZIP). Windows uses `formats: [zip, inno]`; the confirmed scope remains EXE,
without MSI.

AppImage 可设置 `options.filename: '{name}-{version}-{platform}-{arch}.AppImage'` 取得示例风格的文件名。

Set AppImage `options.filename: '{name}-{version}-{platform}-{arch}.AppImage'` for the illustrated naming style.

AppImage 的 `options.update_information` 将更新信息传给 appimagetool，要求预备 `zsyncmake`，
并将生成的 `.AppImage.zsync` 作为正式产物。若工具未生成该文件则失败。更新 URL 必须匹配最终文件名。

AppImage `options.update_information` forwards update information to appimagetool,
requires `zsyncmake`, and returns `.AppImage.zsync` as a real artifact. Missing requested
companions fail the build. Update URLs must match the final filenames.

## 发布接口 / Release contract

同一次 workflow 多次调用时指定不同 `artifact-prefix`，避免 artifact 名冲突。

Use distinct `artifact-prefix` values when calling the workflow multiple times in one run.

输出 `artifact-name`、`assets`（JSON）、`files`、`checksums`；下载 artifact 后获得所有包、
`SHA256SUMS.txt` 与 `release.json`。最终任务重新计算每个文件校验和，拒绝缺失任务、重复文件名或篡改文件。
文件名包含应用、版本、平台、架构；AppImage 保留原名以保持更新元数据有效，其他自定义格式也保留原名。
macOS 的 app.zip 与普通 zip 区分后缀。两份同架构 CLI/GUI 资产需要不同应用名或独立发布配置。

Outputs are `artifact-name`, `assets` (JSON), `files`, and `checksums`. Download the
artifact to obtain packages, `SHA256SUMS.txt`, and `release.json`. Collection rehashes
every file and rejects missing jobs, duplicate names, or tampering. Names include the
application, version, platform, and architecture. AppImages retain their original names
to preserve update metadata; custom formats retain theirs too. macOS app.zip and ordinary
zip have distinct suffixes. CLI and GUI assets of the same architecture need different
application names or separate release configurations.

同一 runner 使用根目录 Action 时 `target: all` 只选择当前宿主与架构匹配的配置，支持逗号分隔目标，
可传 `repository/ref/source-directory`。跨平台全量构建必须调用上述共享工作流。
打包成功不是原生安装或启动验收成功；新工作流提供构建结果，现有示例 CI 继续单独负责运行与安装验收。

On one runner, the root Action's `target: all` selects compatible host/architecture
entries; comma-separated targets and `repository/ref/source-directory` are supported.
Use the reusable workflow for all-platform builds. Successful packaging does not mean
successful native installation or launch. The new workflow reports builds; existing
example CI separately verifies launch and installation behavior.

参考 / References:
[GitHub artifacts](https://docs.github.com/en/actions/concepts/workflows-and-actions/workflow-artifacts),
[FreeBSD VM](https://github.com/vmactions/freebsd-vm),
[Qt setup](https://github.com/jurplel/install-qt-action),
[AppImage updates](https://docs.appimage.org/packaging-guide/optional/updates.html).
