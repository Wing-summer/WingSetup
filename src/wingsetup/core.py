# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

"""Execute isolated packaging pipelines and expose project extension APIs."""

from __future__ import annotations

import hashlib
import json
import importlib.util
import os
import shutil
import shlex
import subprocess
import tempfile
import sys
import traceback
from abc import ABC, abstractmethod
from threading import Event, Thread
from time import monotonic
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence, TypeVar, cast

from .model import Artifact, Config, FlatpakOptions, SetupError, Target
from .console import get_console, plain_text
from .platforms import DeploymentLayout, deployment_layout
from .script_paths import activate_paths


class CommandRunner:
    """Execute argument lists without an implicit shell and retain diagnostics."""

    def __init__(self, log: Path | None = None) -> None:
        """Configure an optional append-only command log.

        Args:
            log: Optional file receiving command arguments and combined process output.
        """
        #: Optional destination for append-only command diagnostics.
        self.log = log

    def run(self, args: Sequence[str], *, cwd: Path,
            env: Mapping[str, str] | None = None) -> str:
        """Execute the requested command and capture its output.

        Execute an argument list, stream combined output, and reject command failures.

        Args:
            args: Command arguments passed directly to the executable without an
                implicit shell.
            cwd: Existing directory in which to execute the command.
            env: Environment overrides merged with the host environment.

        Returns:
            Combined standard output and standard error captured from the process.

        Raises:
            SetupError: The command is empty, cannot be started, or exits with a nonzero
                status.
        """
        if not args:
            raise SetupError("Cannot run an empty command")
        log_stream = self.log.open("a", encoding="utf-8") if self.log is not None else None
        output: list[str] = []
        console = get_console()
        started = monotonic()
        display = subprocess.list2cmdline(args) if os.name == "nt" else shlex.join(args)
        console.write(f"    COMMAND {display}")
        console.write(f"    Directory: {cwd}", "detail")
        try:
            if log_stream:
                log_stream.write(f"$ {list(args)!r}\n")
                log_stream.flush()
            with subprocess.Popen(args, cwd=cwd, env={**os.environ, **(env or {})},
                                  text=True, encoding="utf-8", errors="replace",
                                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT) as process:
                stop = Event()
                heartbeat = Thread(target=console.heartbeat, args=(stop, args[0], started), daemon=True)
                heartbeat.start()
                try:
                    assert process.stdout is not None
                    for line in process.stdout:
                        output.append(line)
                        console.child(line)
                        if log_stream:
                            log_stream.write(plain_text(line))
                            log_stream.flush()
                    code = process.wait()
                finally:
                    stop.set()
                    heartbeat.join()
        except OSError as exc:
            console.write(f"    FAILED {args[0]} ({console.elapsed(started)}): {exc}", "error")
            raise SetupError(f"Cannot run {args[0]}: {exc}") from exc
        finally:
            if log_stream:
                log_stream.close()
        text = "".join(output)
        if code:
            console.write(f"    FAILED {args[0]} exit={code} ({console.elapsed(started)})", "error")
            raise SetupError(f"Command failed ({code}): {list(args)!r}\n{text}")
        console.write(f"    DONE {args[0]} ({console.elapsed(started)})", "success")
        return text



@dataclass(frozen=True)
class BuildContext:
    """Expose target-local paths and safe copy helpers to trusted host hooks."""

    #: Validated configuration shared with this invocation.
    config: Config
    #: Selected target and backend settings.
    target: Target
    #: Unique working directory retained after success or failure.
    work: Path
    #: Target-local directory for generated build outputs.
    build_dir: Path
    #: Root of the staged installation tree.
    deploy_dir: Path
    #: Command executor responsible for streaming output and recording diagnostics.
    runner: CommandRunner

    @property
    def source_dir(self) -> Path:
        """Return the configured project source directory.

        Returns:
            Configured project source directory.
        """
        return self.config.project.source

    @property
    def layout(self) -> DeploymentLayout:
        """Return logical deployment paths for the selected target.

        Returns:
            Deployment paths for the selected backend layout.
        """
        kind = self.target.layout or {"appimage": "linux", "flatpak": "flatpak"}.get(self.target.backend, "portable")
        return deployment_layout(self.deploy_dir, kind, self.config.application.name)

    @property
    def prefix_dir(self) -> Path:
        """Return the target installation prefix within the deployment tree.

        Returns:
            Target installation prefix within the deployment tree.
        """
        return self.layout.prefix

    @property
    def app_dir(self) -> Path:
        """Return the directory for the executable and its adjacent resources.

        Returns:
            Executable directory within the deployment tree.
        """
        return self.layout.app

    @property
    def executable(self) -> Path:
        """Resolve the target override or default executable against this run.

        Returns:
            Absolute path to the selected build output.
        """
        return self.resolve_path(self.target.executable or self.config.application.executable)

    @property
    def executable_name(self) -> str:
        """Return the entry filename, removing the .app suffix for macOS bundles.

        Returns:
            Executable filename or the stem of a .app bundle path.
        """
        path = self.target.executable or self.config.application.executable
        return path.stem if path.suffix == ".app" else path.name

    def resolve_path(self, path: Path) -> Path:
        """Expand source, build, and work placeholders into an absolute path.

        Args:
            path: File or directory path to inspect or process.

        Returns:
            Absolute path after expanding this run's source, build, and work
            directories.
        """
        value = str(path)
        for key, replacement in (("{build}", self.build_dir), ("{source}", self.source_dir),
                                 ("{work}", self.work)):
            value = value.replace(key, str(replacement))
        return Path(value).resolve()

    def copy_app(self, source: Path, destination: str) -> None:
        """Copy content relative to the application executable directory.

        Args:
            source: Source file or directory; supported run-time placeholders are
                expanded.
            destination: Relative copy destination inside the selected deployment
                location.

        Raises:
            SetupError: The application-relative destination is unsafe or copying fails
                validation.
        """
        if Path(destination).is_absolute() or ".." in Path(destination).parts:
            raise SetupError("Application resource destination must be relative")
        self.copy(source, str(self.app_dir.relative_to(self.deploy_dir) / destination))

    def run(self, args: Sequence[str], *, cwd: Path | None = None,
            env: Mapping[str, str] | None = None) -> str:
        """Expand deployment placeholders and execute a command through the runner.

        Args:
            args: Command arguments passed directly to the executable without an
                implicit shell.
            cwd: Command working directory; None selects the project source directory.
            env: Environment overrides merged with the host environment.

        Returns:
            Combined output returned by the configured command runner.
        """
        replacements = {"{source}": str(self.source_dir), "{build}": str(self.build_dir),
                        "{deploy}": str(self.deploy_dir), "{work}": str(self.work),
                        "{prefix}": str(self.prefix_dir), "{app}": str(self.app_dir),
                        "{resources}": str(self.layout.resources), "{libraries}": str(self.layout.libraries),
                        "{plugins}": str(self.layout.plugins)}
        expanded: list[str] = []
        for arg in args:
            for key, value in replacements.items():
                arg = arg.replace(key, value)
            expanded.append(arg)
        return self.runner.run(expanded, cwd=cwd or self.source_dir, env=env)

    def copy(self, source: Path, destination: str) -> None:
        """Copy content into the deployment tree.

        Copy content into the deployment tree while rejecting escaping destinations.

        Args:
            source: Source file or directory; supported run-time placeholders are
                expanded.
            destination: Relative copy destination inside the selected deployment
                location.

        Raises:
            SetupError: The source is missing or the destination escapes the tree or
                contains unsafe links.
        """
        source = self.resolve_path(source)
        root = self.deploy_dir.resolve()
        dest = root / destination
        if Path(destination).is_absolute() or not dest.resolve().is_relative_to(root):
            raise SetupError(f"Copy escapes deployment directory: {destination}")
        if not source.exists():
            raise SetupError(f"Missing resource: {source}")
        console = get_console()
        console.write(f"    COPY {source} -> {dest}", "detail")
        started = monotonic()
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.is_dir() and any(p.is_symlink() for p in dest.rglob("*")):
            raise SetupError(f"Copy destination contains symlinks: {dest}")
        if source.is_dir():
            # Dereference source symlinks, so deployment cannot retain external links.
            shutil.copytree(source, dest, dirs_exist_ok=True)
        else:
            shutil.copy2(source, dest)
        console.write(f"    COPIED {destination} ({console.elapsed(started)})", "detail")


class ProjectHooks:
    """Optional host callbacks; SDK builds deliberately skip the build callback."""

    def pre_prepare(self, ctx: BuildContext) -> None:
        """Run the optional callback before preparation.

        Run an optional callback before the prepare stage; directories are not initialized yet.

        Args:
            ctx: Target-local configuration, paths, and command execution services.
        """
        pass

    def after_prepare(self, ctx: BuildContext) -> None:
        """Run an optional callback after successful completion of the prepare stage.

        Args:
            ctx: Target-local configuration, paths, and command execution services.
        """
        pass

    def pre_build(self, ctx: BuildContext) -> None:
        """Run an optional callback before the build stage.

        Args:
            ctx: Target-local configuration, paths, and command execution services.
        """
        pass

    def after_build(self, ctx: BuildContext) -> None:
        """Run an optional callback after successful completion of the build stage.

        Args:
            ctx: Target-local configuration, paths, and command execution services.
        """
        pass

    def pre_deploy(self, ctx: BuildContext) -> None:
        """Run an optional callback before the deploy stage.

        Args:
            ctx: Target-local configuration, paths, and command execution services.
        """
        pass

    def after_deploy(self, ctx: BuildContext) -> None:
        """Run an optional callback after successful completion of the deploy stage.

        Args:
            ctx: Target-local configuration, paths, and command execution services.
        """
        pass

    def pre_package(self, ctx: BuildContext) -> None:
        """Run an optional callback before the package stage.

        Args:
            ctx: Target-local configuration, paths, and command execution services.
        """
        pass

    def after_package(self, ctx: BuildContext) -> None:
        """Run an optional callback after successful completion of the package stage.

        Args:
            ctx: Target-local configuration, paths, and command execution services.
        """
        pass

    def build(self, ctx: BuildContext) -> None:
        """Perform the backend or project build extension.

        Provide an optional host project build extension; the default implementation does nothing.

        Args:
            ctx: Target-local configuration, paths, and command execution services.
        """
        pass

    def deploy(self, ctx: BuildContext) -> None:
        """Stage the application or recipe contents.

        Provide an optional host project deploy extension; the default implementation does nothing.

        Args:
            ctx: Target-local configuration, paths, and command execution services.
        """
        pass


class PackageBackend(ABC):
    """Format adapter; the pipeline owns hook order and failure propagation."""

    @abstractmethod
    def check(self, ctx: BuildContext) -> tuple[str, ...]:
        """Report unmet backend requirements without running project hooks.

        Args:
            ctx: Target-local configuration, paths, and command execution services.

        Returns:
            Unmet requirements as messages; an empty tuple means all checked
            requirements are satisfied.
        """
        ...

    def prepare(self, ctx: BuildContext) -> None:
        """Check declared requirements and create the target build directory.

        Args:
            ctx: Target-local configuration, paths, and command execution services.

        Raises:
            SetupError: A backend requirement or declared build tool is unavailable.
        """
        missing = check_requirements(self, ctx)
        if missing:
            raise SetupError("Missing requirements:\n" + "\n".join(missing))
        ctx.build_dir.mkdir(parents=True, exist_ok=True)

    def build(self, ctx: BuildContext, hooks: ProjectHooks) -> None:
        """Execute configured host commands and invoke the project build callback.

        Args:
            ctx: Target-local configuration, paths, and command execution services.
            hooks: Trusted host project callbacks invoked at the backend-defined
                extension points.
        """
        for command in ctx.config.project.commands:
            ctx.run(command)
        hooks.build(ctx)

    @abstractmethod
    def deploy(self, ctx: BuildContext, hooks: ProjectHooks) -> None:
        """Stage the installation tree and invoke project deployment extensions.

        Args:
            ctx: Target-local configuration, paths, and command execution services.
            hooks: Trusted host project callbacks invoked at the backend-defined
                extension points.
        """
        ...

    @abstractmethod
    def package(self, ctx: BuildContext) -> tuple[Artifact, ...]:
        """Create final outputs and return their artifact records.

        Args:
            ctx: Target-local configuration, paths, and command execution services.

        Returns:
            Completed output artifacts in the requested generation order.
        """
        ...


def deploy_resources(ctx: BuildContext) -> None:
    """Copy common and target-specific resources.

    Apply common and target-specific resource rules to logical deployment locations.

    Args:
        ctx: Target-local configuration, paths, and command execution services.
    """
    for rule in (*ctx.config.project.resources, *ctx.target.resources):
        base = {"root": ctx.deploy_dir, "prefix": ctx.prefix_dir, "app": ctx.app_dir,
                "resources": ctx.layout.resources, "libraries": ctx.layout.libraries,
                "plugins": ctx.layout.plugins}[rule.relative_to]
        destination = str(base.relative_to(ctx.deploy_dir) / rule.destination)
        ctx.copy(rule.source, destination)


def artifact(ctx: BuildContext, path: Path, format_name: str) -> Artifact:
    """Validate a nonempty output, calculate SHA-256, and write its checksum sidecar.

    Args:
        ctx: Target-local configuration, paths, and command execution services.
        path: File or directory path to inspect or process.
        format_name: Concrete output format recorded in the artifact metadata.

    Returns:
        Artifact metadata containing the output path, format, architecture, and digest.

    Raises:
        SetupError: The expected output is missing or empty.
    """
    if not path.is_file() or path.stat().st_size == 0:
        raise SetupError(f"Packager did not produce a nonempty file: {path}")
    console = get_console()
    console.write(f"    SHA256 calculating: {path} ({path.stat().st_size:,} bytes)", "detail")
    started = monotonic()
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    path.with_name(path.name + ".sha256").write_text(f"{digest}  {path.name}\n")
    console.write(f"    SHA256 recorded ({console.elapsed(started)})", "detail")
    return Artifact(path, format_name, ctx.target.arch, digest)


#: Extension base type preserved when loading a trusted subclass.
T = TypeVar("T")


def load_extension(spec: str, base: Path, expected: type[T]) -> T:
    """Load a trusted local extension subclass.

    Import and instantiate a trusted local subclass of the required extension type.

    Args:
        spec: Trusted local extension specification in file.py:ClassName form.
        base: Directory relative to which configuration or extension paths are resolved.
        expected: Required base class for the loaded extension.

    Returns:
        New instance of the validated extension subclass.

    Raises:
        SetupError: The specification is malformed or does not identify a subclass of
            the required base.
    """
    filename, separator, name = spec.rpartition(":")
    if not separator:
        raise SetupError(f"Expected file.py:ClassName: {spec}")
    path = (base / filename).resolve()
    module_spec = importlib.util.spec_from_file_location(f"_wingsetup_{path.stem}", path)
    if module_spec is None or module_spec.loader is None:
        raise SetupError(f"Cannot load extension: {path}")
    module = importlib.util.module_from_spec(module_spec)
    sys.modules[module_spec.name] = module
    module_spec.loader.exec_module(module)
    candidate: object = getattr(module, name, None)
    if not isinstance(candidate, type):
        raise SetupError(f"{spec} must inherit {expected.__name__}")
    extension_class = cast(type[object], candidate)
    if not issubclass(extension_class, expected):
        raise SetupError(f"{spec} must inherit {expected.__name__}")
    return extension_class()


def backend_for(target: Target, base: Path) -> PackageBackend:
    """Instantiate a registered backend or load a trusted custom backend extension.

    Args:
        target: Selected target definition to instantiate or execute.
        base: Directory relative to which configuration or extension paths are resolved.

    Returns:
        New backend instance for the selected target.
    """
    from .registry import registration
    spec = registration(target.backend)
    return spec.factory() if spec else load_extension(target.backend, base, PackageBackend)


def run_target(config: Config, target: Target,
               runner: CommandRunner | None = None) -> tuple[Artifact, ...]:
    """Run an isolated four-stage packaging pipeline.

    Execute all four stages in isolation and retain diagnostics when a stage fails.

    Args:
        config: Validated application and project configuration.
        target: Selected target definition to instantiate or execute.
        runner: Optional command executor override; None creates a run-local logging
            executor.

    Returns:
        Artifact records for the completed target, in backend output order.

    Raises:
        SetupError: A lifecycle hook or backend stage fails; the retained working
            directory is reported.
    """
    config.workspace.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix=f"{target.name}-", dir=config.workspace))
    deploy = work / ("AppDir" if target.backend == "appimage" else "root")
    ctx = BuildContext(config, target, work, work / "build", deploy,
                       runner or CommandRunner(work / "commands.log"))
    console = get_console()
    target_started = monotonic()
    console.write(f"TARGET {target.name} | {target.backend} | {target.platform}/{target.arch}")
    console.write(f"Workspace: {work}", "detail")
    with activate_paths(ctx):
        console.write("Loading backend and project hooks", "detail")
        try:
            backend = backend_for(target, config.path.parent)
            hooks = (ProjectHooks() if config.project.hooks is None else
                     load_extension(config.project.hooks, config.path.parent, ProjectHooks))
        except Exception as exc:
            console.write(f"TARGET {target.name}: FAILED loading extensions", "error")
            (work / "failure.log").write_text(traceback.format_exc(), encoding="utf-8")
            raise SetupError(f"Cannot load target extensions; work directory: {work}: {exc}") from exc
        result: tuple[Artifact, ...] = ()
        for index, stage in enumerate(("prepare", "build", "deploy", "package"), start=1):
            started = monotonic()
            console.progress(index - 1, 4, f"{target.name}: START {stage} [{index}/4]")
            action = f"pre_{stage}"
            try:
                console.write(f"    HOOK {action}", "detail")
                getattr(hooks, action)(ctx)
                action = f"backend.{stage}"
                console.write(f"    STEP {action}", "detail")
                if stage == "prepare":
                    backend.prepare(ctx)
                elif stage == "build":
                    backend.build(ctx, hooks)
                elif stage == "deploy":
                    backend.deploy(ctx, hooks)
                else:
                    (config.output / target.name).mkdir(parents=True, exist_ok=True)
                    result = backend.package(ctx)
                action = f"after_{stage}"
                console.write(f"    HOOK {action}", "detail")
                getattr(hooks, action)(ctx)
                console.progress(index, 4, f"{target.name}: DONE {stage} ({console.elapsed(started)})", "success")
            except Exception as exc:
                console.progress(index - 1, 4, f"{target.name}: FAILED {stage} at {action} ({console.elapsed(started)})", "error")
                console.write(f"Stopped; remaining stages will not run. Diagnostics: {work}", "warning")
                (work / "failure.log").write_text(traceback.format_exc())
                raise SetupError(f"{target.name}/{stage} failed; work directory: {work}: {exc}") from exc
        report = [{"path": str(item.path), "format": item.format, "arch": item.arch,
                   "sha256": item.sha256, "kind": item.kind} for item in result]
        (work / "artifacts.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        console.write(f"TARGET {target.name}: DONE ({console.elapsed(target_started)}), {len(result)} artifact(s)", "success")
        for item in result:
            console.write(f"    OUTPUT {item.path}", "success")
            console.write(f"    SHA256 {item.sha256}", "detail")
        return result


def tool_missing(name: str) -> tuple[str, ...]:
    """Report an executable requirement when it cannot be resolved on PATH.

    Args:
        name: Name of the tool, backend, field, or environment variable being processed.

    Returns:
        Unmet requirements as messages; an empty tuple means all checked requirements
        are satisfied.
    """
    return () if shutil.which(name) else (f"Executable: {name}",)


def check_requirements(backend: PackageBackend, ctx: BuildContext) -> tuple[str, ...]:
    """Check backend and applicable declared tool requirements.

    Combine backend and declared tool checks, skipping irrelevant host build tools.

    Args:
        backend: Backend instance whose requirements are combined with declared tool
            checks.
        ctx: Target-local configuration, paths, and command execution services.

    Returns:
        Unmet requirements as messages; an empty tuple means all checked requirements
        are satisfied.
    """
    from .registry import registration
    spec = registration(ctx.target.backend)
    sdk_build = isinstance(ctx.target.options, FlatpakOptions) and ctx.target.options.mode == "sdk"
    recipe = spec is not None and spec.kind == "recipe"
    tools = ctx.target.tools + (() if sdk_build or recipe else ctx.config.project.tools)
    errors = list(backend.check(ctx))
    for tool in tools:
        errors.extend(tool_missing(tool))
    return tuple(dict.fromkeys(errors))
