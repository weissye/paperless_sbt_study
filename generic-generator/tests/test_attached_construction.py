"""Attached deletion and mutations during construction must have observed evidence."""
import copy
import json
from pathlib import Path
import unittest
import test_compiled_relationships as compiled
import test_alternate_paths as alternate
from tools.relationship_execution import validate_deletion_receipts, validate_shared_update_receipts

ROOT = Path(__file__).resolve().parents[1]

class AttachedConstructionTests(unittest.TestCase):
    execute = alternate.AlternatePathTests.execute

    @classmethod
    def setUpClass(cls):
        compiled.CompiledRelationshipTests.setUpClass()
        cls.profile = json.loads((ROOT/'profiles/mealie-relational-alternate-paths.json').read_text())
        cls.runtime = json.loads((ROOT/'profiles/mealie-relational-attached-runtime.json').read_text())
        cls.result = compiled.CompiledRelationshipTests.generate(relationship_profile=cls.profile, relationship_runtime=cls.runtime)

    def test_attached_deletion_has_no_detach_writes_and_construction_is_interleaved(self):
        plan = self.result.resource_maps['relationship_scenario_plan']
        tasks = {t['id']:t for t in plan['tasks']}
        self.assertEqual(sum(t['kind']=='attached_delete' for t in tasks.values()),10)
        self.assertEqual(self.result.resource_maps['relationship_compilation']['http_requests_per_complete_schedule'],598)
        orders = []
        for seed in [11,22,33]:
            receipt = self.execute(self.result,seed)
            validate_deletion_receipts(receipt,plan)
            validate_shared_update_receipts(receipt,plan)
            order = receipt['task_order']
            first = next(i for i,t in enumerate(order) if tasks[t]['kind'] in ('shared_update','attached_delete'))
            self.assertTrue(any(tasks[t]['kind']=='link' and not tasks[t].get('lifecycle_phase') for t in order[first+1:]))
            self.assertTrue(any(tasks[t]['kind']=='qualified_action' for t in order[first+1:]))
            self.assertTrue(all(r['attached_at_delete'] for r in receipt['detached_deletions']))
            orders.append(tuple(t for t in order if tasks[t]['kind'] in ('shared_update','attached_delete')))
        self.assertEqual(len(set(orders)),3)
        self.assertNotIn("mode:'prepare_detach'",self.result.stories_js)
        self.assertNotRegex(self.result.stories_js,r'\bsvc\.')

    def test_server_success_with_dangling_reference_is_rejected(self):
        for fault in ['delete-dangling','delete-ignored','delete-unrelated-links','delete-cascades-source','embedded-stale']:
            self.execute(self.result,11,fault)

    def test_policy_and_receipt_cannot_be_inferred_or_forged(self):
        for change in ['policy','boolean','duplicate']:
            runtime = copy.deepcopy(self.runtime)
            if change=='policy':runtime['attached_target_deletions'][0].pop('success_policy')
            elif change=='boolean':runtime['mutate_during_construction']='true'
            else:runtime['detached_target_deletions']=[{k:v for k,v in runtime['attached_target_deletions'][0].items() if k!='success_policy'}]
            with self.assertRaises(ValueError):compiled.CompiledRelationshipTests.generate(relationship_profile=self.profile,relationship_runtime=runtime)
        receipt = self.execute(self.result);receipt['detached_deletions'][0]['attached_at_delete']=False
        with self.assertRaises(ValueError):validate_deletion_receipts(receipt,self.result.resource_maps['relationship_scenario_plan'])
