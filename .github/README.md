# Workflows / 工作流

| 文件 / File | 职责 / Responsibility |
| --- | --- |
| `workflows/ci.yml` | Python 3.11/3.14 的跨平台 strict 与单元测试 / Cross-platform strict checks and unit tests on Python 3.11/3.14 |
| `workflows/examples.yml` | 显式列出全部矩阵用例，执行真实打包与汇总检查 / Explicit matrices for real packaging and complete-result verification |
| `workflows/package.yml` | 供外部应用调用的显式参数化打包入口 / Explicitly parameterized reusable packaging for external applications |
| `actions/python-env/action.yml` | 本仓库 CI 的虚拟环境准备 / Repository CI virtual-environment preparation |
| `../action.yml` | 外部应用可复用的单目标打包 Action / Reusable single-target packaging action for applications |

每个工作流使用有含义的 job/step 名称；系统依赖准备、构建与验证逻辑分别位于
`ci/prepare.py`、`ci/examples.py`，避免在 YAML 中嵌入长脚本。工具缓存按 SHA-256 锁文件隔离。

Workflows use descriptive job and step names. System provisioning and build/verification
logic live in `ci/prepare.py` and `ci/examples.py`, keeping long scripts out of YAML.
Tool caches are separated by the SHA-256 lock file.

示例测试不执行安装入口、不发布 release 或推送 AUR，不使用 Apple 凭据。新增示例目标或
后端时必须更新覆盖清单；遗漏会在 plan job 和单元测试中失败。原生运行结果以对应 runner
实际执行为准，工作流静态校验不能代替执行。

Example checks do not execute installer entries, publish releases, push AUR changes,
or use Apple credentials. Add coverage entries whenever targets or backends are added;
omissions fail the plan job and unit tests. Native results require actual runner
execution; workflow linting is not a substitute.

## 如何确认全部测试 / How to confirm complete coverage

打开 `workflows/examples.yml` 即可看到全部用例：linux 12 个、flatpak 6 个、native 3 个、
recipes 3 个。AUR release、AUR git、脚本导出是三个独立的矩阵任务，不再隐藏在单个组内。
覆盖检查会对照 `ci/examples.json` 和全部示例目标，拒绝漏项、重复项或错误 runner。

`workflows/examples.yml` lists every case: 12 linux, six flatpak, three native,
and three recipes. AUR release, AUR git, and script export are separate matrix
jobs rather than hidden group members. Coverage checks compare these matrices
with `ci/examples.json` and all configured targets, rejecting omissions, duplicates,
and incorrect runners.

GitHub Actions Summary 中有两张表：
GitHub Actions Summary contains two tables:

1. **计划覆盖 / Planned coverage**：列出用例、runner、产物格式和启动要求，不表示已通过。
   Lists cases, runners, output formats, and launch requirements without claiming execution.
2. **实际执行结果 / Execution results**：逐项显示 PASS、FAIL、MISSING 或 INVALID，
   同时列出校验与启动结果。
   Shows PASS, FAIL, MISSING, or INVALID for each case, including checksum and launch evidence.

最后的 **All 24 example cases passed** job 始终执行汇总，必须收齐本次 run/attempt/commit
的 24 份成功记录，全部预期格式和必需启动检查均通过，前置 job 也全部成功才会变绿。
准备工具失败、取消或跳过导致的缺失记录不会被当作通过。分支保护可要求这一检查。

The final **All 24 example cases passed** job always aggregates results. It requires
24 successful receipts matching the current run, attempt, and commit, all expected
formats and required launches, and successful prerequisite jobs. Missing evidence
from provisioning failure, cancellation, or skipping cannot count as passed. This
check can be required by branch protection.

安装器入口、Apple Developer ID、公证、universal2 仍不在该基准中。Inno 的启动
检查来自同次部署的 ZIP，AUR/管理脚本验证导出内容，不执行安装或源码构建。

Installer execution, Apple Developer ID signing, notarization, and universal2
remain outside this baseline. Inno launch checks use the ZIP from the same staged
payload. AUR and management-script checks validate exported content without
installation or source compilation.

Linux 与 Flatpak 的每个目标分别在 Ubuntu 22.04、26.04 执行，产物及记录名称互不覆盖。
macOS arm64 (`macos-15`) 与 Intel (`macos-15-intel`) 分别打包和启动全部三种归档格式。
Qt AppImage 两个 LTS 用例均须通过 offscreen 与私有 Weston Wayland 启动。

Every Linux and Flatpak target runs on Ubuntu 22.04 and 26.04, with distinct artifact
and receipt names. Separate macOS arm64 (`macos-15`) and Intel (`macos-15-intel`) jobs
package and launch all three archive formats. Both Qt AppImage LTS cases require
offscreen and private Weston Wayland launches.

`actionlint.yaml` 补充旧版 actionlint 尚未收录的官方 `ubuntu-26.04` 标签，
不把工作流改为自托管 runner，也不关闭其他标签检查。

`actionlint.yaml` supplements older actionlint catalogs with the official
`ubuntu-26.04` label; it neither switches workflows to self-hosted execution nor
disables checks for other labels.
