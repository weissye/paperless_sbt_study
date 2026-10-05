"""Campaign acceptance must be based on complete independent native evidence."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.relationship_campaign import summarize
from tools.relationship_execution import model_hashes


class CampaignTests(unittest.TestCase):
    def project(self, parent, name, reverse=False):
        project = Path(parent) / name
        (project / 'spec/js').mkdir(parents=True)
        (project / 'execution-review').mkdir()
        (project / 'spec/js/interfaces.test.js').write_text('// fake evidence fixture')
        tasks = [{'id': 'A', 'after': [], 'kind': 'create'}, {'id': 'B', 'after': [], 'kind': 'create'},
                 {'id': 'probe', 'after': ['A', 'B'], 'kind': 'negative_link', 'cycle_path': ['A', 'B'], 'rejection_codes': [400], 'verify_cycle_members': True}]
        plan = {'tasks': tasks, 'instances': {'type': ['A', 'B']}}
        compilation = {'http_requests_per_complete_schedule': 18}
        (project / 'relationship_scenario_plan.json').write_text(json.dumps(plan))
        (project / 'relationship_compilation.json').write_text(json.dumps(compilation))
        sample = {'status': 'NATIVE_SYMBOLIC_SAMPLES_COMPLETE', 'model_sha256': model_hashes(project), 'task_orders': [['B', 'A', 'probe'] if reverse else ['A', 'B', 'probe']]}
        receipt = {'status': 'LIVE_CALLBACKS_COMPLETE', 'task_count': 3, 'response_count': 18, 'owned_instances': 2,
                   'negative_tests': [{'task_id': 'probe', 'cycle_length': 2, 'code': 400, 'source_unchanged': True, 'all_members_unchanged': True,
                                       'member_checks': [{'instance': x, 'unchanged': True} for x in ['A', 'B']]}]}
        live = {'status': 'NATIVE_RELATIONSHIP_CALLBACKS_PASS', 'native_exit_code': 0, 'live_accepted': True, 'sample_id': 1, 'runtime_receipt': receipt}
        (project / 'execution-review/sample-acceptance.json').write_text(json.dumps(sample))
        (project / 'execution-review/run-acceptance.json').write_text(json.dumps(live))
        return project

    def test_distinct_orders_are_measured_and_duplicates_do_not_count(self):
        with tempfile.TemporaryDirectory() as temporary:
            a = self.project(temporary, 'a')
            b = self.project(temporary, 'b', reverse=True)
            result = summarize([a, b], 2)
            self.assertEqual(result['status'], 'EXPANDED_CAMPAIGN_PASS')
            self.assertEqual(result['distinct_task_orders'], 2)
            self.assertEqual(summarize([a, a], 2)['status'], 'EXPANDED_CAMPAIGN_NOT_ACCEPTED')
            self.assertEqual(summarize([a], 2)['status'], 'EXPANDED_CAMPAIGN_NOT_ACCEPTED')
            self.assertEqual(summarize([a], 1)['status'], 'EXPANDED_SINGLE_RUN_PASS')

    def test_same_order_is_not_reported_as_schedule_variation(self):
        with tempfile.TemporaryDirectory() as temporary:
            a = self.project(temporary, 'a')
            b = self.project(temporary, 'b')
            result = summarize([a, b], 2)
            self.assertEqual(result['status'], 'EXPANDED_CAMPAIGN_NO_SCHEDULE_VARIATION')
            self.assertEqual(result['accepted_runs'], 2)
            self.assertFalse(result['schedule_variation_observed'])

    def test_failed_live_changed_model_and_incomplete_member_evidence_are_rejected(self):
        for fault in ['exit', 'model', 'member', 'order']:
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as temporary:
                project = self.project(temporary, 'a')
                path = project / 'execution-review/run-acceptance.json'
                live = json.loads(path.read_text())
                if fault == 'exit':
                    live['native_exit_code'] = 2
                elif fault == 'member':
                    live['runtime_receipt']['negative_tests'][0]['member_checks'].pop()
                elif fault == 'model':
                    (project / 'spec/js/interfaces.test.js').write_text('// changed')
                else:
                    sample_path = project / 'execution-review/sample-acceptance.json'
                    sample = json.loads(sample_path.read_text())
                    sample['task_orders'] = [['probe', 'A', 'B']]
                    sample_path.write_text(json.dumps(sample))
                path.write_text(json.dumps(live))
                self.assertEqual(summarize([project], 1)['status'], 'EXPANDED_CAMPAIGN_NOT_ACCEPTED')

    def test_campaign_zip_contains_each_review_without_large_native_payloads(self):
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            project = self.project(parent, 'a')
            (project / 'relationship-samples.json').write_text('EXCLUDED SAMPLE')
            (project / 'execution-review/native-result.json').write_text('EXCLUDED RESULT')
            manifest = parent / 'manifest.json'
            manifest.write_text(json.dumps({'expected_runs': 1, 'projects': [str(project)]}))
            destination = parent / 'campaign.zip'
            process = subprocess.run([sys.executable, str(ROOT / 'tools/relationship_campaign.py'), '--manifest', str(manifest), '--review-zip', str(destination)], capture_output=True, text=True)
            self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
            with zipfile.ZipFile(destination) as archive:
                self.assertIn('campaign-acceptance.json', archive.namelist())
                self.assertIn('run-1-review.zip', archive.namelist())
            with zipfile.ZipFile(parent / 'run-1-review.zip') as archive:
                self.assertIn('execution-review/run-acceptance.json', archive.namelist())
                self.assertFalse(any(name.endswith(('relationship-samples.json', 'native-result.json')) for name in archive.namelist()))


if __name__ == '__main__':
    unittest.main()
