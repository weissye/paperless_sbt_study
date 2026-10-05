"""Read-only failure collection, missing tools and token protection."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from collect_relationship_failure import collect


class FailureCollectionTests(unittest.TestCase):
    def prepare(self, root):
        project = root / 'project'
        review = project / 'execution-review'
        review.mkdir(parents=True)
        (project / 'relationship_scenario_plan.json').write_text('{"tasks": []}')
        (review / 'run-output.txt').write_text('FAIL: unexpected response')
        (review / 'native-result.json').write_text(json.dumps({'results': [{'responseCode': 400, 'body': 'Circular reference', 'messages': ['Authorization: Bearer SECRET_TOKEN'] }]}))
        return project

    def test_missing_docker_preserves_source_and_extracts_native_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = self.prepare(root)
            before = {str(p.relative_to(project)): p.read_bytes() for p in project.rglob('*') if p.is_file()}
            with patch('collect_relationship_failure.shutil.which', return_value=None):
                report = collect(project, root / 'review.zip', 'server', 'start', 'end')
            after = {str(p.relative_to(project)): p.read_bytes() for p in project.rglob('*') if p.is_file()}
            self.assertEqual(before, after)
            self.assertEqual(report['api_requests'], 0)
            self.assertEqual(report['docker_logs']['status'], 'DOCKER_CLIENT_UNAVAILABLE')
            with zipfile.ZipFile(root / 'review.zip') as archive:
                text = archive.read('native-failure-extract.json').decode()
                self.assertIn('Circular reference', text)
                self.assertNotIn('SECRET_TOKEN', text)
                self.assertNotIn('execution-review/native-result.json', archive.namelist())

    def test_docker_command_only_reads_logs_and_redacts_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = self.prepare(root)
            def run(command, **kwargs):
                self.assertEqual(command, ['docker-test', 'logs', '--timestamps', '--tail', '1000', '--since', 'start', '--until', 'end', 'server'])
                kwargs['stdout'].write(b'HTTP 400 Circular reference; Authorization: Bearer SECRET_TOKEN\n')
                return subprocess.CompletedProcess(command, 0)
            with patch('collect_relationship_failure.shutil.which', return_value='docker-test'), patch('collect_relationship_failure.subprocess.run', side_effect=run):
                report = collect(project, root / 'review.zip', 'server', 'start', 'end')
            self.assertEqual(report['docker_logs']['status'], 'CAPTURED')
            with zipfile.ZipFile(root / 'review.zip') as archive:
                self.assertNotIn('SECRET_TOKEN', archive.read('server-log.txt').decode())
                self.assertNotIn('server-log.raw', archive.namelist())

    def test_timeout_discards_unredacted_partial_log(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = self.prepare(root)
            def run(command, **kwargs):
                kwargs['stdout'].write(b'Authorization: Bearer SECRET_TOKEN')
                raise subprocess.TimeoutExpired(command, 30)
            with patch('collect_relationship_failure.shutil.which', return_value='docker-test'), patch('collect_relationship_failure.subprocess.run', side_effect=run):
                report = collect(project, root / 'review.zip', 'server', 'start', 'end')
            self.assertEqual(report['docker_logs']['status'], 'TIMEOUT')
            with zipfile.ZipFile(root / 'review.zip') as archive:
                self.assertNotIn('server-log.raw', archive.namelist())


if __name__ == '__main__':
    unittest.main()
