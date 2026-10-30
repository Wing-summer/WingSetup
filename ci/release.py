# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

"""Plan trusted project release jobs and collect verified, uniquely named assets."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import yaml

from wingsetup.config import load_config
from wingsetup.core import run_target
from wingsetup.model import SetupError
from wingsetup.validation import fields, mapping, sequence, string, strings


@dataclass(frozen=True)
class ReleaseJob:
    """A project-owned build entry executed on its explicitly selected runner."""

    #: Stable identifier used for selection and uploaded artifact names.
    id: str
    #: GitHub runner label or self-hosted label array.
    runner: tuple[str, ...]
    #: Repository-relative WingSetup package configuration.
    config: str
    #: Ordered package target names within that configuration.
    targets: tuple[str, ...]
    #: Explicit argument lists for tool and dependency preparation.
    prepare: tuple[tuple[str, ...], ...]
    #: Additional argument lists executed only in Qt mode.
    qt_prepare: tuple[tuple[str, ...], ...]
    #: Native host execution or a FreeBSD virtual machine.
    system: str
    #: Optional version for the workflow's reusable Qt setup action.
    qt_version: str
    #: Qt installer architecture, empty for the action's native default.
    qt_arch: str
    #: Space-separated optional Qt modules.
    qt_modules: str


def relative(value: object, where: str) -> str:
    """Validate a repository-relative path without traversal or output injection.

    Args:
        value: Untrusted YAML path.
        where: Configuration field used in errors.

    Returns:
        Validated relative POSIX pathname.
    """
    text = string(value, where)
    if '\\' in text or ':' in text or Path(text).is_absolute() or '..' in Path(text).parts or any(ord(char) < 32 for char in text):
        raise SetupError(f'{where}: require a repository-relative path')
    return text


def commands(value: object) -> tuple[tuple[str, ...], ...]:
    """Validate preparation commands as nonempty argument lists without a shell.

    Args:
        value: Sequence of command argument arrays.

    Returns:
        Immutable command arrays.
    """
    result = tuple(strings(item, 'prepare command') for item in sequence(value, 'prepare'))
    if any(not item or any('\x00' in arg for arg in item) for item in result):
        raise SetupError('Preparation commands must be nonempty argument lists')
    return result


def load_jobs(path: Path, selection: str = 'all') -> tuple[ReleaseJob, ...]:
    """Validate a release build file and select jobs in declaration order.

    Args:
        path: Project-owned YAML build matrix.
        selection: All jobs or comma-separated stable job identifiers.

    Returns:
        Nonempty validated release jobs.
    """
    data = mapping(cast(object, yaml.safe_load(path.read_text(encoding='utf-8'))), 'release')
    fields(data, 'schema_version builds', 'release')
    if type(data.get('schema_version')) is not int or data['schema_version'] != 1:
        raise SetupError('release.schema_version must be 1')
    result: list[ReleaseJob] = []
    for identity, raw in mapping(data.get('builds'), 'builds').items():
        if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}', identity):
            raise SetupError(f'Invalid build ID: {identity}')
        item = mapping(raw, identity)
        fields(item, 'runner config targets prepare qt_prepare qt_version qt_arch qt_modules system', identity)
        runner = item.get('runner')
        labels = (string(runner, 'runner'),) if isinstance(runner, str) else strings(runner, 'runner')
        targets = strings(item.get('targets'), 'targets')
        if not labels or not targets or len(set(targets)) != len(targets):
            raise SetupError(f'{identity}: require runner and unique targets')
        system = string(item.get('system', 'native'), 'system')
        if system not in {'native', 'freebsd', 'riscv64'}:
            raise SetupError('system must be native, freebsd, or riscv64')
        optional = {key: string(item[key], key) if key in item else '' for key in ('qt_version', 'qt_arch', 'qt_modules')}
        result.append(ReleaseJob(identity, labels, relative(item.get('config'), 'config'), targets,
                                 commands(item.get('prepare', [])), commands(item.get('qt_prepare', [])), system,
                                 optional['qt_version'], optional['qt_arch'], optional['qt_modules']))
    selected = {item.id for item in result} if selection == 'all' else set(selection.split(','))
    if not selected or selected - {item.id for item in result}:
        raise SetupError('Unknown or empty build selection')
    jobs = tuple(item for item in result if item.id in selected)
    if not jobs or len(jobs) > 256:
        raise SetupError('Release requires between 1 and 256 jobs')
    return jobs


def output(name: str, value: str) -> None:
    """Write an Actions multiline output without interpreting user text.

    Args:
        name: Framework-owned output identifier.
        value: Output payload.
    """
    destination = os.environ.get('GITHUB_OUTPUT')
    if destination:
        delimiter = 'wing_' + uuid.uuid4().hex
        with Path(destination).open('a', encoding='utf-8') as stream:
            stream.write(f'{name}<<{delimiter}\n{value}\n{delimiter}\n')


def write_index(directory: Path, assets: list[dict[str, str]]) -> None:
    """Write a deterministic release manifest and standard checksum file.

    Args:
        directory: Directory containing verified release files.
        assets: Flat, uniquely named asset metadata.
    """
    assets.sort(key=lambda item: item['name'])
    (directory / 'release.json').write_text(json.dumps({'schema_version': 1, 'assets': assets}, indent=2) + '\n', encoding='utf-8')
    (directory / 'SHA256SUMS.txt').write_text(''.join(f"{item['sha256']}  {item['name']}\n" for item in assets), encoding='utf-8')


def collect(inputs: Path, destination: Path, expected: tuple[str, ...]) -> list[dict[str, str]]:
    """Verify every job receipt and asset before assembling a flat release directory.

    Args:
        inputs: Downloaded job artifact directories.
        destination: New output directory; existing directories are rejected.
        expected: Exact planned job IDs; missing and unexpected receipts fail closed.

    Returns:
        Verified asset metadata suitable for a release API.
    """
    receipts = sorted(inputs.rglob('release.json'))
    if not expected or len(set(expected)) != len(expected):
        raise SetupError('Require a nonempty unique expected build list')
    found: set[str] = set()
    assets: list[dict[str, str]] = []
    names: set[str] = set()
    sources: list[Path] = []
    for receipt in receipts:
        if receipt.is_symlink() or not receipt.resolve().is_relative_to(inputs.resolve()):
            raise SetupError('Release receipt escapes the download directory')
        data = mapping(json.loads(receipt.read_text(encoding='utf-8')), 'receipt')
        if type(data.get('schema_version')) is not int or data['schema_version'] != 1:
            raise SetupError('Unknown release receipt schema')
        identity = string(data.get('build'), 'receipt.build')
        if identity in found or identity not in expected:
            raise SetupError(f'Unexpected or duplicate release receipt: {identity}')
        found.add(identity)
        entries = sequence(data.get('assets'), 'receipt.assets')
        if not entries:
            raise SetupError(f'Empty release job: {identity}')
        for raw in entries:
            item = mapping(raw, 'asset')
            name = relative(item.get('name'), 'asset.name')
            if '/' in name or name in names or name in {'release.json', 'SHA256SUMS.txt'}:
                raise SetupError(f'Duplicate or invalid release asset: {name}')
            source = receipt.parent / name
            if source.is_symlink() or not source.is_file():
                raise SetupError(f'Missing release asset: {name}')
            with source.open('rb') as stream:
                digest = hashlib.file_digest(stream, 'sha256').hexdigest()
            if digest != item.get('sha256'):
                raise SetupError(f'Checksum mismatch: {name}')
            names.add(name)
            sources.append(source)
            assets.append({key: string(item.get(key), key) for key in ('name', 'sha256', 'format', 'arch', 'target')})
    if found != set(expected):
        raise SetupError(f'Missing release builds: {sorted(set(expected) - found)}')
    destination.mkdir(parents=True, exist_ok=False)
    for source in sources:
        shutil.copy2(source, destination / source.name)
    write_index(destination, assets)
    return assets


def build(root: Path, job: ReleaseJob, mode: str, destination: Path) -> None:
    """Prepare a trusted repository and run every target before emitting a job receipt.

    Args:
        root: Checked-out application repository.
        job: Explicit runner configuration.
        mode: Qt enables Qt-specific preparation commands.
        destination: New directory receiving this job's release assets.
    """
    os.environ['WINGSETUP_QT'] = 'true' if mode == 'qt' else 'false'
    for command in (*job.prepare, *(job.qt_prepare if mode == 'qt' else ())):
        subprocess.run(command, cwd=root, check=True)
        # Child preparation scripts cannot modify this process; honor Actions PATH exports.
        github_path = os.environ.get('GITHUB_PATH')
        if github_path and Path(github_path).is_file():
            additions = Path(github_path).read_text(encoding='utf-8').splitlines()
            current = os.environ.get('PATH', '').split(os.pathsep)
            for addition in additions:
                if addition and addition not in current:
                    current.insert(0, addition)
            os.environ['PATH'] = os.pathsep.join(current)
    config_path = (root / job.config).resolve()
    if not config_path.is_relative_to(root.resolve()):
        raise SetupError('Package configuration escapes source repository')
    config = load_config(config_path)
    by_name = {item.name: item for item in config.targets}
    if set(job.targets) - by_name.keys():
        raise SetupError(f'{job.id}: unknown package targets')
    destination.mkdir(parents=True, exist_ok=False)
    assets: list[dict[str, str]] = []
    for name in job.targets:
        for item in run_target(config, by_name[name]):
            if item.kind == 'directory':
                continue  # Distributable ZIP/DMG companions carry application bundles.
            platform_name = {'Darwin': 'macos', 'Windows': 'windows'}.get(by_name[name].platform, by_name[name].platform.lower())
            suffixes = {'tar.gz': '.tar.gz', 'app.zip': '.app.zip', 'zip': '.zip', 'inno': '.exe',
                        'deb': '.deb', 'rpm': '.rpm', 'pkg.tar.zst': '.pkg.tar.zst', 'flatpak': '.flatpak', 'dmg': '.dmg'}
            suffix = '-portable.zip' if platform_name == 'windows' and item.format == 'zip' else suffixes.get(item.format)
            # Preserve AppImage names because update metadata and zsync URLs bind them.
            filename = item.path.name if suffix is None else f'{config.application.name}-{config.application.version}-{platform_name}-{item.arch}{suffix}'
            relative(filename, 'release filename')
            if filename in {'release.json', 'SHA256SUMS.txt'} or (destination / filename).exists():
                raise SetupError(f'Duplicate or reserved asset name: {filename}; use unique target output names')
            shutil.copy2(item.path, destination / filename)
            assets.append({'name': filename, 'sha256': item.sha256, 'format': item.format, 'arch': item.arch, 'target': name})
    if not assets:
        raise SetupError('Release build generated no distributable files')
    write_index(destination, assets)
    receipt = json.loads((destination / 'release.json').read_text(encoding='utf-8'))
    receipt_data = mapping(receipt, 'receipt')
    receipt_data['build'] = job.id
    (destination / 'release.json').write_text(json.dumps(receipt_data, indent=2) + '\n', encoding='utf-8')


def main() -> None:
    """Dispatch planning, per-runner builds, or final release aggregation."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('plan', 'build', 'collect'))
    parser.add_argument('--file', type=Path)
    parser.add_argument('--builds', default='all')
    parser.add_argument('--root', type=Path, default=Path.cwd())
    parser.add_argument('--mode', choices=('qt', 'plain'), default='qt')
    parser.add_argument('--destination', type=Path, default=Path('release-assets'))
    parser.add_argument('--inputs', type=Path, default=Path('downloaded-assets'))
    parser.add_argument('--expected', default='[]')
    args = parser.parse_args()
    if args.command == 'collect':
        assets = collect(args.inputs, args.destination, strings(json.loads(args.expected), 'expected'))
        output('assets', json.dumps(assets, separators=(',', ':')))
        output('checksums', (args.destination / 'SHA256SUMS.txt').read_text(encoding='utf-8').rstrip())
        output('files', '\n'.join(item['name'] for item in assets))
        summary = os.environ.get('GITHUB_STEP_SUMMARY')
        if summary:
            with Path(summary).open('a', encoding='utf-8') as stream:
                stream.write('## Release assets / 发布资产\n\n| File / 文件 | SHA-256 |\n| --- | --- |\n')
                for item in assets:
                    stream.write(f"| {item['name'].replace('|', '&#124;')} | `{item['sha256']}` |\n")
        return
    if args.file is None:
        raise SetupError('--file is required')
    build_file = args.file.resolve()
    source_root = args.root.resolve()
    if not build_file.is_relative_to(source_root):
        raise SetupError('Build configuration escapes source repository')
    jobs = load_jobs(build_file, args.builds)
    if args.command == 'build':
        if len(jobs) != 1:
            raise SetupError('A runner must select exactly one build')
        build(args.root, jobs[0], args.mode, args.destination)
    else:
        for job in jobs:
            package_file = (source_root / job.config).resolve()
            if not package_file.is_relative_to(source_root):
                raise SetupError('Package configuration escapes source repository')
            config = load_config(package_file)
            if set(job.targets) - {target.name for target in config.targets}:
                raise SetupError(f'{job.id}: unknown package targets')
        commit = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=source_root, check=True,
                                text=True, stdout=subprocess.PIPE).stdout.strip()
        output('source-ref', commit)
        matrix = [{'id': job.id, 'runner': list(job.runner), 'qt_version': job.qt_version,
                   'qt_arch': job.qt_arch, 'qt_modules': job.qt_modules, 'system': job.system,
                   'environment': {'BUILD_CONFIG': str(build_file.relative_to(source_root)), 'BUILD_ID': job.id, 'MODE': args.mode}} for job in jobs]
        output('matrix', json.dumps({'include': matrix}, separators=(',', ':')))
        output('expected', json.dumps([job.id for job in jobs]))
        print(json.dumps(matrix, indent=2))


if __name__ == '__main__':
    main()
