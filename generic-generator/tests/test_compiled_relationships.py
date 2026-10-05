"""Acceptance boundaries for the additive generic relationship compiler."""
import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from generator_v56.pipeline import run_pipeline
from generator_v56.render.compiled_relationships import compile_relationships
from tools.relationship_execution import audit_samples, find_receipt, validate_negative_receipts


class CompiledRelationshipTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.profile = json.loads((ROOT / 'profiles/mealie-relational-map-pilot.json').read_text())
        cls.runtime = json.loads((ROOT / 'profiles/mealie-relational-runtime.json').read_text())
        cls.contract = str(ROOT / 'compatibility/contracts/mealie.json')
        cls.result = cls.generate()

    @classmethod
    def generate(cls, **options):
        args = dict(story_profile='parallel-crud', relationship_profile=cls.profile,
                    compile_relationship_model=True, relationship_runtime=cls.runtime)
        args.update(options)
        return run_pipeline(cls.contract, 'regression', 'http://127.0.0.1:9925', 2, **args)

    def test_compiled_plan_has_real_actors_and_interfaces(self):
        result = self.result
        plan = result.resource_maps['relationship_scenario_plan']
        report = result.resource_maps['relationship_compilation']
        self.assertEqual(len(plan['tasks']), 55)
        self.assertTrue(all(task['executable'] for task in plan['tasks']))
        self.assertEqual(report['http_requests_per_complete_schedule'], 170)
        self.assertEqual(report['symbolic_actor_count'], 21)
        self.assertFalse(report['live_accepted'])
        self.assertNotRegex(result.stories_js, r'\bsvc\s*\.\s*(?:get|post|put|patch|delete)\s*\(')
        self.assertIn('SBT:RelScenarioComplete', result.stories_js)
        self.assertIn('SBT_REL_LIVE_RECEIPT', result.interfaces_js)
        recipe = next(m for m in plan['instance_metadata'].values() if m['resource'] == 'api/recipes')
        self.assertEqual(recipe['route_fields'][0]['response_field'], 'slug')
        self.assertIn('id', recipe['identity_fields'])

    def test_compilation_is_deterministic_and_analysis_stays_opt_in(self):
        again = self.generate()
        self.assertEqual(self.result.stories_js, again.stories_js)
        self.assertEqual(self.result.interfaces_js, again.interfaces_js)
        legacy = self.generate(compile_relationship_model=False)
        plain = run_pipeline(self.contract, 'regression', 'http://127.0.0.1:9925', 2, story_profile='parallel-crud')
        self.assertEqual(legacy.stories_js, plain.stories_js)
        self.assertEqual(legacy.interfaces_js, plain.interfaces_js)
        self.assertEqual(legacy.generation_report, plain.generation_report)
        self.assertNotEqual(self.result.stories_js, plain.stories_js)

    def test_other_contract_is_rejected(self):
        runtime = copy.deepcopy(self.runtime)
        runtime['contract_sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'different contract'):
            self.generate(relationship_runtime=runtime)

    def test_recursive_policy_separates_acyclic_links_and_length_specific_probes(self):
        tasks = self.result.resource_maps['relationship_scenario_plan']['tasks']
        field = 'recipeIngredient[].referencedRecipe'
        positives = [t for t in tasks if t['kind'] == 'link' and t['field_path'] == field]
        negatives = [t for t in tasks if t['kind'] == 'negative_link']
        self.assertEqual({len(t['cycle_path']) for t in negatives}, {2, 3})
        edges = {t['source_instance']: t['target_instances'] for t in positives}
        for probe in negatives:
            path = probe['cycle_path']
            self.assertEqual(probe['target_instances'], [path[0]])
            self.assertEqual(probe['source_instance'], path[-1])
            for left, right in zip(path, path[1:]):
                self.assertEqual(edges[left], [right])
            self.assertNotIn(path[-1], edges)
            self.assertTrue({t['id'] for t in positives}.issubset(probe['after']))
        profile = copy.deepcopy(self.profile)
        profile['instances_per_type'] = 5
        profile['recursive_relationships'][0]['cycle_lengths'] = [2, 3, 5]
        analysis = self.generate(compile_relationship_model=False, relationship_profile=profile)
        self.assertEqual({len(t['cycle_path']) for t in analysis.resource_maps['relationship_scenario_plan']['tasks'] if t['kind'] == 'negative_link'}, {2, 3, 5})
        profile.pop('recursive_relationships')
        unqualified = self.generate(relationship_profile=profile)
        self.assertFalse(any(t['kind'] == 'negative_link' for t in unqualified.resource_maps['relationship_scenario_plan']['tasks']))

    def test_recursive_policy_requires_evidence_and_selected_relation(self):
        for field, value, message in [('evidence_sha256', '', 'evidence'), ('cycle_lengths', [2, 4], 'Cycle lengths'), ('verify_cycle_members', 'true', 'boolean'), ('field_path', 'invented', 'does not match'), ('rejection_codes', [500], 'client error')]:
            profile = copy.deepcopy(self.profile)
            profile['recursive_relationships'][0][field] = value
            with self.assertRaisesRegex(ValueError, message):
                self.generate(relationship_profile=profile)

    @unittest.skipUnless(shutil.which('node'), 'Node is required for the optional runtime stub.')
    def test_expanded_cycles_read_all_members_and_detect_target_mutations(self):
        profile = json.loads((ROOT / 'profiles/mealie-relational-cycle-expansion.json').read_text())
        result = self.generate(relationship_profile=profile)
        plan = result.resource_maps['relationship_scenario_plan']
        report = result.resource_maps['relationship_compilation']
        self.assertEqual(report['task_count'], 93)
        self.assertEqual(report['http_requests_per_complete_schedule'], 304)
        self.assertEqual(report['symbolic_actor_count'], 35)
        self.assertEqual({len(t['cycle_path']) for t in plan['tasks'] if t['kind'] == 'negative_link'}, {2, 3, 4, 5})
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary)
            (target / 'interfaces.regression.js').write_text(result.interfaces_js)
            (target / 'stories.regression.js').write_text(result.stories_js)
            (target / 'relationship_scenario_plan.json').write_text(json.dumps(plan))
            orders = []
            for seed, fault in [(11, ''), (22, ''), (33, ''), (11, 'cycle-target-mutates-on-reject'), (11, 'cycle-mutates-on-reject'), (11, 'cycle-accepted'), (11, 'cycle-500')]:
                process = subprocess.run([shutil.which('node'), str(ROOT / 'tests/check_compiled_relationships.js'), str(target), str(seed), fault], capture_output=True, text=True)
                self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
                if not fault:
                    outcome = json.loads(process.stdout)
                    self.assertEqual(outcome['http_requests'], 304)
                    orders.append(tuple(outcome['task_order']))
            self.assertEqual(len(set(orders)), 3)

    def test_expanded_receipts_require_unique_complete_member_checks(self):
        task = {'id': 'probe', 'kind': 'negative_link', 'cycle_path': ['A', 'B', 'C'], 'rejection_codes': [400], 'verify_cycle_members': True}
        record = {'task_id': 'probe', 'cycle_length': 3, 'code': 400, 'source_unchanged': True, 'all_members_unchanged': True, 'member_checks': [{'instance': member, 'unchanged': True} for member in task['cycle_path']]}
        validate_negative_receipts({'negative_tests': [record]}, {'tasks': [task]})
        for checks in [record['member_checks'][:-1], [record['member_checks'][0]] * 3, [{'instance': member, 'unchanged': member != 'B'} for member in task['cycle_path']]]:
            bad = copy.deepcopy(record)
            bad['member_checks'] = checks
            with self.assertRaisesRegex(ValueError, 'cycle member evidence'):
                validate_negative_receipts({'negative_tests': [bad]}, {'tasks': [task]})
        bad = copy.deepcopy(record)
        del bad['all_members_unchanged']
        with self.assertRaisesRegex(ValueError, 'cycle member evidence'):
            validate_negative_receipts({'negative_tests': [bad]}, {'tasks': [task]})

    def test_native_receipt_requires_both_rejection_and_unchanged_source(self):
        plan = self.result.resource_maps['relationship_scenario_plan']
        records = [{'task_id': t['id'], 'code': 400, 'source_unchanged': True, 'cycle_length': len(t['cycle_path'])} for t in plan['tasks'] if t['kind'] == 'negative_link']
        validate_negative_receipts({'negative_tests': records}, plan)
        for key, value in [('code', 200), ('source_unchanged', False), ('cycle_length', 99)]:
            wrong = copy.deepcopy(records)
            wrong[0][key] = value
            with self.assertRaisesRegex(ValueError, 'unqualified'):
                validate_negative_receipts({'negative_tests': wrong}, plan)
        with self.assertRaisesRegex(ValueError, 'complete'):
            validate_negative_receipts({}, plan)

    def test_undocumented_create_identity_requires_external_evidence(self):
        runtime = copy.deepcopy(self.runtime)
        del runtime['response_bindings']['POST /api/organizers/categories']
        with self.assertRaisesRegex(ValueError, 'observed response binding'):
            self.generate(relationship_runtime=runtime)

    def test_identity_views_validate_contract_paths_and_remain_explicit(self):
        for field, value, message in [('write_path', 'inventedId', 'Undocumented'), ('target_field', 'name', 'incompatible'), ('readback_path', 'inventedId', 'Undocumented')]:
            runtime = copy.deepcopy(self.runtime)
            runtime['relationship_identity_views'][0][field] = value
            with self.assertRaisesRegex(ValueError, message):
                self.generate(relationship_runtime=runtime)
        runtime = copy.deepcopy(self.runtime)
        del runtime['relationship_identity_views']
        result = self.generate(relationship_runtime=runtime)
        self.assertEqual(result.resource_maps['relationship_compilation']['configured_identity_views'], [])
        self.assertEqual(len(self.result.resource_maps['relationship_compilation']['configured_identity_views']), 2)
        runtime = copy.deepcopy(self.runtime)
        runtime['write_defaults']['PUT /api/households/shopping/items/{item_id}'] = [{'path': 'foodId', 'value': None}]
        with self.assertRaisesRegex(ValueError, 'conflicts'):
            self.generate(relationship_runtime=runtime)

    def test_collection_write_view_requires_documented_paths_and_matching_identity(self):
        for key, value, message in [('write_path', 'invented[]', 'Undocumented'), ('readback_path', 'invented[].recipeId', 'Undocumented'), ('target_field', 'name', 'incompatible'), ('item_identity_field', 'inventedId', 'incompatible'), ('evidence_sha256', '', 'evidence')]:
            runtime = copy.deepcopy(self.runtime)
            runtime['relationship_write_views'][0][key] = value
            with self.assertRaisesRegex(ValueError, message):
                self.generate(relationship_runtime=runtime)
        plan = self.result.resource_maps['relationship_scenario_plan']
        remapped = [t for t in plan['tasks'] if t.get('configured_write_view')]
        self.assertEqual(len(remapped), 3)
        self.assertTrue(all(t['field_path'] == 'referencedRecipe' and t['configured_write_view']['readback_path'] == 'recipeReferences[].recipeId' for t in remapped))

    def test_required_execution_cycle_is_rejected(self):
        maps = copy.deepcopy(self.result.resource_maps)
        # Use the original plan, before the additive action compilation.
        analysis = self.generate(compile_relationship_model=False)
        maps = copy.deepcopy(analysis.resource_maps)
        creates = [t for t in maps['relationship_scenario_plan']['tasks'] if t['kind'] == 'create']
        creates[0]['after'].append(creates[1]['id'])
        creates[1]['after'].append(creates[0]['id'])
        raw = json.loads(Path(self.contract).read_text())
        with self.assertRaisesRegex(ValueError, 'cycle'):
            compile_relationships(analysis.plan, maps, raw, self.runtime)

    def test_native_sample_audit_rejects_truncation_and_wrong_order(self):
        plan = {'tasks': [{'id': 'A', 'after': []}, {'id': 'B', 'after': ['A']}]}
        sample = [{'name': 'SBT:RelBootstrapDone'}]
        for task in ('A', 'B'):
            sample += [{'name': name, 'data': {'id': task}} for name in ('SBT:RelTask', 'SBT:RelTaskDone')]
        sample += [{'name': 'SBT:RelScenarioComplete', 'data': {'tasks': 2}}]
        self.assertEqual(audit_samples([sample], plan)['tasks_per_sample'], 2)
        with self.assertRaisesRegex(ValueError, 'Truncated'):
            audit_samples([sample[:-1]], plan)
        invalid = copy.deepcopy(sample)
        invalid[1]['data']['id'] = 'B'
        with self.assertRaisesRegex(ValueError, 'prerequisites'):
            audit_samples([invalid], plan)

    def test_receipt_must_be_observed_and_is_not_inferred_from_exit_code(self):
        self.assertIsNone(find_receipt('Exit code: 0'))
        receipt = {'status': 'LIVE_CALLBACKS_COMPLETE', 'task_count': 54}
        message = 'SBT_REL_LIVE_RECEIPT ' + json.dumps(receipt)
        self.assertEqual(find_receipt('INFO ' + message), receipt)
        self.assertEqual(find_receipt('', {'messages': [message]}), receipt)
        self.assertIsNone(find_receipt('SBT_REL_LIVE_RECEIPT invalid'))

    @unittest.skipUnless(shutil.which('node'), 'Node is required for the optional runtime stub.')
    def test_generated_schedules_and_fail_closed_callbacks_in_node_stub(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary)
            (target / 'interfaces.regression.js').write_text(self.result.interfaces_js)
            (target / 'stories.regression.js').write_text(self.result.stories_js)
            (target / 'relationship_scenario_plan.json').write_text(json.dumps(self.result.resource_maps['relationship_scenario_plan']))
            orders = []
            for seed, fault, missing in [(1, '', ''), (2, '', ''), (1, '', 'opaque-object'), (1, 'readback', ''), (1, 'identity-view', ''), (1, 'route-id', ''), (1, 'ambiguous-create', ''), (1, 'scope', ''), (1, 'cycle-accepted', ''), (1, 'cycle-mutates-on-reject', ''), (1, 'cycle-500', ''), (1, 'association-readback', ''), (1, 'projection-null', '')]:
                process = subprocess.run([shutil.which('node'), str(ROOT / 'tests/check_compiled_relationships.js'),
                                          str(target), str(seed), fault, missing], capture_output=True, text=True)
                self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
                if not fault:
                    report = json.loads(process.stdout)
                    self.assertEqual(report['tasks'], 55)
                    self.assertEqual(report['http_requests'], 170)
                    self.assertEqual(report['max_active_http'], 1)
                    orders.append(report['task_order'])
            self.assertNotEqual(orders[0], orders[1])
            self.assertEqual(orders[0], orders[2])
            # Reproduce the previous bug against the same FK-authoritative server.
            runtime = copy.deepcopy(self.runtime)
            del runtime['relationship_identity_views']
            previous = self.generate(relationship_runtime=runtime)
            (target / 'interfaces.regression.js').write_text(previous.interfaces_js)
            process = subprocess.run([shutil.which('node'), str(ROOT / 'tests/check_compiled_relationships.js'),
                                      str(target), '1', 'unsynchronized-view'], capture_output=True, text=True)
            self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
            runtime = copy.deepcopy(self.runtime)
            del runtime['relationship_write_views']
            previous = self.generate(relationship_runtime=runtime)
            (target / 'interfaces.regression.js').write_text(previous.interfaces_js)
            process = subprocess.run([shutil.which('node'), str(ROOT / 'tests/check_compiled_relationships.js'),
                                      str(target), '1', 'ignored-recipe-field'], capture_output=True, text=True)
            self.assertEqual(process.returncode, 0, process.stdout + process.stderr)


if __name__ == '__main__':
    unittest.main()
