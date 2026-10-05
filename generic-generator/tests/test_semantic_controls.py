"""Opt-in controlled sequences and repeated target occurrences."""
import copy
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from generator_v56.pipeline import run_pipeline
from tools.semantic_receipts import validate_semantic_receipts

ROOT = Path(__file__).resolve().parents[1]
CASES = ['duplicate-no-merge', 'merge-no-decrement', 'single-ingredient', 'three-ingredient', 'chain-readd', 'food-integer-lifecycle', 'unit-integer-lifecycle']

def generate(name, scope=None, runtime=None):
    return run_pipeline(str(ROOT/'compatibility/contracts/mealie.json'), 'control', 'http://127.0.0.1:9925', 213,
        story_profile='parallel-crud', compile_relationship_model=True,
        relationship_profile=scope or json.loads((ROOT/f'profiles/mealie-control-{name}-scope.json').read_text()),
        relationship_runtime=runtime or json.loads((ROOT/f'profiles/mealie-control-{name}-runtime.json').read_text()))

class SemanticControlTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Node callback regression requires Node.')
    def test_all_controls_in_three_orders_have_independently_validated_receipts(self):
        for name in CASES:
            result = generate(name)
            again = generate(name)
            self.assertEqual(result.interfaces_js, again.interfaces_js)
            self.assertEqual(result.stories_js, again.stories_js)
            self.assertNotRegex(result.stories_js, r'\bsvc\.(get|post|put|patch|delete)\(')
            plan = result.resource_maps['relationship_scenario_plan']
            with tempfile.TemporaryDirectory() as folder:
                p = Path(folder)
                (p/'interfaces.control.js').write_text(result.interfaces_js)
                (p/'stories.control.js').write_text(result.stories_js)
                (p/'relationship_scenario_plan.json').write_text(json.dumps(plan))
                for seed in [1,2,3]:
                    run = subprocess.run(['node', str(ROOT/'tests/check_compiled_relationships.js'), folder, str(seed), ''], capture_output=True, text=True)
                    self.assertEqual(run.returncode, 0, name + run.stdout[-1000:] + run.stderr[-1000:])
                    receipt = json.loads(run.stdout)['receipt']
                    validate_semantic_receipts(receipt, plan)
                    if name != 'merge-no-decrement':
                        for instance in plan['instances']['api/households/shopping/lists']:
                            final = receipt['semantic_tests'][-1]['expected'][instance]
                            self.assertAlmostEqual(sum(final['totals'].values()), 7)
                            self.assertEqual(final['references'], {})

    def test_invalid_phases_and_occurrences_are_rejected_before_requests(self):
        name = 'duplicate-no-merge'
        original = json.loads((ROOT/f'profiles/mealie-control-{name}-runtime.json').read_text())
        bad = [None,[], [{'kind':'unknown'}], [{'kind':'contribution','amount':-1,'offset':0}],
            [{'kind':'contribution','amount':float('nan'),'offset':0}],
            [{'kind':'merge','from_index':1,'to_index':1}],
            [{'kind':'merge','from_index':1,'to_index':2},{'kind':'merge','from_index':1,'to_index':3}]]
        for phases in bad:
            runtime = copy.deepcopy(original); runtime['semantic_program']['phases'] = phases
            with self.assertRaises(ValueError): generate(name, runtime=runtime)
        original_scope = json.loads((ROOT/f'profiles/mealie-control-{name}-scope.json').read_text())
        for indices in [[], [0], [True], [4], '1', [1]*9]:
            scope = copy.deepcopy(original_scope); scope['target_bindings'][-1]['target_indices'] = indices
            with self.assertRaises(ValueError): generate(name, scope=scope)

    def test_unknown_phase_keys_are_rejected(self):
        runtime = json.loads((ROOT/'profiles/mealie-control-single-ingredient-runtime.json').read_text())
        runtime['semantic_program']['phases'][0]['unexpected'] = True
        with self.assertRaises(ValueError): generate('single-ingredient', runtime=runtime)
