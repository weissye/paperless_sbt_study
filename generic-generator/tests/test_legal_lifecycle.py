"""Legal graph transitions must be accepted and have fresh source/target evidence."""
import copy
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
import test_compiled_relationships as compiled
from tools.relationship_execution import validate_legal_receipts, select_run_source

ROOT = Path(__file__).resolve().parents[1]

class LegalLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiled.CompiledRelationshipTests.setUpClass()
        cls.profile = json.loads((ROOT / 'profiles/mealie-relational-legal-lifecycle.json').read_text())
        cls.result = compiled.CompiledRelationshipTests.generate(relationship_profile=cls.profile)

    def test_dependencies_and_counts(self):
        plan = self.result.resource_maps['relationship_scenario_plan']
        report = self.result.resource_maps['relationship_compilation']
        self.assertEqual((report['task_count'], report['http_requests_per_complete_schedule']), (96, 326))
        lifecycle = [t for t in plan['tasks'] if t.get('lifecycle_phase')]
        self.assertEqual([t['kind'] for t in lifecycle], ['unlink', 'link', 'negative_link'])
        self.assertIn(lifecycle[0]['id'], lifecycle[1]['after'])
        self.assertIn(lifecycle[1]['id'], lifecycle[2]['after'])
        self.assertEqual(lifecycle[2]['cycle_path'][-1], lifecycle[2]['source_instance'])
        self.assertEqual(len(report['legal_readback_tasks']), 6)
        self.assertNotRegex(self.result.stories_js, r'\bsvc\.')

    def test_runtime_accepts_legal_links_and_rejects_injected_faults(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'interfaces.regression.js').write_text(self.result.interfaces_js)
            (root/'stories.regression.js').write_text(self.result.stories_js)
            (root/'relationship_scenario_plan.json').write_text(json.dumps(self.result.resource_maps['relationship_scenario_plan']))
            for seed, fault in [(11,''),(22,''),(33,''),(11,'legal-rejected'),(11,'unlink-ignored'),(11,'legal-target-id'),(11,'cycle-target-mutates-on-reject')]:
                process = subprocess.run(['node',str(ROOT/'tests/check_compiled_relationships.js'),str(root),str(seed),fault],capture_output=True,text=True)
                self.assertEqual(process.returncode,0,process.stdout+process.stderr)

    def test_incomplete_or_forged_legal_evidence_is_rejected(self):
        plan = {'tasks':[{'id':'legal','kind':'link','legal_readback':True,'target_instances':['B']}]}
        record = {'task_id':'legal','source_readback':True,'expected':['id-B'],'observed':['id-B'],'targets_read':['B']}
        validate_legal_receipts({'legal_tests':[record]},plan)
        for key,value in [('source_readback',False),('targets_read',[]),('observed',[]),('expected',[None])]:
            bad=copy.deepcopy(record);bad[key]=value
            with self.assertRaises(ValueError):validate_legal_receipts({'legal_tests':[bad]},plan)
        with self.assertRaises(ValueError):validate_legal_receipts({},plan)

    def test_opt_in_is_validated(self):
        profile=copy.deepcopy(self.profile);profile['recursive_relationships'][0]['legal_lifecycle']='true'
        with self.assertRaisesRegex(ValueError,'boolean'):
            compiled.CompiledRelationshipTests.generate(relationship_profile=profile)

    def test_single_sample_reuses_source_and_multiple_samples_keep_selection(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'samples.json';source.write_text('[{"id":1}]')
            self.assertEqual(select_run_source([{'id':1}],1,source,root),source)
            self.assertFalse((root/'selected-sample.json').exists())
            selected=select_run_source([{'id':1},{'id':2}],2,source,root)
            self.assertEqual(json.loads(selected.read_text()),[{'id':2}])
