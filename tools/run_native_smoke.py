"""Bounded native infrastructure pilot. No cleanup or automatic retry."""
import argparse
from datetime import datetime, timezone
import getpass
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--username', default='research_admin')
    parser.add_argument('--sample-only', action='store_true')
    args = parser.parse_args()
    root = args.root.resolve()
    generator = root / 'generic-generator'
    contract = root / 'model/paperless-openapi.json'
    runtime = json.loads((root / 'profiles/paperless-native-runtime.json').read_text(encoding='utf-8-sig'))
    if hashlib.sha256(contract.read_bytes()).hexdigest() != runtime['contract_sha256']:
        raise ValueError('Pinned contract differs from the pilot profile.')
    if not shutil.which('provengo'):
        raise ValueError('Provengo is not on PATH. No server requests were sent.')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:8]
    project = root / 'provengo' / ('paperless-native-' + stamp)
    output = project / 'spec/js'
    output.mkdir(parents=True)
    (project / 'config').mkdir()
    (project / 'config/provengo.yml').write_text('version: 2\n', encoding='utf-8')
    command = [sys.executable, '-B', '-m', 'generator_v56', 'generate', '--openapi', str(contract),
               '--name', 'paperless', '--base-url', 'http://127.0.0.1:9930', '--out', str(output),
               '--seed', '1101', '--story-profile', 'parallel-crud', '--resource-maps',
               '--relationship-profile', str(root / 'profiles/paperless-native-scope.json'),
               '--compile-relationships', '--relationship-runtime', str(root / 'profiles/paperless-native-runtime.json')]
    subprocess.run(command, cwd=generator, check=True)
    for path in output.glob('*.json'):
        shutil.copyfile(path, project / path.name)
    review = root / 'runs' / ('native-smoke-' + stamp)
    review.mkdir(parents=True)
    execution = generator / 'tools/relationship_execution.py'
    env = os.environ.copy()
    if not any('-Xmx' in env.get(k, '') for k in ('JAVA_TOOL_OPTIONS', '_JAVA_OPTIONS', 'JDK_JAVA_OPTIONS')):
        env['JAVA_TOOL_OPTIONS'] = (env.get('JAVA_TOOL_OPTIONS', '') + ' -Xmx1g').strip()
    print('Sampling one bounded schedule. No server requests are sent.', flush=True)
    subprocess.run([sys.executable, '-B', str(execution), 'sample', '--project', str(project),
                    '--size', '1', '--review-zip', str(review / 'sampling-review.zip')], env=env, check=True)
    if args.sample_only:
        print('SAMPLE_ONLY_COMPLETE: ' + str(review))
        return
    print('Infrastructure pilot: login, four statistics reads, two tag creations and two identity readbacks. Tags are retained.', flush=True)
    env['SBT_REL_USERNAME'] = args.username
    env['SBT_REL_PASSWORD'] = getpass.getpass('Paperless password: ')
    try:
        subprocess.run([sys.executable, '-B', str(execution), 'run', '--project', str(project),
                        '--sample-id', '1', '--review-zip', str(review / 'live-review.zip')], env=env, check=True)
    finally:
        env.pop('SBT_REL_PASSWORD', None)
        print('Review directory: ' + str(review), flush=True)


if __name__ == '__main__':
    main()
