"""Embedded value consistency and detach/delete oracles are additive generic options."""
import copy
import json
from pathlib import Path
import unittest
import test_compiled_relationships as compiled
import test_alternate_paths as alternate
from tools.relationship_execution import validate_shared_update_receipts, validate_deletion_receipts

ROOT=Path(__file__).resolve().parents[1]

class ConsistencyTests(unittest.TestCase):
    execute=alternate.AlternatePathTests.execute

    @classmethod
    def setUpClass(cls):
        compiled.CompiledRelationshipTests.setUpClass()
        cls.profile=json.loads((ROOT/'profiles/mealie-relational-alternate-paths.json').read_text())
        cls.runtime=json.loads((ROOT/'profiles/mealie-relational-consistency-runtime.json').read_text())
        cls.result=compiled.CompiledRelationshipTests.generate(relationship_profile=cls.profile,relationship_runtime=cls.runtime)

    def test_complete_plan_checks_embedded_values_and_deletion_controls(self):
        plan=self.result.resource_maps['relationship_scenario_plan']
        deletions=[t for t in plan['tasks'] if t['kind']=='detached_delete']
        self.assertEqual(len(deletions),10)
        self.assertEqual(len(plan['tasks']),129)
        for task in deletions:
            self.assertEqual(len(task['checks']),5)
            self.assertEqual(sum(c['detached'] for c in task['checks']),2)
            self.assertTrue(all(c['protected_fields'] for c in task['checks']))
        mutation_orders = []
        for seed in [11,22,33]:
            result=self.execute(self.result,seed)
            self.assertEqual(result['http_requests'],self.result.resource_maps['relationship_compilation']['http_requests_per_complete_schedule'])
            validate_shared_update_receipts(result,plan)
            validate_deletion_receipts(result,plan)
            mutation_orders.append(tuple(t for t in result['task_order'] if t.startswith(('shared-update:', 'detached-delete:'))))
        self.assertEqual(len(set(mutation_orders)),3)
        self.assertNotRegex(self.result.stories_js,r'\bsvc\.')

    def test_stale_view_and_deletion_faults_prevent_acceptance(self):
        for fault in ['embedded-stale','delete-ignored','delete-unrelated-links','delete-cascades-source']:
            self.execute(self.result,11,fault)

    def test_incomplete_and_forged_evidence_is_rejected(self):
        result=self.execute(self.result);plan=self.result.resource_maps['relationship_scenario_plan']
        receipt=copy.deepcopy(result);receipt['shared_updates'][0]['referrers'][0]['embedded_values']=[]
        with self.assertRaises(ValueError):validate_shared_update_receipts(receipt,plan)
        for fault in ['absence','missing-control','duplicate','protected-change','dangling-reference']:
            receipt=copy.deepcopy(result);entry=receipt['detached_deletions'][0]
            if fault=='absence':entry['absence_code']=200
            elif fault=='missing-control':entry['checks'].pop()
            elif fault=='duplicate':entry['checks'][-1]=copy.deepcopy(entry['checks'][0])
            elif fault=='protected-change':entry['checks'][0]['protected_after']={}
            else:entry['checks'][0]['after'].append(entry['target_id'])
            with self.assertRaises(ValueError):validate_deletion_receipts(receipt,plan)

    def test_opt_in_and_contract_boundaries(self):
        for modify in ['bool','operation','absence','unselected','unsupported-path']:
            runtime=copy.deepcopy(self.runtime)
            if modify=='bool':runtime['shared_target_updates'][0]['verify_embedded_value']='true'
            elif modify=='operation':runtime['detached_target_deletions'][0]['operation']='DELETE /api/foods/{item_id}'
            elif modify=='absence':runtime['detached_target_deletions'][0]['absent_codes']=[200]
            elif modify=='unselected':runtime['detached_target_deletions'][0]['resource_type']='unselected'
            else:runtime['detached_target_deletions'][0]={'resource_type':'api/foods','operation':'DELETE /api/foods/{item_id}','absent_codes':[404]}
            with self.assertRaises(ValueError):compiled.CompiledRelationshipTests.generate(relationship_profile=self.profile,relationship_runtime=runtime)
