"""A source-code dump or authentication failure is not a semantic finding."""
import json
import tempfile
import unittest
from pathlib import Path
import zipfile
from tools.classify_control_review import classify

class ControlReviewTests(unittest.TestCase):
    def review(self, output, accepted=False):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'review.zip'
            with zipfile.ZipFile(path, 'w') as archive:
                archive.writestr('execution-review/run-acceptance.json', json.dumps({'live_accepted': accepted, 'error': 'Test failure'}))
                archive.writestr('execution-review/run-output.txt', output)
            result = classify(path)
            self.assertEqual(len(result['sha256']),64)
            self.assertFalse(result['new_bug_confirmed'])
            return result

    def test_authentication_and_callback_source_are_blocked(self):
        for output in ['WARN FAIL: actual 401, expected 200', "function check(){fail('Semantic consistency mismatch: '+JSON.stringify(evidence));}"]:
            self.assertEqual(self.review(output)['status'],'BLOCKED')

    def test_only_actual_semantic_warning_is_a_candidate(self):
        data={'instance':'list#1','expected':{'totals':{'key':19}},'observed':{'totals':{'key':20}}}
        result=self.review('12:00 WARN [RUN>TEST-1] FAIL: Semantic consistency mismatch: '+json.dumps(data)+'.')
        self.assertEqual(result['status'],'SEMANTIC_CANDIDATE')
        self.assertEqual(result['first_failure'],data)
        self.assertEqual(self.review('INFO Test Result: SUCCESS',True)['status'],'PASS')
