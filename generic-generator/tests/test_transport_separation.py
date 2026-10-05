"""Regression checks against the preserved pre-change generator source."""
import dataclasses
import importlib
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from generator_v56.pipeline import run_pipeline
from generator_v56.render.http_interfaces import HttpInterfaceRegistry

PROFILES = ['full', 'minimal-smoke', 'validated-lifecycle', 'validated-action-lifecycle',
            'validated-relation-lifecycle', 'relation-kind-campaign',
            'interleaved-relational-lifecycle', 'interleaved-relational-exploration',
            'multi-resource-interleaving', 'multi-resource-verified-obligations',
            'multi-resource-verified-resources', 'long-interleaving',
            'concurrency-breadth', 'parallel-crud']

def before_pipeline(directory):
    target = Path(directory) / 'generator_before'
    shutil.copytree(ROOT / 'generator_v56', target, ignore=shutil.ignore_patterns('__pycache__'))
    for name in ['pipeline.py', 'parallel_crud_v3.py', 'stories_js.py']:
        destination = target / name if name == 'pipeline.py' else target / 'render' / name
        shutil.copyfile(ROOT / 'compatibility/baseline' / name, destination)
    sys.path.insert(0, str(directory))
    return importlib.import_module('generator_before.pipeline').run_pipeline

class SeparationRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.before = staticmethod(before_pipeline(cls.temp.name))

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def assert_equivalent(self, source, profile, **kwargs):
        arguments = dict(openapi_path=str(source), name='regression', base_url='http://127.0.0.1:9925', seed=2,
                         story_profile=profile, **kwargs)
        before = self.before(**arguments)
        after = run_pipeline(**arguments)
        self.assertEqual(dataclasses.asdict(before.plan), dataclasses.asdict(after.plan))
        self.assertEqual(before.generation_report, after.generation_report)
        self.assertEqual(before.dependency_graph_report, after.dependency_graph_report)
        self.assertEqual(before.unsupported_refs, after.unsupported_refs)
        self.assertTrue(after.interfaces_js.startswith(before.interfaces_js))
        self.assertNotRegex(after.stories_js, r'\bsvc\s*\.\s*(get|post|put|patch|delete|head|options)\s*\(')
        registry = HttpInterfaceRegistry(); registry.entries = after.transport_manifest
        self.assertEqual(before.stories_js, registry.restore_legacy_story(after.stories_js))
        if not after.transport_manifest:
            self.assertEqual(before.interfaces_js, after.interfaces_js)
            self.assertEqual(before.stories_js, after.stories_js)
        return after

    def contracts(self):
        return sorted((ROOT / 'compatibility/contracts').glob('*.json'))

    def test_all_existing_cli_profiles_preserve_plan_reports_and_model_source(self):
        for source in self.contracts():
            for profile in PROFILES:
                with self.subTest(contract=source.name, profile=profile):
                    self.assert_equivalent(source, profile)

    def test_multiple_logical_workers_and_instances_preserve_binding_and_cleanup(self):
        for source in self.contracts():
            with self.subTest(contract=source.name):
                result = self.assert_equivalent(source, 'parallel-crud', logical_processes=2, instances_per_entity=2)
                self.assertTrue(result.transport_manifest)
                self.assertIn('SBT:ParentsBound', result.stories_js)

    def test_configured_request_rules_and_auth_environment_remain_compatible(self):
        source = ROOT / 'compatibility/contracts/keycloak.json'
        rules = ROOT / 'compatibility/keycloak-rules.json'
        if not source.exists() or not rules.exists():
            self.skipTest('Keycloak compatibility inputs are not present.')
        result = self.assert_equivalent(source, 'parallel-crud', overrides=json.loads(rules.read_text()), auth_token_env='SBT_ACCESS_TOKEN')
        self.assertTrue(result.transport_manifest)

    def test_prefix_observation_is_lifted_without_changing_caller_state(self):
        for source in self.contracts():
            with self.subTest(contract=source.name):
                self.assert_equivalent(source, 'long-interleaving', long_rounds=(2, 2), emit_prefix_witnesses=True)

    def test_repeated_generation_is_deterministic(self):
        source = self.contracts()[0]
        arguments = dict(openapi_path=str(source), name='regression', base_url='http://127.0.0.1:9925', seed=2, story_profile='parallel-crud')
        first = run_pipeline(**arguments); second = run_pipeline(**arguments)
        self.assertEqual(first.interfaces_js, second.interfaces_js)
        self.assertEqual(first.stories_js, second.stories_js)
        self.assertEqual(first.transport_manifest, second.transport_manifest)

if __name__ == '__main__':
    unittest.main()
