# Repository guidance / 仓库协作规范

## Scope and structure / 范围与结构

- Keep the framework generic. Application-specific adapters belong in the application's own packaging directory. Preserve unrelated working-tree changes.
  框架保持通用；具体应用的适配放在应用自己的打包目录，保留无关工作区改动。
- Maintain exactly two example roots: `examples/basic` and `examples/qtwidgets`. Keep each backend in its own module; register capabilities in `registry.py` and use `DeploymentLayout` for destination paths.
  示例根目录仅保留 `examples/basic` 和 `examples/qtwidgets`。后端分别存放，能力在 `registry.py` 注册，部署路径使用 `DeploymentLayout`。
- Keep the lifecycle `prepare → build → deploy → package`. Failed stages skip their after hook and later stages. SDK builds and recipes must not invoke host compilation.
  保持四阶段生命周期；失败时跳过对应 after Hook 和后续阶段。SDK 构建及配方不得调用宿主编译。

## Python and documentation / Python 与文档

- Require Python 3.11+ and Pyright strict. Validate YAML at the boundary into immutable typed models; do not spread `Any` or accept unknown fields.
  使用 Python 3.11+ 和 Pyright strict。YAML 在边界验证并转为不可变类型模型，不扩散 `Any`，不接受未知字段。
- Document every Python module, class, function, and method in English using PEP 257 docstrings and Google-style sections where applicable. Describe parameters, results, relevant failures, and lifecycle behavior. Document every declared field and instance attribute with `#:` comments.
  所有 Python 模块、类、函数和方法使用英文 PEP 257 文档字符串，适用时使用 Google 风格段落，说明参数、结果、异常和生命周期。声明字段及实例属性使用 `#:` 注释。
- Keep code comments in English. Keep prose documentation bilingual in Chinese and English in the same file. LICENSE remains English only.
  代码注释使用英文，说明文档在同一文件采用中英双语；LICENSE 仅保留英文。
- Add the existing English copyright/SPDX header to source and comment-capable configuration files. Framework contributions use BSD-3-Clause; preserve other projects' licenses. Do not put comments in JSON or empty marker files.
  源码及支持注释的配置使用现有英文版权/SPDX 文件头；框架采用 BSD-3-Clause，保留其他项目许可。JSON 和空标记文件不添加注释。
- Use `ctx` or the read-only `paths` namespace for target-local paths. Do not inject mutable process globals, hard-code local checkout paths, or cache a run-specific path at import time.
  目标路径使用 `ctx` 或只读 `paths`，不注入可变进程全局状态，不写入机器专属路径，不在导入时缓存运行路径。

## Dependencies and validation / 依赖与验证

- Install Python dependencies in a workspace virtual environment and unprivileged tools in the workspace. Local runs must not install system packages, add Flatpak remotes, or install runtimes automatically. CI preparation may explicitly provision ephemeral runners.
  Python 依赖安装到工作区虚拟环境，无需权限的工具放在工作区。本地不自动安装系统包、添加 Flatpak remote 或安装 runtime；CI 可显式准备临时 runner。
- Run `.venv/bin/python -m pyright`, `.venv/bin/python -m pytest -q`, and relevant packaging checks. Windows uses `.venv/Scripts/python.exe`. Validate workflow edits with actionlint when available.
  执行 strict、测试及相关打包检查；Windows 使用对应虚拟环境路径，工作流可用时通过 actionlint 验证。
- Use the example coverage manifest in `ci/examples.json` for real packaging CI. Every built-in backend and every configured example target must be covered. Keep the explicit workflow matrices aligned with the manifest; the final result gate must reject missing or failed execution receipts. Verify checksums, metadata, and launch behavior separately; never treat mock tests as native packaging evidence.
  真实打包 CI 使用 `ci/examples.json` 覆盖清单，涵盖所有内置后端及示例目标。显式工作流矩阵须与清单一致，最终汇总不得接受缺失或失败的执行记录。分别验证校验值、元数据和启动，不把模拟测试当作原生打包证据。
- Keep CI steps named and responsibilities separated. Never run installers, publish releases, push AUR changes, or access signing credentials implicitly in pull-request checks.
  CI 步骤明确命名并分清职责；PR 检查不隐式运行安装器、发布 release、推送 AUR 或访问签名凭据。

## Release and repository hygiene / 版本与仓库维护

- The initial framework version is `0.0.1`. Keep `pyproject.toml` and versioned CHANGELOG entries consistent. Record user-visible release changes, not a development transcript.
  框架初版为 `0.0.1`，保持项目版本与 CHANGELOG 对应。变更日志记录面向用户的版本变化，不记录开发过程。
- Do not commit virtual environments, downloaded tools, caches, work directories, packages, local editor workspaces, or credentials. Keep `.gitignore` scoped so example sources and recipe scripts remain visible.
  不提交虚拟环境、下载工具、缓存、工作目录、产物、本机编辑器工作区或凭据。忽略规则不得隐藏示例源码及配方脚本。
