"""Generic quantitative policy compilation and independent oracle regressions."""
import copy
import json
import shutil
from pathlib import Path
import subprocess
import tempfile
import unittest
from generator_v56.pipeline import run_pipeline
from tools.semantic_receipts import validate_semantic_receipts

ROOT = Path(__file__).resolve().parents[1]

class SemanticCampaignTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scope = json.loads((ROOT/'profiles/mealie-relational-semantic-scope.json').read_text())
        cls.results = {family: cls.generate(family) for family in ['merge','quantity','combined']}
    @classmethod
    def generate(cls, family, runtime=None, profile=None):
        return run_pipeline(str(ROOT/'compatibility/contracts/mealie.json'),'semantic','http://127.0.0.1:9925',209,story_profile='parallel-crud',relationship_profile=profile or cls.scope,compile_relationship_model=True,relationship_runtime=runtime or json.loads((ROOT/f'profiles/mealie-relational-{family}-runtime.json').read_text()))
    def replay(self, family, seed=1, fault=''):
        result = self.results[family]
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder)
            (p/'interfaces.semantic.js').write_text(result.interfaces_js)
            (p/'stories.semantic.js').write_text(result.stories_js)
            (p/'relationship_scenario_plan.json').write_text(json.dumps(result.resource_maps['relationship_scenario_plan']))
            response = subprocess.run(['node',str(ROOT/'tests/check_compiled_relationships.js'),folder,str(seed),fault],capture_output=True,text=True)
            self.assertEqual(response.returncode,0,response.stdout+response.stderr)
            return None if fault else json.loads(response.stdout)['receipt']
    def test_three_families_are_deterministic_and_separate_http(self):
        for family, result in self.results.items():
            again = self.generate(family)
            self.assertEqual(result.interfaces_js,again.interfaces_js)
            self.assertEqual(result.stories_js,again.stories_js)
            self.assertNotRegex(result.stories_js,r'\bsvc\.(get|post|put|patch|delete)\(')
            self.assertEqual(result.resource_maps['relationship_compilation']['http_requests_per_complete_schedule'],{'merge':147,'quantity':245,'combined':267}[family])
    @unittest.skipUnless(shutil.which("node"), "Node is required for optional callback regression.")
    def test_three_orders_preserve_manual_quantity_and_owned_merge_links(self):
        for family, result in self.results.items():
            for seed in [1,2,3]:
                receipt = self.replay(family,seed)
                plan = result.resource_maps['relationship_scenario_plan']
                validate_semantic_receipts(receipt,plan)
                if family != 'merge':
                    final = receipt['semantic_tests'][-1]['expected']
                    for i in plan['instances']['api/households/shopping/lists']:
                        self.assertEqual(sum(final[i]['totals'].values()),7)
                        self.assertEqual(final[i]['references'],{})
    @unittest.skipUnless(shutil.which("node"), "Node is required for optional callback regression.")
    def test_faults_are_rejected_before_completion(self):
        for fault in ['quantity-double','wrong-reference-quantity','remove-manual','merge-stale-list','merge-loses-quantity','merge-500']:
            self.replay('combined',fault=fault)
    @unittest.skipUnless(shutil.which("node"), "Node is required for optional callback regression.")
    def test_forged_matching_expected_and_observed_is_independently_rejected(self):
        receipt = self.replay('combined')
        plan = self.results['combined'].resource_maps['relationship_scenario_plan']
        forged = copy.deepcopy(receipt)
        record = forged['semantic_tests'][1]
        i = record['container'];k = next(iter(record['expected'][i]['totals']))
        record['expected'][i]['totals'][k] += 1
        for check in record['checks']:
            if check['instance']==i:check['observed']['totals'][k] += 1
        with self.assertRaisesRegex(ValueError,'Independent semantic quantity'):
            validate_semantic_receipts(forged,plan)
        for field, value in [('amount',999),('checks',[]),('reference_id','unowned')]:
            forged = copy.deepcopy(receipt);forged['semantic_tests'][1][field] = value
            with self.assertRaises(ValueError):validate_semantic_receipts(forged,plan)
        forged = copy.deepcopy(receipt);merge = next(r for r in forged['semantic_tests'] if r['kind']=='semantic_merge');merge['absence_code']=200
        with self.assertRaises(ValueError):validate_semantic_receipts(forged,plan)
    def test_undocumented_or_unrelated_operations_and_paths_are_rejected(self):
        base = json.loads((ROOT/'profiles/mealie-relational-combined-runtime.json').read_text())
        for section, field, value in [('merge','operation','PUT /api/units/merge'),('contribution','add_operation','POST /api/foods'),('container_measure','amount_path','invented')]:
            runtime = copy.deepcopy(base);runtime['semantic_program'][section][field]=value
            with self.assertRaises(ValueError):self.generate('combined',runtime=runtime)
        profile=copy.deepcopy(self.scope);profile['excluded_relationships'][0]['field_path']='invented'
        with self.assertRaises(ValueError):self.generate('combined',profile=profile)
        runtime=copy.deepcopy(base);runtime['create_defaults']['POST /api/foods']={'invented':1}
        with self.assertRaises(ValueError):self.generate('combined',runtime=runtime)
        runtime=copy.deepcopy(base);runtime['semantic_program']={}
        with self.assertRaises(ValueError):self.generate('combined',runtime=runtime)
        runtime=copy.deepcopy(base);runtime['shared_target_updates']=[{'unsupported':True}]
        with self.assertRaises(ValueError):self.generate('combined',runtime=runtime)
