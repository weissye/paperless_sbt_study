"""Remove/add controls distinguish collision creation from removal defects."""
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from test_semantic_controls import generate, ROOT
from tools.semantic_receipts import validate_semantic_receipts

CASES = [resource+'-integer-'+mode for resource in ('food','unit') for mode in ('no-merge','one-merge')]

class RemovalControlTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Node is required.')
    def test_generated_controls_in_three_orders(self):
        for name in CASES:
            result = generate(name)
            again = generate(name)
            self.assertEqual(result.interfaces_js, again.interfaces_js)
            self.assertEqual(result.stories_js, again.stories_js)
            self.assertNotRegex(result.stories_js, r'\bsvc\.(get|post|put|patch|delete)\(')
            plan = result.resource_maps['relationship_scenario_plan']
            merge_count = sum(t['kind']=='semantic_merge' for t in plan['tasks'])
            self.assertEqual(merge_count, 0 if name.endswith('no-merge') else 1)
            with tempfile.TemporaryDirectory() as folder:
                p = Path(folder)
                (p/'interfaces.control.js').write_text(result.interfaces_js)
                (p/'stories.control.js').write_text(result.stories_js)
                (p/'relationship_scenario_plan.json').write_text(json.dumps(plan))
                for seed in (1,2,3):
                    run = subprocess.run(['node',str(ROOT/'tests/check_compiled_relationships.js'),folder,str(seed),''],capture_output=True,text=True)
                    self.assertEqual(run.returncode,0,name+run.stdout[-1000:]+run.stderr[-1000:])
                    receipt=json.loads(run.stdout)['receipt']
                    validate_semantic_receipts(receipt,plan)
                    for instance in plan['instances']['api/households/shopping/lists']:
                        state=receipt['semantic_tests'][-1]['expected'][instance]
                        self.assertAlmostEqual(sum(state['totals'].values()),7)
                        self.assertEqual(state['references'],{})
