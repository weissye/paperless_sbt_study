"""Require actual quantitative grouping collisions before accepting merge coverage."""
import copy
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from generator_v56.pipeline import run_pipeline
from tools.semantic_receipts import validate_semantic_receipts
ROOT=Path(__file__).resolve().parents[1]

class MergeCollisionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scope=json.loads((ROOT/'profiles/mealie-relational-collision-scope.json').read_text())
        cls.runtime=json.loads((ROOT/'profiles/mealie-relational-collision-runtime.json').read_text())
        cls.result=cls.generate()
    @classmethod
    def generate(cls,scope=None,runtime=None):
        return run_pipeline(str(ROOT/'compatibility/contracts/mealie.json'),'collision','http://127.0.0.1:9925',212,story_profile='parallel-crud',relationship_profile=scope or cls.scope,compile_relationship_model=True,relationship_runtime=runtime or cls.runtime)
    def replay(self,result,seed=1,fault=''):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            (root/'interfaces.collision.js').write_text(result.interfaces_js)
            (root/'stories.collision.js').write_text(result.stories_js)
            (root/'relationship_scenario_plan.json').write_text(json.dumps(result.resource_maps['relationship_scenario_plan']))
            run=subprocess.run(['node',str(ROOT/'tests/check_compiled_relationships.js'),folder,str(seed),fault],capture_output=True,text=True)
            self.assertEqual(run.returncode,0,run.stdout+run.stderr)
            return None if fault else json.loads(run.stdout)['receipt']
    def test_bindings_are_typed_deterministic_and_preserve_http_separation(self):
        again=self.generate();self.assertEqual(again.interfaces_js,self.result.interfaces_js)
        self.assertEqual(again.stories_js,self.result.stories_js)
        self.assertNotRegex(self.result.stories_js,r'\bsvc\.(get|post|put|patch|delete)\(')
        tasks=self.result.resource_maps['relationship_scenario_plan']['tasks']
        for t in [t for t in tasks if t.get('field_path')=='recipeIngredient[].unit']:
            self.assertEqual(t['target_instances'],['api/units#1'])
            food=next(x for x in tasks if x.get('source_instance')==t['source_instance'] and x.get('field_path')=='recipeIngredient[].food')
            self.assertIn(food['id'],t['after'])
    @unittest.skipUnless(shutil.which('node'),'Node is required for callback regression.')
    def test_three_orders_really_collapse_groups_and_preserve_manual_stock(self):
        plan=self.result.resource_maps['relationship_scenario_plan']
        for seed in [1,2,3]:
            receipt=self.replay(self.result,seed);validate_semantic_receipts(receipt,plan)
            merges=[r for r in receipt['semantic_tests'] if r['kind']=='semantic_merge']
            self.assertEqual([r['collision_groups'] for r in merges],[4,5])
            final=receipt['semantic_tests'][-1]['expected']
            for i in plan['instances']['api/households/shopping/lists']:
                self.assertEqual(sum(final[i]['totals'].values()),7)
                self.assertEqual(final[i]['references'],{})
    @unittest.skipUnless(shutil.which('node'),'Node is required for callback regression.')
    def test_lost_collision_item_and_forged_coverage_are_rejected(self):
        self.replay(self.result,fault='merge-collision-drops-item')
        self.replay(self.result,fault='remove-manual')
        receipt=self.replay(self.result)
        next(r for r in receipt['semantic_tests'] if r['kind']=='semantic_merge')['collision_groups']=999
        with self.assertRaisesRegex(ValueError,'collision coverage'):
            validate_semantic_receipts(receipt,self.result.resource_maps['relationship_scenario_plan'])
        scope=copy.deepcopy(self.scope);scope.pop('target_bindings')
        self.replay(self.generate(scope=scope),fault='missing-collision')
    def test_invalid_bindings_and_cyclic_prerequisites_are_rejected(self):
        for key,value in [('target_index',0),('target_type','api/foods'),('after_fields',['invented']),('source_type',[])]:
            scope=copy.deepcopy(self.scope);scope['target_bindings'][0][key]=value
            with self.assertRaises(ValueError):self.generate(scope=scope)
        runtime=copy.deepcopy(self.runtime);runtime['semantic_program']['require_merge_collision']='true'
        with self.assertRaises(ValueError):self.generate(runtime=runtime)
        scope=copy.deepcopy(self.scope)
        scope['target_bindings'].append({'source_type':'api/recipes','target_type':'api/foods','field_path':'recipeIngredient[].food','target_index':1,'after_fields':['recipeIngredient[].unit']})
        with self.assertRaisesRegex(ValueError,'cycle'):self.generate(scope=scope)
