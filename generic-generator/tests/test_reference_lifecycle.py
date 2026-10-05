"""Matched deletion/control programs, independent receipts and injected faults."""
import copy
import json
from pathlib import Path
import unittest
import test_compiled_relationships as compiled
import test_alternate_paths as alternate
from tools.reference_receipts import validate_reference_receipts

ROOT=Path(__file__).resolve().parents[1]
class ReferenceLifecycleTests(unittest.TestCase):
    execute=alternate.AlternatePathTests.execute
    @classmethod
    def setUpClass(cls):compiled.CompiledRelationshipTests.setUpClass()
    def generate(self,resource='food',mode='delete',edit=None):
        name='mealie-reference-'+resource+'-'+mode
        profile=json.loads((ROOT/'profiles'/(name+'-scope.json')).read_text())
        runtime=json.loads((ROOT/'profiles'/(name+'-runtime.json')).read_text())
        if edit:edit(runtime['reference_lifecycle'])
        return compiled.CompiledRelationshipTests.generate(relationship_profile=profile,relationship_runtime=runtime)
    def test_four_profiles_three_orders_and_post_delete_construction(self):
        for resource in ['food','unit']:
            for mode in ['control','delete']:
                result=self.generate(resource,mode);plan=result.resource_maps['relationship_scenario_plan']
                probe=next(t for t in plan['tasks'] if t['kind']=='reference_lifecycle')
                self.assertNotRegex(result.stories_js,r'\bsvc\.')
                for seed in [11,22,33]:
                    observed=self.execute(result,seed);receipt=observed['receipt'];validate_reference_receipts(receipt,plan)
                    order=observed['task_order'];position=order.index(probe['id'])
                    self.assertLess(order.index(probe['prefix_action']),position)
                    self.assertTrue(all(order.index(t)>position for t in probe['deferred_actions']))
                    self.assertEqual(observed['http_requests'],100+(mode=='delete'))
    def test_healthy_rejection_and_five_semantic_faults(self):
        for resource in ['food','unit']:
            result=self.generate(resource)
            # The test stub treats this variant as a healthy alternate server policy.
            self.execute(result,11,'reference-reject')
            for fault in ['reference-dangling','reference-unrelated','reference-reject-partial','reference-followup-ignored','reference-rebind-ignored']:
                self.execute(result,11,fault)
    def test_previous_display_oracle_fails_on_healthy_rebinding(self):
        result=self.generate(edit=lambda r:r.pop('derived_fields'))
        self.execute(result,11,'derived-display-legacy')

    def test_configuration_is_strict(self):
        changes=[lambda r:r.update(target_index=True),lambda r:r.update(replacement_index=1),lambda r:r.update(rejection_codes=[500]),lambda r:r.update(preserve_fields=[]),lambda r:r.update(field_path='invented'),lambda r:r.update(mode='automatic'),lambda r:r.update(derived_fields=['recipeIngredient[].quantity'])]
        for change in changes:
            with self.assertRaises(ValueError):self.generate(edit=change)
    def test_receipt_cannot_omit_baselines_controls_or_followup(self):
        result=self.generate();plan=result.resource_maps['relationship_scenario_plan'];receipt=self.execute(result)['receipt']
        for change in [lambda r:r.pop('reference_lifecycles'),lambda r:r['reference_lifecycles'][0]['checks'].pop(),lambda r:r['reference_lifecycles'][0]['followups'].pop(),lambda r:r['reference_lifecycles'][0].update(target_checked=False),lambda r:r['reference_lifecycles'][0]['checks'][0]['before'].clear()]:
            forged=copy.deepcopy(receipt);change(forged)
            with self.assertRaises(ValueError):validate_reference_receipts(forged,plan)
    def test_no_option_keeps_legacy_js_byte_identical(self):
        # Compare the new compiler to the saved pre-change module, not a second call to itself.
        import importlib.util,sys
        before=ROOT/'compatibility/reference-baseline/compiled_relationships.py'
        if not before.exists():self.skipTest('Baseline source is only present in release validation workspace.')
        name='generator_v56.render._reference_before';spec=importlib.util.spec_from_file_location(name,before);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        import generator_v56.render.compiled_relationships as pipeline
        actual=compiled.CompiledRelationshipTests.generate()
        old=pipeline.compile_relationships
        try:
            pipeline.compile_relationships=module.compile_relationships
            previous=compiled.CompiledRelationshipTests.generate()
        finally:pipeline.compile_relationships=old
        self.assertEqual(actual.interfaces_js,previous.interfaces_js);self.assertEqual(actual.stories_js,previous.stories_js);self.assertEqual(actual.generation_report,previous.generation_report)

import os,shutil,socket,subprocess,tempfile
from generator_v56.pipeline import run_pipeline
from tools.relationship_execution import audit_samples,find_receipt

@unittest.skipUnless(os.environ.get('PROVENGO_TEST_JAR') and shutil.which('java'), 'Native Provengo jar is required.')
class NativeReferenceLifecycleTests(ReferenceLifecycleTests):
    # Avoid rerunning the inherited stub test matrix in this class.
    test_four_profiles_three_orders_and_post_delete_construction=None
    test_healthy_rejection_and_five_semantic_faults=None
    test_previous_display_oracle_fails_on_healthy_rebinding=None
    test_configuration_is_strict=None
    test_receipt_cannot_omit_baselines_controls_or_followup=None
    test_no_option_keeps_legacy_js_byte_identical=None
    def test_native_compact_serialized_callbacks_and_policies(self):
        jar=str(Path(os.environ['PROVENGO_TEST_JAR']).resolve())
        for resource in ['food','unit']:
            for mode in ['control','delete']:
                with tempfile.TemporaryDirectory() as folder:
                    project=Path(folder);name='mealie-reference-'+resource+'-'+mode
                    with socket.socket() as probe:probe.bind(('127.0.0.1',0));port=probe.getsockname()[1]
                    result=run_pipeline(str(ROOT/'compatibility/contracts/mealie.json'),'native','http://127.0.0.1:'+str(port),217,story_profile='parallel-crud',compile_relationship_model=True,relationship_profile=json.loads((ROOT/'profiles'/(name+'-scope.json')).read_text()),relationship_runtime=json.loads((ROOT/'profiles'/(name+'-runtime.json')).read_text()))
                    (project/'spec/js').mkdir(parents=True);(project/'config').mkdir();(project/'config/provengo.yml').write_text('version: 2\n')
                    (project/'spec/js/interfaces.native.js').write_text(result.interfaces_js);(project/'spec/js/stories.native.js').write_text(result.stories_js)
                    plan=result.resource_maps['relationship_scenario_plan'];(project/'relationship_scenario_plan.json').write_text(json.dumps(plan))
                    command=['java','-Xmx512m','-jar',jar]
                    sample=subprocess.run(command+['sample','--size','2','--max-length','500','-o','samples.json',str(project)],capture_output=True,text=True,timeout=60)
                    self.assertEqual(sample.returncode,0,sample.stdout+sample.stderr)
                    samples=json.loads((project/'samples.json').read_text());audit_samples(samples,plan);self.assertLess((project/'samples.json').stat().st_size,4*1024*1024)
                    faults=['','']+(['reference-reject','reference-dangling','reference-reject-partial','reference-followup-ignored','reference-rebind-ignored'] if mode=='delete' else [])
                    for index,fault in enumerate(faults):
                        env=dict(os.environ,NATIVE_MOCK_PORT=str(port),NATIVE_MOCK_FAULT=fault,SBT_REL_USERNAME='local',SBT_REL_PASSWORD='local')
                        server=subprocess.Popen(['node',str(ROOT/'tests/native_http_mock.js'),str(project)],env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
                        try:
                            self.assertEqual(server.stdout.readline().strip(),'READY')
                            run=subprocess.run(command+['--batch-mode','run','--run-source','samples.json','--run-id',str(2 if index==1 else 1),str(project)],env=env,capture_output=True,text=True,timeout=60)
                            output=run.stdout+run.stderr;receipt=find_receipt(output)
                            if fault and fault!='reference-reject':self.assertNotEqual(run.returncode,0,resource+' '+mode+' '+fault);self.assertIsNone(receipt)
                            else:
                                self.assertEqual(run.returncode,0,'\n'.join(line for line in output.splitlines() if any(w in line for w in ['WARN [','ERR [','Exception'])))
                                validate_reference_receipts(receipt,plan)
                                self.assertEqual(receipt['response_count'],result.resource_maps['relationship_compilation']['http_requests_per_complete_schedule'])
                        finally:server.terminate();server.communicate(timeout=10)

class ReferenceReviewTests(unittest.TestCase):
    def test_read_only_classifier_accepts_observed_completion_and_rejects_auth(self):
        import zipfile
        from tools.classify_reference_review import classify
        test=ReferenceLifecycleTests();ReferenceLifecycleTests.setUpClass();result=test.generate();receipt=test.execute(result)['receipt'];plan=result.resource_maps['relationship_scenario_plan']
        with tempfile.TemporaryDirectory() as folder:
            for accepted,message,status in [(True,'','PASS'),(False,'WARN [RUN] FAIL: Reference lifecycle mismatch: {"stage":"post_delete"}.','REFERENCE_CANDIDATE'),(False,'WARN [RUN] FAIL: Unexpected HTTP 401','BLOCKED')]:
                path=Path(folder)/'review.zip'
                with zipfile.ZipFile(path,'w') as archive:
                    archive.writestr('execution-review/run-acceptance.json',json.dumps({'live_accepted':accepted,'runtime_receipt':receipt}))
                    archive.writestr('execution-review/run-output.txt',message)
                    archive.writestr('relationship_scenario_plan.json',json.dumps(plan))
                # Native logging includes a space before WARN; reproduce that shape.
                if message.startswith('WARN'):
                    with zipfile.ZipFile(path,'w') as archive:
                        archive.writestr('execution-review/run-acceptance.json',json.dumps({'live_accepted':accepted,'runtime_receipt':receipt}));archive.writestr('execution-review/run-output.txt',' '+message);archive.writestr('relationship_scenario_plan.json',json.dumps(plan))
                self.assertEqual(classify(path)['status'],status)
