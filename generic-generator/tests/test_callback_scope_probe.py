"""The native probe must stay bounded, complete, and read-only."""
import base64
import json
from pathlib import Path
import tempfile
import unittest
from tools.callback_scope_probe import inspect_sample, model_source

class CallbackScopeProbeTests(unittest.TestCase):
    def sample(self,blob=b'native-function',method='GET',complete=True):
        call={'name':'GET','data':{'lib':'REST','method':method,'url':'http://127.0.0.1:9925/openapi.json','callback':{'class':'org.mozilla.javascript.InterpretedFunction','object':base64.b64encode(blob).decode()}}}
        events=[call,call]
        if complete:events.append({'name':'SBT:ScopeProbeComplete'})
        return [events]

    def inspect(self,value):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'samples.json';p.write_text(json.dumps(value))
            return inspect_sample(p)

    def test_accepts_complete_read_only_native_probe(self):
        self.assertEqual(self.inspect(self.sample()),[15,15])

    def test_rejects_scope_leak_mutation_or_incomplete_sample(self):
        for value in [self.sample(b'GLOBAL_SCOPE_SENTINEL:'),self.sample(method='POST'),self.sample(complete=False)]:
            with self.assertRaises(ValueError):self.inspect(value)

    def test_generated_probe_is_two_gets_with_rtv_receipt(self):
        code=model_source('http://127.0.0.1:9925')
        self.assertEqual(code.count('svc.get('),2)
        self.assertNotRegex(code,r'svc\.(post|put|patch|delete)\(')
        self.assertIn('initStandardObjects',code)
        self.assertIn('compileFunction',code)
        self.assertIn('SBT_SCOPE_PROBE_NATIVE_PASS',code)

    def test_zero_exit_without_sample_is_rejected_before_http(self):
        from unittest.mock import patch
        from types import SimpleNamespace
        from tools.callback_scope_probe import main
        with tempfile.TemporaryDirectory() as folder:
            review=Path(folder)/'review.zip'
            args=['probe','--root',folder,'--review-zip',str(review)]
            with patch('sys.argv',args), patch('tools.callback_scope_probe.native',return_value=SimpleNamespace(returncode=0,stdout='sampling error',stderr='')) as native:
                self.assertEqual(main(),1)
                self.assertEqual(native.call_count,1)
                self.assertEqual(native.call_args.args[0][0],'sample')
            self.assertTrue(review.exists())

    def test_only_baseline_can_capture_sentinel(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'samples.json'
            p.write_text(json.dumps(self.sample(b'GLOBAL_SCOPE_SENTINEL:')))
            self.assertEqual(inspect_sample(p,False),[22,22])
            with self.assertRaises(ValueError):inspect_sample(p)

    def test_outside_variant_prepares_callbacks_before_bthread(self):
        code=model_source('http://127.0.0.1:9925','outside')
        self.assertLess(code.index('var preparedCallbacks='),code.index('bthread('))
        self.assertEqual(code.count('svc.get('),2)
        self.assertIn('SCOPE_STAGE: standard scope',code)
