"""Preserve scoped study sources/evidence in Git; never stage runtime data."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

PATHS = ['generic-generator', 'model', 'profiles', 'scripts', 'tools', 'validation',
         'docs', 'evidence', 'deployment', 'README-PAPERLESS-NATIVE.md', 'README-GIT-HANDOFF.md',
         'README.md', 'SHA256SUMS.json', 'GIT-HANDOFF-SHA256.json', '.gitignore', '.gitattributes']
IGNORE = '''
# Portable Paperless research: local secrets and runtime state
.env
.env.*
docker-compose.env
*.secrets.env
/runs/
/provengo/
/consume/
/export/
/media/
/data/
/db/
.venv/
__pycache__/
*.pyc
'''
ATTRIBUTES = '\n# Research evidence must preserve binary bytes\n*.zip -text\n*.docx -text\n*.pdf -text\n'


def git(root, *args, check=True):
    return subprocess.run(['git', '-C', str(root), *args], check=check,
                          capture_output=True, text=True, encoding='utf-8', errors='replace')


def save(root, remote, push):
    root = Path(root).resolve()
    evidence = root / 'evidence/native-smoke-20261005-160959'
    expected = json.loads((evidence / 'qualification.json').read_text(encoding='utf-8-sig'))
    archive = evidence / 'live-review-original.zip'
    if hashlib.sha256(archive.read_bytes()).hexdigest() != expected['archive_sha256']:
        raise ValueError('Archived native evidence hash mismatch. Git was not changed.')
    for path, appended in [('.gitignore', IGNORE), ('.gitattributes', ATTRIBUTES)]:
        target = root / path
        old = target.read_text(encoding='utf-8-sig') if target.exists() else ''
        if appended.strip() not in old:
            target.write_text(old.rstrip() + '\n' + appended, encoding='utf-8')
    if not (root / '.git').exists():
        enclosing = git(root, 'rev-parse', '--show-toplevel', check=False)
        if enclosing.returncode == 0:
            raise ValueError('Study is inside another Git repository. A separate root is required.')
        git(root, 'init', '-b', 'main')
    if git(root, 'symbolic-ref', '--short', 'HEAD').stdout.strip() != 'main':
        raise ValueError('Expected main branch. No branch was renamed.')
    origin = git(root, 'remote', 'get-url', 'origin', check=False)
    if origin.returncode != 0:
        git(root, 'remote', 'add', 'origin', remote)
    elif origin.stdout.strip() != remote:
        raise ValueError('Existing origin differs from the requested repository. It was not changed.')
    staged = git(root, 'diff', '--cached', '--quiet', check=False)
    if staged.returncode != 0:
        raise ValueError('Existing staged changes must be committed or unstaged before this scoped save.')
    selected = [p for p in PATHS if (root / p).exists()]
    for item in selected:
        path = root / item
        files = path.rglob('*') if path.is_dir() else [path]
        for file in files:
            if file.is_file() and file.stat().st_size >= 50 * 1024 * 1024:
                raise ValueError('Large source/evidence file requires a separate storage decision: ' + str(file))
    git(root, 'add', '--', *selected)
    # Preserve these reviewed evidence bytes even if a global rule ignores ZIPs.
    git(root, 'add', '-f', '--',
        str(archive.relative_to(root)),
        str((evidence / 'qualification.json').relative_to(root)),
        str((evidence / 'HANDOFF.md').relative_to(root)),
        'docs/research/Next_System_Experimental_Protocol.docx')
    staged_names = git(root, 'diff', '--cached', '--name-only').stdout.splitlines()
    prohibited = [p for p in staged_names if Path(p).name in ('.env', 'docker-compose.env') or
                  p.startswith(('runs/', 'provengo/', 'consume/', 'export/'))]
    if prohibited:
        raise ValueError('Local runtime/secrets were already tracked; review before committing: ' + ', '.join(prohibited))
    if staged_names:
        print(git(root, 'commit', '-m', 'Preserve Paperless generator, pinned contract and verified native pilot').stdout)
    else:
        print('No new scoped changes to commit.')
    if push:
        print(git(root, 'push', '-u', 'origin', 'main').stderr)
        remote_head = git(root, 'ls-remote', 'origin', 'refs/heads/main').stdout.split()
        local_head = git(root, 'rev-parse', 'HEAD').stdout.strip()
        if not remote_head or remote_head[0] != local_head:
            raise ValueError('Remote HEAD verification failed.')
        print('PAPERLESS_GIT_PUSH_VERIFIED: ' + local_head)
    else:
        print('PAPERLESS_SCOPED_COMMIT_SAVED; push was not requested.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', required=True)
    parser.add_argument('--remote', default='https://github.com/weissye/paperless_sbt_study.git')
    parser.add_argument('--push', action='store_true')
    args = parser.parse_args()
    try:
        save(args.root, args.remote, args.push)
    except subprocess.CalledProcessError as error:
        print(error.stderr or error.stdout or str(error), file=sys.stderr)
        print('Git operation failed. Existing source and any created local commit were preserved.', file=sys.stderr)
        raise SystemExit(1)
    except (ValueError, OSError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
