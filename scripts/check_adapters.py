#!/usr/bin/env python3
"""Offline checks for independently distributed adapters in this workspace.

Build every adapters/* project and its source-rebuilt wheel. Install each into
its own clean environment alongside the core wheel, outside all checkouts, run
its regression suite, then uninstall it and rescore unchanged core Runs.
Scientific dependencies and model training are not part of this check.
"""
import argparse
import configparser
from email.parser import BytesParser
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import sys
import tarfile
import tempfile
import zipfile

from packaging.specifiers import SpecifierSet

import check_release as release


PROBE = '''
import json
from pathlib import Path
import sys
from gymts import GymTS
from gymts.contracts import digest
name, module, fixture, store, saved = sys.argv[1:]
assert module not in sys.modules
with GymTS(store) as gym:
    assert not gym.enabled_integrations
    info = next(item for item in gym.available_integrations() if item['name'] == name)
    assert info['status'] == 'available'
    assert module not in sys.modules
    gym.enable_integration(name)
    gym.enable_integration(name)
    assert gym.enabled_integrations == (name,)
    assert module in sys.modules
    spec = json.loads(Path(fixture).read_text())
    report = gym.autobench.evaluate(spec)
    assert report['status'] == 'completed', report
    plan = gym.artifacts.read_json(report['plan_ref'])
    manifest = gym.artifacts.read_json(report['run_manifest_ref'])
    executions = {entry['unit_id']: entry for entry in manifest['entries']}
    runs = [{'unit_id': unit['unit_id'], 'evaluation_case_id': unit['evaluation_case_id'],
             'candidate_id': unit['candidate_id'], 'repetition': unit['repetition'],
             'run_id': executions[unit['unit_id']]['run_id'], 'unavailable_reason': None,
             'unit_spec_ref': unit['resolved_spec_ref']} for unit in plan['expected_units']]
    assert all(run['run_id'] for run in runs)
    score = {'protocol_version': 'gymts.score/1', 'name': 'after-adapter-removal',
             'purpose': spec['purpose'], 'runs': runs, 'baseline_id': spec['baseline_id'],
             'scoring': spec['scoring'], 'comparison': spec['comparison'],
             'failure_policy': spec['failure_policy'], 'previous_evaluation_id': report['evaluation_id']}
    Path(saved).write_text(json.dumps({'score': score,
        'results': {run['run_id']: digest(gym.records.get_run(run['run_id'])['result']) for run in runs}}))
print(json.dumps({'discovery_without_import': True, 'explicit_idempotent_enable': True,
                  'core_evaluation_runs': len(runs)}))
'''

AFTER_REMOVAL = '''
import importlib.util
import json
from pathlib import Path
import sys
from gymts import GymTS
from gymts.contracts import digest
name, module, store, saved = sys.argv[1:]
assert importlib.util.find_spec(module) is None
previous = json.loads(Path(saved).read_text())
def forbidden(*args, **kwargs):
    raise AssertionError('Rescoring must not run a Candidate')
with GymTS(store) as gym:
    assert not any(item['name'] == name for item in gym.available_integrations())
    gym.environment_ts.run = forbidden
    report = gym.autobench.score(previous['score'])
    assert report['status'] == 'completed', report
    manifest = gym.artifacts.read_json(report['run_manifest_ref'])
    assert [entry['run_id'] for entry in manifest['entries']] == [run['run_id'] for run in previous['score']['runs']]
    assert all(digest(gym.records.get_run(run_id)['result']) == result for run_id, result in previous['results'].items())
print(json.dumps({'uninstall_preserves_core': True, 'rescoring_keeps_runs_and_results': True}))
'''


def inspect(path, expected, module):
    members = {}
    if path.suffix == '.whl':
        with zipfile.ZipFile(path) as archive:
            for entry in archive.infolist():
                release.check_member(entry.filename)
                if entry.is_dir():
                    continue
                if (entry.external_attr >> 16) & 0o170000 == 0o120000:
                    raise release.ReleaseError('Symbolic link in adapter wheel')
                members[entry.filename] = archive.read(entry)
        prefix = module + '/'
        if any(not name.startswith(prefix) and '.dist-info/' not in name for name in members):
            raise release.ReleaseError('Adapter wheel contains a foreign package')
        metadata = [data for name, data in members.items() if name.endswith('.dist-info/METADATA')]
        if len(metadata) != 1:
            raise release.ReleaseError('Adapter wheel needs unique metadata')
        requirements = BytesParser().parsebytes(metadata[0]).get_all('Requires-Dist', [])
        if not any(re.match(r'gymts\s*[<(=>]', value, re.I) for value in requirements):
            raise release.ReleaseError('Adapter must declare its core compatibility range')
        module_names = {name for name in members if name.endswith('.py')}
    else:
        with tarfile.open(path, 'r:gz') as archive:
            for entry in archive.getmembers():
                release.check_member(entry.name)
                if entry.isdir():
                    continue
                if not entry.isfile():
                    raise release.ReleaseError('Non-regular adapter source member')
                members[entry.name] = archive.extractfile(entry).read()
        roots = {PurePosixPath(name).parts[0] for name in members}
        if len(roots) != 1:
            raise release.ReleaseError('Adapter source needs one root')
        prefix = next(iter(roots)) + '/'
        members = {name[len(prefix):]: data for name, data in members.items()}
        required = {'README.md', 'setup.cfg', 'pyproject.toml', 'MANIFEST.in'}
        if not required.issubset(members) or not any(name.startswith('tests/') for name in members):
            raise release.ReleaseError('Adapter source is missing metadata or its regression suite')
        module_names = {name[len('src/'):] for name in members if name.startswith('src/') and name.endswith('.py')}
    for name, data in members.items():
        release.check_member(name, data)
        if name.startswith('gymts/') or name.startswith('src/gymts/'):
            raise release.ReleaseError('Adapter must not overwrite the core namespace')
    if module_names != expected:
        raise release.ReleaseError('Adapter modules differ from source')
    return {'file': path.name, 'files': len(members), 'bytes': path.stat().st_size,
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def pip(python, work, *args):
    return release.command([python, '-I', '-B', '-m', 'pip', '--isolated', '--disable-pip-version-check', *args], work)


def check_adapter(project, core_wheel, core_source, work, *, dependency_wheels=None):
    config = configparser.ConfigParser()
    config.read(project / 'setup.cfg', encoding='utf-8')
    name = config['metadata']['name']
    module = name.replace('-', '_')
    entry = config['options.entry_points']['gymts.integrations'].strip()
    integration = entry.split('=', 1)[0].strip()
    source = work / 'source'
    shutil.copytree(project, source, symlinks=True, ignore=release.snapshot_ignore)
    if any(path.is_symlink() for path in source.rglob('*')):
        raise release.ReleaseError('Adapter inputs must not contain symbolic links')
    expected = {path.relative_to(project / 'src').as_posix() for path in (project / 'src').rglob('*.py')}
    distributions = work / 'distributions'
    distributions.mkdir()
    sdist = release.build(source, distributions, 'sdist')
    wheel = release.build(source, distributions, 'wheel')
    sdist_report, wheel_report = inspect(sdist, expected, module), inspect(wheel, expected, module)
    extracted = work / 'extracted'
    extracted.mkdir()
    rebuilt_source = release.extract_source(sdist, extracted)
    rebuilt_dir = work / 'rebuilt'
    rebuilt_dir.mkdir()
    rebuilt_wheel = release.build(rebuilt_source, rebuilt_dir, 'wheel')
    rebuilt_report = inspect(rebuilt_wheel, expected, module)
    install = work / 'installed'
    install.mkdir()
    core_details = release.install_and_test(core_wheel, core_source, install, False)
    python = install / 'venv' / ('Scripts/python.exe' if sys.platform == 'win32' else 'bin/python')
    dependency_args = (['--find-links', str(dependency_wheels)] if dependency_wheels else ['--no-deps'])
    pip(python, install, 'install', '--no-index', *dependency_args, '--no-compile', str(wheel))
    for line in config['options.entry_points'].get('console_scripts', '').splitlines():
        if line.strip():
            console_name = line.split('=', 1)[0].strip()
            console = python.parent / (console_name + '.exe' if sys.platform == 'win32' else console_name)
            release.command([console, '--help'], install)
    fixture = core_source / 'examples' / 'forecast_evaluation.json'
    store, saved = install / 'persistent-store', install / 'before-removal.json'
    probe = json.loads(release.command([python, '-I', '-B', '-c', PROBE, integration, module, fixture, store, saved], install))
    verification = install / 'verification'
    verification.mkdir()
    for item in ('tests', 'scripts', 'examples'):
        if (rebuilt_source / item).exists():
            shutil.copytree(rebuilt_source / item, verification / item, ignore=release.snapshot_ignore)
    output = release.command([python, '-I', '-B', '-m', 'unittest', 'discover', '-s', verification / 'tests', '-q'], install)
    match = re.search(r'Ran (\d+) tests?', output)
    if not match:
        raise release.ReleaseError('Adapter regressions did not report a count')
    skipped = re.search(r'OK \(skipped=(\d+)\)', output)
    pip(python, install, 'uninstall', '--yes', name)
    removal = json.loads(release.command([python, '-I', '-B', '-c', AFTER_REMOVAL, integration, module, store, saved], install))
    pip(python, install, 'install', '--no-index', *dependency_args, '--no-compile', str(rebuilt_wheel))
    release.command([python, '-I', '-B', '-c',
                     'from gymts import GymTS; import sys; g=GymTS(sys.argv[2], integrations=(sys.argv[1],)); g.close()',
                     integration, install / 'rebuilt-store'], install)
    return {'distribution': name, 'version': config['metadata']['version'],
            'distributions': {'wheel': wheel_report, 'sdist': sdist_report, 'rebuilt_wheel': rebuilt_report},
            'core_only': core_details, 'activation': probe,
            'tests': int(match.group(1)), 'skipped': int(skipped.group(1)) if skipped else 0,
            'removal': removal, 'rebuilt_wheel_installed': True}


def check_coexistence(projects, core_wheel, core_source, work, *, dependency_wheels=None):
    install = work / 'coexistence'
    install.mkdir()
    release.install_and_test(core_wheel, core_source, install, False)
    python = install / 'venv' / ('Scripts/python.exe' if sys.platform == 'win32' else 'bin/python')
    packages = []
    for project in projects:
        config = configparser.ConfigParser()
        config.read(project / 'setup.cfg', encoding='utf-8')
        packages.append((config['metadata']['name'],
                         config['options.entry_points']['gymts.integrations'].strip().split('=', 1)[0].strip()))
        wheel = next((work / project.name / 'distributions').glob('*.whl'))
        dependency_args = (['--find-links', str(dependency_wheels)] if dependency_wheels else ['--no-deps'])
        pip(python, install, 'install', '--no-index', *dependency_args, '--no-compile', str(wheel))
    code = '''
import json
from pathlib import Path
import sys
from gymts import GymTS
names = json.loads(sys.argv[1])
with GymTS(sys.argv[3], integrations=names) as gym:
    assert gym.enabled_integrations == tuple(names)
    assert gym.run(json.loads(Path(sys.argv[2]).read_text()))['status'] == 'succeeded'
'''
    fixture = core_source / 'examples' / 'forecast_experiment.json'
    release.command([python, '-I', '-B', '-c', code, json.dumps([item[1] for item in packages]),
                     fixture, install / 'all-enabled'], install)
    removed, removed_name = packages[0]
    pip(python, install, 'uninstall', '--yes', removed)
    remaining = [item[1] for item in packages[1:]]
    release.command([python, '-I', '-B', '-c', code, json.dumps(remaining), fixture,
                     install / 'remaining-enabled'], install)
    release.command([python, '-I', '-B', '-c',
                     'from gymts import GymTS; import sys; '
                     'assert not any(item["name"] == sys.argv[1] for item in GymTS.available_integrations())',
                     removed_name], install)
    return {'all_enabled': [item[1] for item in packages], 'uninstalled': removed,
            'remaining_enabled_and_core_run_succeeded': remaining}


def check(root):
    projects = sorted(path.parent for path in (root / 'adapters').glob('*/pyproject.toml'))
    if not projects:
        raise release.ReleaseError('No independent adapter projects found')
    reports, unsupported = [], []
    compatible = []
    for project in projects:
        config = configparser.ConfigParser()
        config.read(project / 'setup.cfg', encoding='utf-8')
        requirement = config['options'].get('python_requires', '')
        if sys.version.split()[0] not in SpecifierSet(requirement):
            unsupported.append({'distribution': config['metadata']['name'],
                                'requires_python': requirement, 'reason': 'Current Python is outside the declared host compatibility range'})
        else:
            compatible.append(project)
    projects = compatible
    if not projects:
        raise release.ReleaseError('No adapters support the current Python')
    with tempfile.TemporaryDirectory(prefix='gymts-adapters-release-') as temporary:
        work = Path(temporary)
        core_source = work / 'core-source'
        shutil.copytree(root, core_source, symlinks=True, ignore=release.snapshot_ignore)
        distributions = work / 'core-wheel'
        distributions.mkdir()
        core_wheel = release.build(core_source, distributions, 'wheel')
        expected = {path.relative_to(core_source).as_posix() for path in (core_source / 'gymts').rglob('*.py')}
        release.inspect_archive(core_wheel, expected)
        # Workspace adapters may depend on shared domain-contract packages.
        # Resolve only declared dependencies from local wheels, never install
        # every project into each supposedly independent test environment.
        dependency_wheels = work / 'dependency-wheels'
        dependency_wheels.mkdir()
        for project in projects:
            dependency_source = work / ('dependency-source-' + project.name)
            shutil.copytree(project, dependency_source, symlinks=True, ignore=release.snapshot_ignore)
            release.build(dependency_source, dependency_wheels, 'wheel')
        for project in projects:
            target = work / project.name
            target.mkdir()
            reports.append(check_adapter(project, core_wheel, core_source, target,
                                         dependency_wheels=dependency_wheels))
        coexistence = check_coexistence(projects, core_wheel, core_source, work,
                                        dependency_wheels=dependency_wheels)
    return {'status': 'passed', 'offline': True, 'python': sys.version.split()[0], 'adapters': reports,
            'unsupported_python': unsupported,
            'coexistence': coexistence,
            'scope': 'Independent package/activation/regression/removal checks; no model training or quality claim'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    try:
        report = check(Path(__file__).resolve().parents[1])
    except (release.ReleaseError, OSError, ValueError, ImportError) as error:
        print(json.dumps({'status': 'failed', 'error': str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + '\n'
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding='utf-8')
    print(rendered, end='')
    return 0


if __name__ == '__main__':
    sys.exit(main())
