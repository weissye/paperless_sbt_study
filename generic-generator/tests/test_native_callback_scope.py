"""Optional regression using the installed native Provengo runtime and local HTTP fixture."""
import base64
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import unittest

from generator_v56.pipeline import run_pipeline
from tools.relationship_execution import audit_samples, find_receipt, validate_negative_receipts, validate_shared_update_receipts, validate_deletion_receipts, validate_semantic_receipts, model_hashes, digest, bundle

from tools.relationship_sample_campaign import summarize_reviews

ROOT = Path(__file__).resolve().parents[1]
JAR = os.environ.get('PROVENGO_TEST_JAR', '')


@unittest.skipUnless(JAR and Path(JAR).is_file() and shutil.which('java') and shutil.which('node'),
                     'Set PROVENGO_TEST_JAR to enable native runtime tests.')
class NativeCallbackScopeTests(unittest.TestCase):
    def test_native_compact_callbacks_complete_and_detect_identity_corruption(self):
        self.run_model('mealie-relational-compact-runtime.json', ['', 'route-id'])

    def test_native_shared_update_callbacks_detect_both_update_and_reference_faults(self):
        self.run_model('mealie-relational-shared-update-runtime.json', ['', 'shared-update-ignored', 'shared-reference-changed'])

    def test_native_embedded_and_deletion_oracles(self):
        self.run_model('mealie-relational-consistency-runtime.json', ['', '', '', 'embedded-stale', 'delete-ignored', 'delete-unrelated-links', 'delete-cascades-source'])

    def test_native_attached_deletion_during_construction(self):
        self.run_model('mealie-relational-attached-runtime.json', ['', '', '', 'delete-dangling', 'delete-ignored', 'delete-unrelated-links', 'delete-cascades-source'])

    def test_native_semantic_families_and_injected_quantity_merge_faults(self):
        self.run_model('mealie-relational-merge-runtime.json', ['', '', '', 'merge-stale-list', 'merge-500'])
        self.run_model('mealie-relational-quantity-runtime.json', ['', '', '', 'quantity-double', 'remove-manual'])
        self.run_model('mealie-relational-combined-runtime.json', ['', '', '', 'wrong-reference-quantity', 'merge-loses-quantity'])

    def test_native_same_unit_collisions_and_partial_removal(self):
        self.run_model('mealie-relational-collision-runtime.json', ['', '', '', 'merge-collision-drops-item', 'remove-manual'])

    def test_native_opt_in_control_sequences(self):
        for name in ['duplicate-no-merge','merge-no-decrement','single-ingredient','three-ingredient','chain-readd']:
            self.run_model('mealie-control-'+name+'-runtime.json', ['', '', '', 'quantity-double'])

    def test_native_food_and_unit_integer_lifecycles(self):
        for name in ['food-integer-lifecycle','unit-integer-lifecycle']:
            self.run_model('mealie-control-'+name+'-runtime.json', ['', '', '', 'merge-stale-list', 'remove-manual'])

    def test_native_removal_diagnostic_controls(self):
        for resource in ['food','unit']:
            for mode in ['no-merge','one-merge']:
                self.run_model('mealie-control-'+resource+'-integer-'+mode+'-runtime.json', ['', '', '', 'remove-manual'])

    def run_model(self, runtime_filename, faults):
        with tempfile.TemporaryDirectory() as folder:
            project = Path(folder)
            with socket.socket() as port_socket:
                port_socket.bind(('127.0.0.1', 0))
                port = port_socket.getsockname()[1]
            semantic = runtime_filename.startswith('mealie-control-') or runtime_filename in ('mealie-relational-merge-runtime.json','mealie-relational-quantity-runtime.json','mealie-relational-combined-runtime.json','mealie-relational-collision-runtime.json')
            profile = json.loads((ROOT/'profiles'/('mealie-relational-collision-scope.json' if runtime_filename=='mealie-relational-collision-runtime.json' else ('mealie-relational-semantic-scope.json' if semantic else 'mealie-relational-alternate-paths.json'))).read_text())
            if runtime_filename.startswith('mealie-control-'):
                profile = json.loads((ROOT/'profiles'/runtime_filename.replace('-runtime.json','-scope.json')).read_text())
            runtime = json.loads((ROOT/'profiles'/runtime_filename).read_text())
            result = run_pipeline(str(ROOT/'compatibility/contracts/mealie.json'), 'native',
                                  'http://127.0.0.1:'+str(port), 205, story_profile='parallel-crud',
                                  relationship_profile=profile, compile_relationship_model=True,
                                  relationship_runtime=runtime)
            (project/'spec/js').mkdir(parents=True)
            (project/'config').mkdir()
            (project/'config/provengo.yml').write_text('version: 2\n')
            (project/'spec/js/interfaces.native.js').write_text(result.interfaces_js, encoding='utf-8')
            (project/'spec/js/stories.native.js').write_text(result.stories_js, encoding='utf-8')
            plan = result.resource_maps['relationship_scenario_plan']
            (project/'relationship_scenario_plan.json').write_text(json.dumps(plan))
            report = result.resource_maps['relationship_compilation']
            (project/'relationship_compilation.json').write_text(json.dumps(report))
            campaign = semantic or runtime_filename in ('mealie-relational-consistency-runtime.json', 'mealie-relational-attached-runtime.json')
            sample_size = 3 if campaign else 1
            command = ['java', '-Xmx512m', '-jar', str(Path(JAR).resolve())]
            sample = subprocess.run(command+['sample', '--size', str(sample_size), '--max-length', str(max(600, 2*report['task_count']+report['http_requests_per_complete_schedule']+4)),
                                            '-o', 'samples.json', str(project)],
                                    capture_output=True, text=True, timeout=60)
            samples_path = project/'samples.json'
            self.assertEqual(sample.returncode, 0, sample.stdout+sample.stderr)
            self.assertTrue(samples_path.exists(), sample.stdout+sample.stderr)
            self.assertLess(samples_path.stat().st_size, sample_size*8*1024*1024)
            samples = json.loads(samples_path.read_text())
            self.assertEqual(audit_samples(samples, plan)['tasks_per_sample'], report['task_count'])
            calls = [e for e in samples[0] if (e.get('data') or {}).get('lib') == 'REST']
            self.assertEqual(len(calls), report['http_requests_per_complete_schedule'])
            for event in calls:
                blob = base64.b64decode(event['data']['callback']['object'])
                self.assertNotIn(b'sbtRelHttp_', blob)
                self.assertNotIn(b'sbtRelSchemas', blob)
            successful_reviews = []
            positive_count = 0
            for fault in faults:
                if not fault: positive_count += 1
                sample_id = positive_count if campaign and not fault else 1
                environment = dict(os.environ, NATIVE_MOCK_PORT=str(port), NATIVE_MOCK_FAULT=fault,
                                   SBT_REL_USERNAME='local', SBT_REL_PASSWORD='local')
                server = subprocess.Popen(['node', str(ROOT/'tests/native_http_mock.js'), str(project)],
                                          stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                          text=True, env=environment)
                try:
                    self.assertEqual(server.stdout.readline().strip(), 'READY')
                    run = subprocess.run(command+['--batch-mode', 'run', '--run-source', 'samples.json',
                                                 '--run-id', str(sample_id), str(project)], capture_output=True,
                                         text=True, env=environment, timeout=60)
                    output = run.stdout+run.stderr
                    receipt = find_receipt(output)
                    if fault:
                        self.assertNotEqual(run.returncode, 0)
                        self.assertIsNone(receipt)
                    else:
                        self.assertEqual(run.returncode, 0, '\n'.join(line for line in output.splitlines() if any(word in line for word in [' WARN [',' ERR [','Exception'])))
                        self.assertIsNotNone(receipt)
                        self.assertEqual(receipt['task_count'], report['task_count'])
                        self.assertEqual(receipt['response_count'], report['http_requests_per_complete_schedule'])
                        if not semantic:
                            self.assertEqual(len(receipt['legal_tests']), 17)
                            self.assertEqual(len(receipt['negative_tests']), 7)
                        validate_semantic_receipts(receipt, plan)
                        validate_negative_receipts(receipt, plan)
                        validate_shared_update_receipts(receipt, plan)
                        validate_deletion_receipts(receipt, plan)
                        if campaign:
                            review_dir = project/'execution-review';review_dir.mkdir(exist_ok=True)
                            sample_evidence = dict(audit_samples(samples,plan),status='NATIVE_SYMBOLIC_SAMPLES_COMPLETE',model_sha256=model_hashes(project),samples_sha256=digest(samples_path))
                            (review_dir/'sample-acceptance.json').write_text(json.dumps(sample_evidence))
                            (review_dir/'run-acceptance.json').write_text(json.dumps({'status':'NATIVE_RELATIONSHIP_CALLBACKS_PASS','native_exit_code':0,'live_accepted':True,'sample_id':sample_id,'runtime_receipt':receipt}))
                            (review_dir/'run-output.txt').write_text(output)
                            destination = project/('native-review-'+str(sample_id)+'.zip')
                            bundle(project,list(review_dir.glob('*')),destination);successful_reviews.append(destination)
                finally:
                    server.terminate()
                    server.communicate(timeout=10)

            if campaign:
                summary=summarize_reviews(successful_reviews,3)
                self.assertEqual(summary['status'],'CONSISTENCY_CAMPAIGN_PASS',summary)
                self.assertGreater(summary['distinct_mutation_orders'],1,summary)
