# 安装与桌面集成 / Installation and desktop integration

Windows 使用 Inno Setup，不引入 MSI。共享配置仅描述应用所需行为；后端按实际能力应用，
不支持的选项记录为 ignored。默认当前用户安装，不设置默认打开程序。

Windows uses Inno Setup, without MSI. Shared preferences describe intended behavior;
backends apply supported features and report unsupported ones as ignored. The default
is per-user installation without changing default applications.

## 配置 / Configuration

所有字段均可选，省略整个 installation 时保持旧配置行为。顶层配置作为共享值，
目标 installation 递归覆盖映射、整体替换列表；空列表用于清空继承的关联。
以下路径相对 YAML；可用 `{source}`、`{build}`、`{work}` 引用生成资源。

All fields are optional. Omitting installation preserves legacy behavior. Target
installation mappings recursively override shared mappings and replace complete
lists; empty lists clear inherited associations. Paths are relative to YAML;
`{source}`, `{build}`, and `{work}` may reference generated assets.

```yaml
installation:
  publisher: Example Project
  homepage: https://example.org
  support_url: https://example.org/support
  license_file: LICENSE.txt
  icons:
    linux: assets/app.svg
    windows: assets/app.ico
    macos: assets/app.icns
  scope: user
  directory: '{localappdata}\Programs\Example'
  shortcuts:
    start_menu: true
    desktop: true
  launch_after_install: true
  add_to_path: true
  autostart: true
  file_types:
    - id: project
      description: Example project document
      extensions: [.example-project]
      mime_type: application/x-example-project
      role: editor
      arguments: [--open, '{file}']
      icons:
        linux: assets/document.svg
        windows: assets/document.ico
        macos: assets/document.icns
  protocols:
    - scheme: example-project
      description: Example project URL
      arguments: [--url, '{url}']
  context_menu:
    - id: open
      label: Open with Example
      targets: [file, directory, background]
      arguments: ['{path}']
targets:
  windows:
    backend: inno
    platform: Windows
    arch: x86_64
    executable: '{build}/example.exe'
    installation:
      protocols: []
    options:
      formats: [inno, zip]
```

此片段需配合 application/project 元数据，不是独立配置。scope 仅接受 user/machine，
默认 user；directory 是 Windows 原生目录表达式。start_menu 默认 true，desktop、
launch_after_install、add_to_path、autostart 默认 false；设为 true 表示提供未勾选选项，
其中开始菜单为直接创建。文件关联默认参数 `['{file}']`，协议 `['{url}']`，
右键菜单 `['{path}']`；必须且只能出现一次完整输入占位符，不执行隐式 shell。
file_types 的 id、description、extensions、mime_type 必填，role 默认 editor，可为 viewer；
uti 可选，提供已知 UTI 时不生成导入声明。Windows 运行目录或文件参数都正确加引号。

This fragment requires application/project metadata. scope accepts user/machine
and defaults to user; directory is a native Windows directory expression.
start_menu defaults to true. desktop, launch_after_install, add_to_path, and
autostart default to false; enabling them offers an initially unchecked choice,
while Start menu creation is direct. Default handler arguments are `['{file}']`,
`['{url}']`, and `['{path}']`; exactly one complete input token is required, with no
implicit shell. File types require id, description, extensions, and mime_type.
role defaults to editor and also accepts viewer. Optional uti identifies a known
UTI without creating an imported declaration. Windows executable and input paths
are quoted separately.

平台图标必须分别提供 SVG/PNG、ICO、ICNS；框架不转换图像，也不修改 EXE 内嵌图标。
未使用平台的图标不检查是否存在。原有 application.icon 仍作为 Linux 回退。
显式 Inno options（如 default_dir、privileges、desktop_shortcut、setup 的同名指令）
优先于共享配置；原有 desktop_shortcut=true 的直接创建语义保留。

Supply SVG/PNG, ICO, and ICNS assets separately. The framework neither converts
images nor modifies executable icons. Assets for unused platforms need not exist.
application.icon remains the Linux fallback. Explicit Inno options such as
default_dir, privileges, desktop_shortcut, and corresponding setup directives take
precedence. Legacy desktop_shortcut=true still directly creates its shortcut.

## 能力表 / Capability matrix

| 功能 / Feature | Inno | deb/RPM/Arch | Flatpak | macOS app/ZIP/DMG | AppImage | ZIP/配方/自解压 / recipes/self-extracting |
| --- | --- | --- | --- | --- | --- | --- |
| 应用/文档图标 / App/document icons | 安装器、快捷方式、卸载显示 / Installer, shortcuts, uninstall display | 标准主题目录 / Theme hierarchy | 合规导出 / Exported | Bundle Resources | AppDir 内 / Inside AppDir | Windows ZIP 携带 ICO / Windows ZIP carries ICO |
| 文件/URL 处理声明 / File/URL declarations | ProgID + Capabilities 候选 / Candidates | desktop + MIME XML | desktop + MIME export | Bundle document/URL types | 包内元数据 / Embedded metadata | 忽略 / Ignored |
| 用户/机器范围与安装目录 / Scope/directory | 支持 / Supported | 包管理器决定 / Package manager | Flatpak 决定 / Flatpak | 用户复制位置决定 / User copy location | 不适用 / N/A | 忽略 / Ignored |
| PATH/自启/右键 / PATH/startup/context menu | 可选 / Optional | 忽略 / Ignored | 自启需应用 portal / App portal required | 忽略 / Ignored | 忽略 / Ignored | 忽略 / Ignored |
| 安装后启动 / Post-install launch | 用户可选，静默跳过 / Optional; skipped silently | 忽略 / Ignored | 忽略 / Ignored | 忽略 / Ignored | 忽略 / Ignored | 忽略 / Ignored |
| 许可证文件 / License file | 携带并显示 / Carried and shown | 应用专属目录 / App namespace | 应用专属目录 / App namespace | Bundle Resources | 包内携带 / Carried | 携带 / Carried |

能力表表示生成能力，不等于系统安装已验收。每个目标生成 installation.json，按实际产物
逐字段记录 applied/ignored 与原因；同一 Inno 目标的 ZIP 不会被报告为执行过注册表集成。
CLI 输出摘要，复用 Action 的 installation-report 输出提供报告路径；artifacts.json 不变。

The matrix describes generation capabilities, not completed installation acceptance.
Each target writes installation.json with per-output applied/ignored fields and
reasons. A ZIP from an Inno target never claims registry integration. CLI output
summarizes results; the reusable Action exposes installation-report. artifacts.json
retains its existing structure.

## Windows 所有权、升级与卸载 / Windows ownership, upgrades and uninstall

Inno 仅写本应用 ProgID 和 Capabilities、RegisteredApplications、OpenWithProgids 候选值，
不写 UserChoice 或扩展名的默认值。协议也注册为候选，不接管已有 scheme。
右键菜单使用应用专属 verb，Windows 11 可能放在“显示更多选项”中。

Inno writes application-owned ProgIDs/Capabilities, RegisteredApplications, and
OpenWithProgids candidate values, without UserChoice or extension defaults. URL
handlers are candidates and do not take over an existing scheme. Explorer verbs
are application-owned and may appear under Windows 11's Show more options.

安装范围决定 HKCU/HKLM；机器安装不修改提升身份的个人登录自启。PATH 逐项比较，
忽略大小写、外层引号及尾部目录分隔符；保留原有值类型和其他项。不解析目录联接或将
环境变量表达式视作等价路径。只记录并删除本安装新增的项，已有项不会被认领。
稳定 AppId 复用目录与任务选择；升级清理此前管理而本次移除的关联，卸载不删除用户数据。
Inno 本身并非完整事务安装器，不承诺任意中断后的全量回滚，也不实现自动更新下载器。

Scope selects HKCU/HKLM; machine installs do not alter the elevated identity's
personal login startup. PATH comparison ignores case, outer quotes, and trailing
separators while preserving other tokens and registry storage type. Junctions and
environment-variable expressions are not resolved as equivalent paths. Only entries
added by this installation are owned and removed. Stable AppId retains directory
and task choices; upgrades remove obsolete managed associations, and uninstall
preserves user data. Inno is not fully transactional: arbitrary-interruption
rollback and an update downloader are not provided.

自定义 ISS 必须同时含 @SETUP_DIRECTIVES@ 与 @INSTALLATION_SECTIONS@ 才启用共享安装行为；
未接入时跳过并报告。新增内容使用 Wing 前缀与 Inno 事件属性，保留已有事件回调。
项目模板不得重复定义 Wing 前缀符号。原生 file_excludes/desktop_shortcut 与自定义模板的
旧限制不变。示意模板见 [inno-shared.iss](../examples/basic/recipes/inno-shared.iss)。

Custom ISS opts in using both @SETUP_DIRECTIVES@ and @INSTALLATION_SECTIONS@;
otherwise shared installer behavior is skipped and reported. Generated code uses
Wing-prefixed symbols and event attributes, preserving existing event callbacks.
Templates must not redefine Wing-prefixed symbols. Existing custom-template limits
for native file_excludes/desktop_shortcut remain. See the
[illustrative template](../examples/basic/recipes/inno-shared.iss).

## 桌面系统边界 / Desktop system boundaries

Linux 用独立隐藏 desktop handler 保留每种文件/URL 的参数契约，并保留主 desktop 的注释、
本地化字段和已有处理项。不修改 mimeapps.list；依赖发行版缓存触发机制，不在构建宿主刷新
数据库。AppImage 仍需外部桌面集成工具。Flatpak 不增加权限，自启需应用调用 Background portal。
macOS 在签名前合并 bundle 声明，使用 Alternate 处理等级；应用必须处理系统文件打开事件。

Linux uses separate hidden handlers to retain per-file/URL arguments, preserving
the primary desktop's comments, localized fields, and existing handlers. It never
writes mimeapps.list or refreshes host caches; distro triggers handle installation.
AppImage still needs external desktop integration. Flatpak gains no extra permission;
autostart requires the application Background portal. macOS merges declarations
before signing and uses Alternate handler rank; applications must process OS file-open events.

## 验证 / Verification

Windows 的安装、升级、卸载仅由显式 `ci/examples.py --case qt-windows --verify-installation`
在 GitHub 临时 runner 执行，不由框架或复用 Action 自动执行。检查默认关联不变、快捷方式、
PATH 类型/所有权、失效关联清理、升级目录/任务保留及卸载保留用户数据。测试只检查自启值，
不触发重新登录。失败日志位于目标输出的 installation-validation 目录。

Windows install/upgrade/uninstall runs only through the explicit example entry
above on ephemeral GitHub runners, never implicitly through the framework or
reusable Action. It checks unchanged defaults, shortcuts, PATH type/ownership,
obsolete handlers, retained upgrade directory/tasks, and preserved user data.
Startup values are inspected without logging in again. Failure logs remain under
the target's installation-validation output directory.

参考 / References: [Inno registry](https://jrsoftware.org/ishelp/topic_registrysection.htm),
[Inno events](https://jrsoftware.org/ishelp/topic_scriptevents.htm),
[Windows app registration](https://learn.microsoft.com/en-us/windows/win32/shell/app-registration),
[desktop specification](https://specifications.freedesktop.org/desktop-entry/latest/),
[Flatpak exports](https://docs.flatpak.org/en/latest/conventions.html),
[Background portal](https://flatpak.github.io/xdg-desktop-portal/docs/doc-org.freedesktop.portal.Background.html),
[Apple bundle keys](https://developer.apple.com/library/archive/documentation/General/Reference/InfoPlistKeyReference/Articles/CoreFoundationKeys.html).
