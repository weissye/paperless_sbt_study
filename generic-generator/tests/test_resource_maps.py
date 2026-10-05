"""Resource inference must preserve evidence boundaries and legacy generation."""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from generator_v56.pipeline import run_pipeline
from generator_v56.inference.resource_maps import build_resource_maps, schema_cycles


class ResourceMapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = run_pipeline(str(ROOT / 'compatibility/contracts/mealie.json'), 'regression',
                                  'http://127.0.0.1:9925', 2, story_profile='parallel-crud',
                                  include_resource_maps=True)
        cls.maps = cls.result.resource_maps

    def test_explicit_nested_food_unit_and_recipe_links_are_retained(self):
        templates = self.maps['relationship_map']['templates']
        triples = {(r['source'], r['field_path'], r['target']) for r in templates
                   if r['rule'] == 'explicit_schema_reference'}
        self.assertIn(('api/recipes', 'recipeIngredient[].food', 'api/foods'), triples)
        self.assertIn(('api/recipes', 'recipeIngredient[].unit', 'api/units'), triples)
        self.assertIn(('schema:RecipeIngredient', 'referencedRecipe', 'api/recipes'), triples)
        self.assertIn(('api/households/shopping/lists', 'recipeReferences[].recipe', 'api/recipes'), triples)
        self.assertTrue(all(not r['runtime_fact'] for r in templates))

    def test_tag_lookup_aliases_share_type_and_keep_wire_identity_views(self):
        catalog = self.maps['resource_catalog']
        aliases = {r['alias']: r['canonical'] for r in catalog['entity_aliases']}
        self.assertEqual(aliases['api/organizers/tags/slug'], 'api/organizers/tags')
        self.assertTrue(all(r['alias'] != r['canonical'] for r in catalog['entity_aliases']))
        tags = next(r for r in catalog['resources'] if r['type'] == 'api/organizers/tags')
        identities = {x['field']: x['wire_types'] for x in tags['identity_slots']}
        self.assertIn({'type': 'string', 'format': 'uuid4'}, identities['id'])
        self.assertIn({'type': 'string', 'format': None}, identities['slug'])
        self.assertEqual(catalog['instance_bindings'], [])

    def test_recursive_views_are_not_flattened_into_creation_prerequisites(self):
        resources = self.maps['resource_catalog']['resources']
        ingredient = next(r for r in resources if r['type'] == 'schema:RecipeIngredient')
        self.assertEqual(ingredient['schema_views'], ['RecipeIngredient-Input', 'RecipeIngredient-Output'])
        self.assertEqual(len(self.maps['relationship_map']['schema_cycles']), 2)
        self.assertIn('legacy execution dependencies unchanged', self.maps['relationship_map']['planning_status'])
        self.assertEqual(schema_cycles({'A': {'$ref': '#/components/schemas/B'},
                                        'B': {'$ref': '#/components/schemas/A'}}), [['A', 'B']])

    def test_equal_schema_and_uuid_shape_do_not_merge_unrelated_families(self):
        from types import SimpleNamespace
        def entity(key):
            path = '/' + key + '/{id}'
            op = SimpleNamespace(path=path, method='GET')
            return SimpleNamespace(entity=SimpleNamespace(key=key, collection_path='/' + key,
                    item_path=path), ops=[SimpleNamespace(op=op, kind='get')])
        spec = {'components': {'schemas': {'Common': {'type': 'object', 'properties': {
                'id': {'type': 'string', 'format': 'uuid'}}}}}, 'paths': {}}
        for key in ('alpha', 'beta'):
            spec['paths']['/' + key + '/{id}'] = {'get': {'responses': {'200': {'content': {
                'application/json': {'schema': {'$ref': '#/components/schemas/Common'}}}}}}}
        result = build_resource_maps(spec, SimpleNamespace(entities=[entity('alpha'), entity('beta')]))
        self.assertEqual(result['resource_catalog']['entity_aliases'], [])
        self.assertEqual(result['resource_catalog']['instance_bindings'], [])

    def test_optional_analysis_keeps_generated_files_and_reports_identical(self):
        for name in ('keycloak', 'mealie'):
            with self.subTest(contract=name):
                args = (str(ROOT / ('compatibility/contracts/' + name + '.json')), 'regression',
                        'http://127.0.0.1:9925', 2)
                before = run_pipeline(*args, story_profile='parallel-crud')
                after = run_pipeline(*args, story_profile='parallel-crud', include_resource_maps=True)
                self.assertEqual(before.interfaces_js, after.interfaces_js)
                self.assertEqual(before.stories_js, after.stories_js)
                self.assertEqual(before.generation_report, after.generation_report)
                self.assertEqual(before.dependency_graph_report, after.dependency_graph_report)
                self.assertEqual(len(after.resource_maps['operation_map']['operations']), len(after.doc.operations))
                self.assertEqual(before.resource_maps, {})

    def test_name_based_links_remain_candidates_and_analysis_is_deterministic(self):
        templates = self.maps['relationship_map']['templates']
        named = [r for r in templates if r['rule'] == 'identifier_name_candidate']
        self.assertTrue(named)
        self.assertTrue(all(r['execution_role'] == 'unclassified' for r in named))
        other = run_pipeline(str(ROOT / 'compatibility/contracts/mealie.json'), 'regression',
                              'http://127.0.0.1:9925', 2, story_profile='parallel-crud', include_resource_maps=True)
        self.assertEqual(json.dumps(self.maps, sort_keys=True), json.dumps(other.resource_maps, sort_keys=True))

    def test_relationship_plan_reuses_instances_and_defers_recursive_links(self):
        from generator_v56.render.relationship_blueprint import build_relationship_blueprint
        profile = json.loads((ROOT / 'profiles/mealie-relational-map-pilot.json').read_text())
        # Retain the original unqualified relationship planning behavior.
        profile.pop('recursive_relationships', None)
        blueprint = build_relationship_blueprint(self.result.plan, self.maps, profile)
        self.assertEqual(sum(map(len, blueprint['instances'].values())), 21)
        links = [t for t in blueprint['tasks'] if t['kind'] == 'link']
        self.assertEqual(len(links), 27)
        food_links = [t for t in links if t['field_path'] == 'recipeIngredient[].food']
        self.assertEqual(len(set(food_links[0]['target_instances']) & set(food_links[1]['target_instances'])), 1)
        self.assertEqual(len(food_links[0]['target_instances']), 2)
        recursive = [t for t in links if t['field_path'] == 'recipeIngredient[].referencedRecipe']
        self.assertTrue(recursive)
        self.assertTrue(all(all(p.startswith('create:') for p in t['after']) for t in recursive))
        self.assertTrue(all(t['source_instance'] not in t['target_instances'] for t in recursive))
        contained = [t for t in links if t['field_path'] == 'listItems[]']
        self.assertTrue(all(len(t['target_instances']) == 1 for t in contained))
        self.assertEqual(len({t['target_instances'][0] for t in contained}), 3)
        self.assertTrue(all(not t['executable'] for t in blueprint['tasks']))
        self.assertIn('POST /api/households/shopping/lists/{item_id}/recipe/{recipe_id}',
                      [a['operation'] for a in blueprint['action_candidates']])

    def test_foreign_path_identity_is_not_mistaken_for_owning_resource(self):
        rows = self.maps['operation_map']['operations']
        row = next(r for r in rows if r['operation'] == 'POST /api/households/shopping/lists/{item_id}/recipe/{recipe_id}')
        slots = {s['name']: s for s in row['path_slots']}
        self.assertEqual(slots['item_id']['business_type'], 'api/households/shopping/lists')
        self.assertEqual(slots['recipe_id']['business_type'], 'api/recipes')
        self.assertEqual(slots['recipe_id']['evidence'], 'identifier_name_and_response_relation_candidate')


if __name__ == '__main__':
    unittest.main()
