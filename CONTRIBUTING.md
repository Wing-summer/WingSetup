# Contributing / 贡献指南

Use Python 3.11+ and install development dependencies in a virtual environment.
使用 Python 3.11+，开发依赖必须安装在虚拟环境中。

```sh
uv venv .venv --python python3
uv pip install --python .venv/bin/python -e '.[dev]'
.venv/bin/pyright
.venv/bin/python -m pytest -q
git diff --check
```

Keep each backend in its own module under `src/wingsetup/backends/`; put shared
Linux deployment helpers in `common.py`. Keep format-specific commands out of
the pipeline core. New options need typed models, validation, documentation and
relevant tests. Contributions are licensed under BSD-3-Clause.

每个后端独立存放于 `src/wingsetup/backends/`，共享 Linux 部署逻辑放入
`common.py`。流水线核心不包含格式专属命令。新增配置须同步类型模型、校验、
文档和相关测试。贡献代码采用 BSD-3-Clause 协议。

External application integration belongs in that application's packaging
folder. Examples here should remain generic and must not contain local checkout
paths. Do not commit downloaded tools, virtual environments or build artifacts.

具体应用的适配放在该应用的打包目录。本仓库示例保持通用，不包含本地仓库路径。
不要提交下载工具、虚拟环境和构建产物。

Describe the problem, behavior change and validation in pull requests. Distinguish
unit tests, real package creation and launch tests; report missing dependencies.

提交说明应包含问题、行为变化及验证结果，区分单元测试、真实打包和启动测试，
如实说明缺失依赖。

Keep examples in `examples/basic` and `examples/qtwidgets`. Add an English
BSD-3-Clause SPDX notice at the top of source and comment-capable configuration
files. Keep code comments in English and prose documentation bilingual in Chinese
and English. LICENSE stays in its standard English form; JSON and marker files
must not receive invalid comment syntax.

示例分别放在 `examples/basic` 和 `examples/qtwidgets`。源码及支持注释的配置文件
顶部添加英文 BSD-3-Clause SPDX 声明。代码注释使用英文，说明文档采用中英双语。
LICENSE 保留标准英文原文；JSON 和标记文件不得插入不合法的注释。

Register built-in backend capabilities and option parsers in registry.py. Use
DeploymentLayout for destination paths and declare host/target tools in YAML.
Recipes must skip host compilation; Flatpak SDK builds remain manifest-owned.

内置后端的能力与选项解析器在 registry.py 注册。部署路径使用 DeploymentLayout，
宿主和目标所需工具在 YAML 声明。配方跳过宿主编译，Flatpak SDK 编译由 manifest 负责。

Follow [AGENTS.md](AGENTS.md) for repository-wide maintenance rules. Keep the
framework version and release-oriented changelog consistent. Update ci/examples.json
whenever an example target or built-in backend is added.

仓库维护规则见 [AGENTS.md](AGENTS.md)。保持框架版本与面向版本的变更日志一致。
增加示例目标或内置后端时同步更新 ci/examples.json。
