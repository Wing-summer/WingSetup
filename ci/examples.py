# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

"""Plan example CI coverage and verify real packages without installing them."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
import platform
import subprocess
import tarfile
import tempfile
import zipfile
from dataclasses import dataclass, replace
from pathlib import Path

from wingsetup.config import load_config
from wingsetup.core import run_target
from wingsetup.model import AppImageOptions, Artifact, Config, SetupError, Target
from wingsetup.registry import BACKENDS
from wingsetup.platforms import normalize_arch
from wingsetup.backends.inno import InnoOptions
from wingsetup.backends.macos import MacOSOptions
from wingsetup.backends.makeself import MakeselfOptions
import yaml
from wingsetup.validation import fields, mapping, sequence, string

#: Repository root containing the examples and coverage manifest.
ROOT = Path(__file__).resolve().parents[1]
#: Committed cases serve as the common source for CI matrices and coverage checks.
MANIFEST = ROOT / "ci/examples.json"


@dataclass(frozen=True)
class ExampleCase:
    """One native packaging case and its expected execution environment."""

    #: Unique CI case identifier used in matrix and artifact names.
    id: str
    #: Repository-relative example configuration path.
    config: str
    #: Target selected from that configuration.
    target: str
    #: Provisioning group: linux, flatpak, native, or recipes.
    group: str
    #: GitHub runner label matching the target platform and architecture.
    runner: str
    #: Whether the host build requires an installed Qt SDK.
    qt: bool

    def matrix(self) -> dict[str, object]:
        """Return the runner and Qt fields consumed by the example workflow.

        Returns:
            JSON-compatible GitHub matrix entry for this case.
        """
        return {"id": self.id, "runner": self.runner, "qt": self.qt,
                "qt_host": "windows" if self.runner.startswith("windows") else "mac" if self.runner.startswith("macos") else "linux",
                "qt_arch": "win64_msvc2022_64" if self.runner.startswith("windows") else "clang_64" if self.runner.startswith("macos") else "linux_gcc_64"}


def load_cases() -> tuple[ExampleCase, ...]:
    """Validate coverage of every example target and built-in backend.

    Returns:
        Validated cases in manifest order.

    Raises:
        SetupError: Cases are malformed, duplicated, or leave a target uncovered.
    """
    raw: object = json.loads(MANIFEST.read_text(encoding="utf-8"))
    cases: list[ExampleCase] = []
    configured: set[tuple[str, str]] = set()
    environments: set[tuple[str, str, str]] = set()
    backends: set[str] = set()
    for value in sequence(raw, "examples"):
        item = mapping(value, "case")
        fields(item, "id config target group runner qt", "case")
        qt = item.get("qt")
        if not isinstance(qt, bool):
            raise SetupError("case.qt must be boolean")
        case = ExampleCase(string(item.get("id"), "id"), string(item.get("config"), "config"),
                           string(item.get("target"), "target"), string(
                               item.get("group"), "group"),
                           string(item.get("runner"), "runner"), qt)
        if case.group not in {"linux", "flatpak", "native", "recipes"}:
            raise SetupError(f"Unknown example group: {case.group}")
        if not (ROOT / case.config).resolve().is_relative_to(ROOT / "examples"):
            raise SetupError("CI configurations must live in examples")
        config = load_config(ROOT / case.config)
        target = next(
            (target for target in config.targets if target.name == case.target), None)
        if target is None:
            raise SetupError(f"Unknown example target: {case.id}")
        if any(previous.id == case.id for previous in cases) or (case.config, case.target, case.runner) in environments:
            raise SetupError(f"Duplicate example case: {case.id}")
        cases.append(case)
        configured.add((case.config, case.target))
        environments.add((case.config, case.target, case.runner))
        backends.add(target.backend)
    expected = {(path.relative_to(ROOT).as_posix(), target.name)
                for path in (ROOT / "examples").rglob("*.yml")
                if not set(path.relative_to(ROOT).parts) & {".wingsetup", "dist", "build"}
                and path.name in {"package.yml", "extended.yml"}
                for target in load_config(path).targets}
    if configured != expected or set(BACKENDS) - backends:
        raise SetupError(
            f"Incomplete example coverage: targets={expected - configured}, backends={set(BACKENDS) - backends}")
    for case in cases:
        if case.group in {"linux", "flatpak"}:
            runners = {entry.runner for entry in cases
                       if (entry.config, entry.target) == (case.config, case.target)}
            if runners != {"ubuntu-22.04", "ubuntu-26.04"}:
                raise SetupError(f"Incomplete example coverage: LTS endpoints for {case.id}: {runners}")
    return tuple(cases)


def expected_formats(case: ExampleCase) -> tuple[str, ...]:
    """Describe the concrete artifacts required from one example target.

    Args:
        case: Declared example configuration and target.

    Returns:
        Required output formats, distinguishing native archive variants.
    """
    config = load_config(ROOT / case.config)
    target = next(
        target for target in config.targets if target.name == case.target)
    if isinstance(target.options, InnoOptions):
        return target.options.formats
    if isinstance(target.options, MacOSOptions):
        return tuple("app.zip" if name == "app" else name for name in target.options.formats)
    return ({"appimage": ("appimage",), "flatpak": ("flatpak",), "deb": ("deb",),
             "makeself": ("makeself",), "aur": ("aur",), "script": ("script",)}
            .get(target.backend, ("tar.gz",)))


def output_labels(case: ExampleCase) -> str:
    """Render user-facing output filenames for coverage and execution tables.

    Args:
        case: Example target whose concrete archive extensions should be shown.

    Returns:
        Comma-separated output labels including Makeself's run or sh suffix.
    """
    config = load_config(ROOT / case.config)
    target = next(
        target for target in config.targets if target.name == case.target)
    if isinstance(target.options, MakeselfOptions):
        return "." + target.options.suffix
    labels = {"appimage": ".AppImage", "flatpak": ".flatpak", "deb": ".deb",
              "zip": ".zip", "app.zip": ".app.zip", "dmg": ".dmg",
              "inno": "Inno .exe", "aur": "PKGBUILD + .SRCINFO",
              "script": "Python/shell recipe", "tar.gz": ".tar.gz"}
    return ", ".join(labels.get(name, name) for name in expected_formats(case))


def validate_workflow(cases: tuple[ExampleCase, ...]) -> None:
    """Require visible workflow matrices to match the coverage contract exactly.

    Args:
        cases: Validated cases covering the example configurations and backends.

    Raises:
        SetupError: A matrix omits, duplicates, misroutes, or misconfigures a case.
    """
    # BaseLoader preserves the YAML 'on' key instead of treating it as a boolean.
    document: object = yaml.load(
        (ROOT / ".github/workflows/examples.yml").read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    jobs = mapping(mapping(document, "workflow").get("jobs"), "jobs")
    observed: set[str] = set()
    for group in ("linux", "flatpak", "native", "recipes"):
        job = mapping(jobs.get(group), group)
        strategy = mapping(job.get("strategy"), "strategy")
        matrix = mapping(strategy.get("matrix"), "matrix")
        for raw in sequence(matrix.get("include"), "matrix.include"):
            entry = mapping(raw, "entry")
            identity = string(entry.get("id"), "id")
            case = next((case for case in cases if case.id == identity), None)
            if case is None or case.group != group or identity in observed:
                raise SetupError(
                    f"Unexpected or duplicate workflow case: {identity}")
            runner = entry.get("runner", job.get("runs-on"))
            if runner != case.runner:
                raise SetupError(f"Workflow runner differs for {identity}")
            if group == "linux" and entry.get("qt") != str(case.qt).lower():
                raise SetupError(
                    f"Workflow Qt preparation differs for {identity}")
            if group == "native":
                for key in ("qt_host", "qt_arch"):
                    if entry.get(key) != case.matrix()[key]:
                        raise SetupError(
                            f"Workflow {key} differs for {identity}")
            observed.add(identity)
    if observed != {case.id for case in cases}:
        raise SetupError(
            f"Workflow omits cases: {sorted({case.id for case in cases} - observed)}")


def publish_summary(text: str) -> None:
    """Print a Markdown report and append it to the GitHub job summary.

    Args:
        text: Human-readable report with bilingual column labels.
    """
    print(text, flush=True)
    destination = os.environ.get("GITHUB_STEP_SUMMARY")
    if destination:
        with Path(destination).open("a", encoding="utf-8") as stream:
            stream.write(text + "\n")


def coverage_summary(cases: tuple[ExampleCase, ...]) -> str:
    """Render the planned case, runner, format, and verification coverage table.

    Args:
        cases: Complete validated example baseline.

    Returns:
        Markdown distinguishing planned checks from executed results.
    """
    lines = ["## Planned coverage / 计划覆盖", "",
             "Planned cases are not passed results. / 计划用例不代表已经通过。", "",
             "| Case / 用例 | Runner | Outputs / 产物 | Launch / 启动 |",
             "| --- | --- | --- | --- |"]
    for case in cases:
        formats = expected_formats(case)
        launch = "ZIP payload only / 仅 ZIP 载荷" if "inno" in formats else "Not executed / 不执行" if formats[0] in {
            "aur", "script"} else "Required / 必须通过"
        if requires_wayland(case):
            launch = "Offscreen + Wayland required / 两者均须通过"
        lines.append(
            f"| {case.id} | {case.runner} | {output_labels(case)} | {launch} |")
    lines += ["", f"Total / 总计: **{len(cases)} cases**; all include SHA-256 checks. / 全部检查 SHA-256。",
              "Installer execution, Developer ID/notarization, universal2 are outside this baseline. / 本基准不执行安装器，不覆盖 Developer ID/公证和 universal2。"]
    return "\n".join(lines)


def write_receipt(case: ExampleCase, result: dict[str, object]) -> None:
    """Write a small per-case execution receipt for final CI aggregation.

    Args:
        case: Case whose actual outcome is being recorded.
        result: Outcome and artifact verification evidence from this invocation.
    """
    directory = ROOT / ".ci-results"
    directory.mkdir(exist_ok=True)
    value = {**result, "case": case.id, "config": case.config, "target": case.target,
             "runner": case.runner,
             "host": platform.system(), "arch": platform.machine(),
             "run_id": os.environ.get("GITHUB_RUN_ID", "local"),
             "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT", "local"),
             "commit": os.environ.get("GITHUB_SHA", "local")}
    (directory / f"{case.id}.json").write_text(json.dumps(value,
                                                          indent=2) + "\n", encoding="utf-8")


def report_results(cases: tuple[ExampleCase, ...], directory: Path) -> bool:
    """Require current-run success receipts for every declared case and format.

    Args:
        cases: Required example baseline.
        directory: Directory of receipts downloaded from this workflow run.

    Returns:
        True only when every case and upstream job succeeded with complete evidence.
    """
    rows = ["## Execution results / 实际执行结果", "",
            "| Case / 用例 | Runner | Status / 状态 | Outputs / 产物 | Checksum / 校验 | Launch / 启动 |",
            "| --- | --- | --- | --- | --- | --- |"]
    passed = 0
    for case in cases:
        path = directory / f"{case.id}.json"
        formats = expected_formats(case)
        status, checksum, launch = "MISSING / 无执行记录", "—", "—"
        if path.is_file():
            try:
                result = mapping(json.loads(
                    path.read_text(encoding="utf-8")), "receipt")
                current = all(result.get(field) == os.environ.get(variable, "local") for field, variable in
                              (("run_id", "GITHUB_RUN_ID"), ("run_attempt", "GITHUB_RUN_ATTEMPT"), ("commit", "GITHUB_SHA")))
                evidence = [mapping(item, "artifact") for item in sequence(
                    result.get("artifacts", []), "artifacts")]
                actual = {string(item.get("format"), "format")
                          for item in evidence}
                integrity = bool(evidence) and all(
                    item.get("checksum") is True for item in evidence)
                required = [item for item in evidence if item.get(
                    "format") not in {"inno", "aur", "script"}]
                launched = all(item.get("launch") is True for item in required)
                if requires_wayland(case):
                    launched = launched and any(item.get("wayland") is True for item in evidence)
                complete = current and result.get("runner") == case.runner and result.get("case") == case.id and result.get(
                    "status") == "passed" and actual == set(formats) and integrity and launched
                if complete:
                    passed += 1
                    status = "PASS / 通过"
                    checksum = "PASS"
                    launch = "Offscreen + Wayland PASS" if requires_wayland(case) else "PASS" if required else "Not executed / 不执行"
                    if "inno" in formats:
                        launch = "ZIP PASS; installer not run / 安装器未执行"
                else:
                    status = "FAIL / 失败" if result.get(
                        "status") == "failed" else "INVALID / 证据不完整"
            except (OSError, ValueError, SetupError):
                status = "INVALID / 无效执行记录"
        rows.append(
            f"| {case.id} | {case.runner} | {status} | {output_labels(case)} | {checksum} | {launch} |")
    raw_jobs: object = json.loads(os.environ.get("EXAMPLE_JOB_RESULTS", "{}"))
    jobs = mapping(raw_jobs, "job results")
    successful_jobs = all(mapping(value, "job").get(
        "result") == "success" for value in jobs.values())
    rows += ["", f"**Passed / 已通过: {passed}/{len(cases)}**", "",
             "Missing, cancelled, or skipped cases cannot count as passed. / 缺失、取消或跳过均不计为通过。"]
    if not successful_jobs:
        rows.append(
            "At least one prerequisite job failed or did not run. / 至少一个前置 job 失败或未执行。")
    publish_summary("\n".join(rows))
    return passed == len(cases) and successful_jobs


def command(arguments: list[str], *, marker: str | None = None, platform: str = "offscreen",
            environment: dict[str, str] | None = None) -> str:
    """Execute a verification command with host Qt deployment overrides cleared.

    Args:
        arguments: Executable and explicit arguments; installers are never invoked.
        marker: Optional success text that must be present in captured output.
        platform: Qt platform selected for the launch, without host-plugin fallback.
        environment: Additional isolated compositor environment overrides.

    Returns:
        Combined process output from a successful verification.

    Raises:
        SetupError: The process fails or omits its expected success marker.
    """
    env = dict(os.environ)
    for name in ("LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH", "DYLD_FRAMEWORK_PATH", "QT_PLUGIN_PATH", "QT_QPA_PLATFORM_PLUGIN_PATH", "QML2_IMPORT_PATH"):
        env.pop(name, None)
    qt_root = env.get("QT_ROOT_DIR")
    if qt_root:
        env["PATH"] = os.pathsep.join(part for part in env.get("PATH", "").split(os.pathsep)
                                      if not Path(part).resolve().is_relative_to(Path(qt_root).resolve()))
    env["QT_QPA_PLATFORM"] = platform
    env.update(environment or {})
    if marker and marker.startswith("WIDGETS_DEPLOY_OK"):
        env["QT_DEBUG_PLUGINS"] = "1"
    try:
        result = subprocess.run(arguments, env=env, text=True, encoding="utf-8", errors="replace",
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=120, check=False)
    except subprocess.TimeoutExpired as exc:
        output = exc.stdout or ""
        diagnostic = output.decode(
            "utf-8", errors="replace") if isinstance(output, bytes) else output
        print(diagnostic, end="", flush=True)
        raise SetupError(
            f"Example verification timed out after {exc.timeout}s: {arguments}\n{diagnostic}") from exc
    print(result.stdout, end="", flush=True)
    if result.returncode or (marker and marker not in result.stdout):
        raise SetupError(
            f"Example verification failed: {arguments}: {result.returncode}")
    return result.stdout


def verify_wayland(arguments: list[str], root: Path, marker: str) -> None:
    """Launch the packaged application against a private headless Weston compositor.

    Args:
        arguments: Packaged executable and smoke-test arguments.
        root: Temporary verification directory holding the private runtime socket.
        marker: Application success marker required from the Wayland launch.

    Raises:
        SetupError: The compositor cannot start or the actual Wayland launch fails.
    """
    runtime = root / "wayland-runtime"
    runtime.mkdir(mode=0o700)
    log = root / "weston.log"
    environment = {"XDG_RUNTIME_DIR": str(runtime), "WAYLAND_DISPLAY": "wingsetup-wayland"}
    with log.open("w", encoding="utf-8") as stream:
        process = subprocess.Popen(["weston", "--backend=headless-backend.so", "--use-pixman", "--no-config",
                                    "--socket=wingsetup-wayland", "--idle-time=0"],
                                   env={**os.environ, **environment}, stdout=stream, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic() + 15
            while not (runtime / "wingsetup-wayland").exists():
                if process.poll() is not None or time.monotonic() >= deadline:
                    raise SetupError("Headless Weston failed to create its Wayland socket")
                time.sleep(0.1)
            command(arguments, marker=marker, platform="wayland", environment=environment)
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            stream.flush()
            print(log.read_text(encoding="utf-8"), flush=True)


def requires_wayland(case: ExampleCase) -> bool:
    """Determine whether the declared example requires a real Wayland launch.

    Args:
        case: Case whose AppImage Qt options determine the acceptance requirement.

    Returns:
        True when qt_platforms explicitly includes Wayland.
    """
    config = load_config(ROOT / case.config)
    target = next(target for target in config.targets if target.name == case.target)
    return isinstance(target.options, AppImageOptions) and "wayland" in target.options.qt_platforms


def verify_archive(artifact: Artifact, root: Path, marker: str, executable: str, *, wayland: bool = False) -> None:
    """Inspect and launch an archived example without invoking installation logic.

    Args:
        artifact: Completed package or recipe archive.
        root: Empty directory used for extraction or read-only DMG mounting.
        marker: Expected application launch success message.
        executable: Entry filename expected in portable native packages.
        wayland: Require an additional real Wayland launch for the AppImage.
    """
    if artifact.format == "appimage":
        command([str(artifact.path), "--appimage-extract-and-run",
                "--smoke"], marker=marker)
    elif artifact.format == "deb":
        command(["dpkg-deb", "--extract", str(artifact.path), str(root)])
        command(
            [str(next((root / "usr/lib").glob(f"*/bin/{executable}")))], marker=marker)
        command(["dpkg-deb", "--info", str(artifact.path)])
    elif artifact.format == "makeself":
        command([str(artifact.path), "--check"])
        command([str(artifact.path), "--noexec",
                "--target", str(root / "payload")])
        command([str(root / "payload/hello")], marker=marker)
    elif artifact.format in {"zip", "app.zip"}:
        if os.name == "nt":
            with zipfile.ZipFile(artifact.path) as archive:
                archive.extractall(root)
            # The runtime environment deliberately excludes the host Qt SDK.
            if not (root / "platforms/qoffscreen.dll").is_file():
                raise SetupError(
                    "Windows smoke payload is missing platforms/qoffscreen.dll")
            command([str(root / executable), "--smoke"], marker=marker)
        else:
            command(["ditto", "-x", "-k", str(artifact.path), str(root)])
            bundle = next(root.glob("*.app"))
            command(["codesign", "--verify", "--deep", "--strict", str(bundle)])
            command([str(bundle / "Contents/MacOS" / executable),
                    "--smoke"], marker=marker)
    elif artifact.format == "dmg":
        mount = root / "mounted"
        command(["hdiutil", "attach", "-readonly", "-nobrowse",
                "-mountpoint", str(mount), str(artifact.path)])
        try:
            bundle = next(mount.glob("*.app"))
            command(["codesign", "--verify", "--deep", "--strict", str(bundle)])
            command([str(bundle / "Contents/MacOS" / executable),
                    "--smoke"], marker=marker)
        finally:
            command(["hdiutil", "detach", str(mount)])
    elif artifact.format in {"aur", "script", "tar.gz"}:
        with tarfile.open(artifact.path) as archive:
            archive.extractall(root, filter="data")
        if artifact.format == "aur":
            if not (root / ".SRCINFO").is_file() or not (root / "PKGBUILD").is_file():
                raise SetupError("AUR output lacks PKGBUILD or .SRCINFO")
            command(["bash", "-n", str(root / "PKGBUILD")])
        elif artifact.format == "script":
            if not (root / "installer.py").is_file():
                raise SetupError("Script recipe entry was not exported")
        else:
            command([str(root / executable)], marker=marker)


def run_case(case: ExampleCase) -> None:
    """Package a declared example, verify outputs, and record validation evidence.

    Args:
        case: Coverage-manifest entry matching the current native runner.

    Raises:
        SetupError: Output integrity, expected formats, metadata, or launch checks fail.
    """
    config: Config = load_config(ROOT / case.config)
    target: Target = next(
        target for target in config.targets if target.name == case.target)
    if target.platform != "any" and target.platform != platform.system():
        raise SetupError(f"Example {case.id} requires native {target.platform}")
    if target.arch not in {"any", "universal2"} and target.arch != normalize_arch(platform.machine()):
        raise SetupError(f"Example {case.id} requires native {target.arch}")
    if isinstance(target.options, AppImageOptions):
        target = replace(target, options=replace(
            target.options, runtime_file=ROOT / ".tools/ci/runtime-x86_64"))
    outputs = run_target(config, target)
    expected = {"inno": {"zip", "inno"}, "macos": {
        "app.zip", "zip", "dmg"}}.get(target.backend)
    if expected and {output.format for output in outputs} != expected:
        raise SetupError(f"Expected all native output formats: {expected}")
    marker = "WIDGETS_DEPLOY_OK: translation, resources, .wingplg, private library" if case.qt or case.id.startswith(
        "qt-") else "Hello from WingSetup"
    entry = "widgets-demo.exe" if target.platform == "Windows" else "widgets-demo" if case.id.startswith(
        "qt-") else "hello"
    checks: list[dict[str, object]] = []
    for output in outputs:
        with output.path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        sidecar = output.path.with_name(
            output.path.name + ".sha256").read_text(encoding="utf-8").strip()
        if digest != output.sha256 or sidecar != f"{digest}  {output.path.name}":
            raise SetupError("Artifact SHA-256 or checksum sidecar differs")
        with tempfile.TemporaryDirectory(prefix="wingsetup-verify-") as directory:
            verify_archive(output, Path(directory), marker, entry, wayland=requires_wayland(case))
        checks.append({"path": str(output.path), "format": output.format, "sha256": digest,
                       "checksum": True, "wayland": requires_wayland(case), "launch": output.format not in {"inno", "aur", "script", "flatpak"}})
    if target.backend == "flatpak":
        work = max(config.workspace.glob(
            f"{target.name}-*"), key=lambda path: path.stat().st_mtime_ns)
        metadata = (work / "root/metadata").read_text(encoding="utf-8")
        if config.application.id not in metadata:
            raise SetupError(
                "Flatpak metadata has the wrong application identity")
        command(["flatpak", "build", "--env=QT_QPA_PLATFORM=offscreen",
                str(work / "root"), f"/app/bin/{entry}", "--smoke"], marker=marker)
        checks[0]["launch"] = True
    destination = config.output / target.name / "validation.json"
    result: dict[str, object] = {"case": case.id,
                                 "status": "passed", "artifacts": checks}
    destination.write_text(json.dumps(
        result, indent=2) + "\n", encoding="utf-8")
    write_receipt(case, result)


def main() -> None:
    """Emit GitHub matrices or package and verify selected example cases."""
    parser = argparse.ArgumentParser(description=__doc__)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--matrix", action="store_true")
    selection.add_argument("--coverage", action="store_true")
    selection.add_argument("--report", type=Path)
    selection.add_argument("--case")
    selection.add_argument(
        "--group", choices=("linux", "flatpak", "native", "recipes"))
    arguments = parser.parse_args()
    cases = load_cases()
    if arguments.report is not None:
        if not report_results(cases, arguments.report):
            raise SystemExit(1)
        return
    if arguments.coverage:
        validate_workflow(cases)
        publish_summary(coverage_summary(cases))
        return
    if arguments.matrix:
        destination = os.environ.get("GITHUB_OUTPUT")
        for group in ("linux", "flatpak", "native"):
            value = json.dumps(
                {"include": [case.matrix() for case in cases if case.group == group]})
            print(f"{group}={value}")
            if destination:
                with Path(destination).open("a", encoding="utf-8") as stream:
                    stream.write(f"{group}={value}\n")
        return
    selected = [case for case in cases if case.id ==
                arguments.case or case.group == arguments.group]
    if not selected:
        raise SetupError("No example case matched")
    for case in selected:
        try:
            run_case(case)
        except Exception as exc:
            write_receipt(case, {"status": "failed",
                          "error": str(exc), "artifacts": []})
            raise


if __name__ == "__main__":
    main()
