"""Alternate paths and compact serialized callbacks are additive generic options."""
import copy
import hashlib
from tools.relationship_execution import digest
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
import test_compiled_relationships as compiled

ROOT=Path(__file__).resolve().parents[1]

class AlternatePathTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiled.CompiledRelationshipTests.setUpClass()
        cls.profile=json.loads((ROOT/'profiles/mealie-relational-alternate-paths.json').read_text())
        cls.runtime=json.loads((ROOT/'profiles/mealie-relational-compact-runtime.json').read_text())
        cls.result=compiled.CompiledRelationshipTests.generate(relationship_profile=cls.profile,relationship_runtime=cls.runtime)

    def execute(self,result,seed=11,fault=''):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            (root/'interfaces.regression.js').write_text(result.interfaces_js)
            (root/'stories.regression.js').write_text(result.stories_js)
            (root/'relationship_scenario_plan.json').write_text(json.dumps(result.resource_maps['relationship_scenario_plan']))
            run=subprocess.run(['node',str(ROOT/'tests/check_compiled_relationships.js'),str(root),str(seed),fault],text=True,capture_output=True)
            self.assertEqual(run.returncode,0,run.stdout+run.stderr)
            return json.loads(run.stdout) if not fault else None

    def test_serialized_callbacks_and_alternate_paths(self):
        report=self.result.resource_maps['relationship_compilation']
        self.assertEqual(report['task_count'],109)
        for seed in [11,22,33]:
            evidence=self.execute(self.result,seed)
            self.assertEqual(evidence['http_requests'],report['http_requests_per_complete_schedule'])
            self.assertLess(evidence['serialized_callback_bytes'],20*1024*1024)
        for fault in ['alternate-path-ignored','alternate-unlink-ignored','legal-rejected','cycle-target-mutates-on-reject']:
            self.execute(self.result,11,fault)

    def test_compaction_reduces_size_without_changing_http_or_task_order(self):
        legacy_runtime=copy.deepcopy(self.runtime);legacy_runtime.pop('compact_callbacks')
        legacy=compiled.CompiledRelationshipTests.generate(relationship_profile=self.profile,relationship_runtime=legacy_runtime)
        old=self.execute(legacy);new=self.execute(self.result)
        self.assertEqual(old['task_order'],new['task_order'])
        self.assertEqual(old['http_requests'],new['http_requests'])
        self.assertLess(new['serialized_callback_bytes'],old['serialized_callback_bytes']/10)
        print('Callback serialization bytes:',old['serialized_callback_bytes'],'->',new['serialized_callback_bytes'])

    def test_streaming_hash_keeps_existing_checksum(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'large.bin'
            data=b'contract-and-sample-hash'*100000
            path.write_bytes(data)
            self.assertEqual(digest(path),hashlib.sha256(data).hexdigest())

    def test_new_options_are_strict_and_opt_in(self):
        profile=copy.deepcopy(self.profile);profile['recursive_relationships'][0]['alternate_paths']='true'
        with self.assertRaisesRegex(ValueError,'boolean'):
            compiled.CompiledRelationshipTests.generate(relationship_profile=profile)
        runtime=copy.deepcopy(self.runtime);runtime['compact_callbacks']='true'
        with self.assertRaisesRegex(ValueError,'boolean'):
            compiled.CompiledRelationshipTests.generate(relationship_runtime=runtime)
        plain=compiled.CompiledRelationshipTests.generate()
        self.assertNotIn('sbt_rel_schema_registry',plain.interfaces_js)
        self.assertNotRegex(self.result.stories_js,r'\bsvc\.')
