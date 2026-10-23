# Changelog / 版本变更

本文件记录各版本对用户可见的变化。版本号以 `pyproject.toml` 为准；版本条目不表示已发布到包索引。
This file records user-visible changes by version. `pyproject.toml` defines the version;
a version entry does not imply publication to a package index.

## [0.0.1]

### Added / 新增

- macOS Intel 独立打包目标与原生启动 CI，以及 Ubuntu 22.04/26.04 双 LTS 打包基准。
  Separate macOS Intel packaging/native-launch CI and Ubuntu 22.04/26.04 LTS packaging baselines.

- 显式 Qt Wayland 部署与实际启动验收、平台资源筛选及打包排除规则、Inno 安装器定制。
  Explicit Qt Wayland deployment and launch validation, platform resource/output filters, and Inno installer customization.

- 彩色目标与阶段进度、Hook/命令状态、耗时提示及适合 CI 的纯文本日志。
  Colored target/stage progress, hook/command status, elapsed-time updates, and CI-friendly plain logs.
- YAML 配置的四阶段打包流水线、Python Hook、自定义后端和只读部署路径。
  YAML-configured four-stage packaging, Python hooks, custom backends, and read-only deployment paths.
- AppImage、Flatpak binary/SDK、deb、Windows Inno/ZIP、macOS app/ZIP/DMG 后端。
  Backends for AppImage, Flatpak binary/SDK, deb, Windows Inno/ZIP, and macOS app/ZIP/DMG.
- AUR release/-git 配方、管理脚本归档及 Makeself 自解压包；产物附带 SHA-256 校验值。
  AUR release/-git recipes, management-script archives, and Makeself installers, with SHA-256 output checksums.
- 基础 C 与 Qt Widgets 示例、以示例为基准的跨平台 CI，以及可复用打包 Action/workflow。
  Basic C and Qt Widgets examples, example-driven cross-platform CI, and a reusable packaging action/workflow.
