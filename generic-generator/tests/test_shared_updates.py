"""Contract-derived shared target updates preserve every observed inbound binding."""
import copy
import json
from pathlib import Path
import unittest
import test_alternate_paths as alternate
import test_compiled_relationships as compiled
from tools.relationship_execution import validate_shared_update_receipts

ROOT = Path(__file__).resolve().parents[1]

class SharedUpdateTests(unittest.TestCase):
    execute = alternate.AlternatePathTests.execute
    @classmethod
    def setUpClass(cls):
        compiled.CompiledRelationshipTests.setUpClass()
        cls.profile = json.loads((ROOT/'profiles/mealie-relational-alternate-paths.json').read_text())
        cls.runtime = json.loads((ROOT/'profiles/mealie-relational-shared-update-runtime.json').read_text())
        cls.result = compiled.CompiledRelationshipTests.generate(relationship_profile=cls.profile, relationship_runtime=cls.runtime)

    def test_shared_targets_and_all_referrers_are_checked(self):
        plan = self.result.resource_maps['relationship_scenario_plan']
        tasks = [t for t in plan['tasks'] if t['kind']=='shared_update']
        self.assertTrue(tasks)
        self.assertEqual({t['source_instance'].split('#')[0] for t in tasks}, {'api/foods','api/units'})
        for task in tasks:
            self.assertGreaterEqual(len({r['instance'] for r in task['referrers']}), 2)
        for seed in [11,22,33]:
            evidence = self.execute(self.result, seed)
            self.assertEqual(evidence['http_requests'], self.result.resource_maps['relationship_compilation']['http_requests_per_complete_schedule'])
            validate_shared_update_receipts({'shared_updates':evidence['shared_updates']},plan)
        self.assertNotRegex(self.result.stories_js, r'\bsvc\.')

    def test_update_and_reference_faults_fail_closed(self):
        for fault in ['shared-update-ignored','shared-reference-changed']:
            self.execute(self.result,11,fault)

    def test_configuration_is_opt_in_and_rejects_unshared_or_identity_fields(self):
        legacy = copy.deepcopy(self.runtime); legacy.pop('shared_target_updates')
        result = compiled.CompiledRelationshipTests.generate(relationship_profile=self.profile,relationship_runtime=legacy)
        self.assertEqual(result.resource_maps['relationship_compilation']['task_count'],109)
        for field in ['id','slug','missing']:
            runtime = copy.deepcopy(self.runtime);runtime['shared_target_updates'][0]['field']=field
            with self.assertRaises(ValueError):
                compiled.CompiledRelationshipTests.generate(relationship_profile=self.profile,relationship_runtime=runtime)
        runtime = copy.deepcopy(self.runtime);runtime['shared_target_updates'][0]['resource_type']='api/recipes'
        with self.assertRaises(ValueError):
            compiled.CompiledRelationshipTests.generate(relationship_profile=self.profile,relationship_runtime=runtime)

    def test_receipt_rejects_missing_and_duplicate_referrers(self):
        plan = self.result.resource_maps['relationship_scenario_plan']
        evidence = self.execute(self.result)
        for variant in ['missing','duplicate','changed']:
            receipt={'shared_updates':copy.deepcopy(evidence['shared_updates'])}
            checks=receipt['shared_updates'][0]['referrers']
            if variant=='missing':checks.pop()
            elif variant=='duplicate':checks[-1]=copy.deepcopy(checks[0])
            else:checks[0]['after']=['wrong-id']
            with self.assertRaises(ValueError):validate_shared_update_receipts(receipt,plan)
