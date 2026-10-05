"""Keep native evidence useful while excluding bulky replay payloads and tokens."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.relationship_execution import bundle, find_receipt, redact, failure_excerpt


class ExecutionReviewTests(unittest.TestCase):
    def test_first_failure_is_visible_despite_later_skipped_events(self):
        output = 'INFO preparation\nWARN FAIL: Relationship readback mismatch: food\n' + ('INFO skipped actuation\n' * 1000)
        self.assertIn('Relationship readback mismatch: food', failure_excerpt(output))
        self.assertLess(len(failure_excerpt(output)), 4001)

    def test_dumped_callback_source_is_not_a_runtime_failure(self):
        source = 'if(mismatch)fail("Relationship readback mismatch: "+JSON.stringify(evidence));'
        output = source + '\n12:00 WARN [RUN>TEST-1] FAIL: Semantic consistency mismatch: actual 20 expected 19\n'
        self.assertIn('actual 20 expected 19', failure_excerpt(output))

    def test_runtime_receipt_can_be_read_from_native_rtv_log(self):
        receipt = {'status': 'LIVE_CALLBACKS_COMPLETE', 'task_count': 54, 'response_count': 167}
        line = "INFO [RUN>TEST-1] RTV: setting 'sbt_rel_execution_receipt' to '" + json.dumps(receipt) + "'"
        self.assertEqual(find_receipt(line), receipt)
        self.assertIsNone(find_receipt('Test Result: SUCCESS'))

    def test_tokens_are_redacted_before_error_excerpt_is_truncated(self):
        token = 'A' * 40 + '.' + 'B' * 80 + '.' + 'C' * 50
        line = "RTV: setting 'sbt_rel_token' to '" + token + "'\nAuthorization: Bearer " + token
        output = redact(line)
        self.assertNotIn(token, output)
        self.assertNotIn('B' * 20, output[-50:])
        self.assertIn('<REDACTED_TOKEN>', output)
        opaque = "RTV: setting 'sbt_rel_token' to 'opaque-token-value'"
        self.assertNotIn('opaque-token-value', redact(opaque))

    def test_review_zip_excludes_serialized_samples_but_keeps_acceptance(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / 'project'
            (project / 'spec/js').mkdir(parents=True)
            review = project / 'execution-review'
            review.mkdir()
            (project / 'spec/js/interfaces.test.js').write_text('// model')
            (project / 'relationship-samples.json').write_text('[]')
            (project / 'relationship_compilation.json').write_text('{}')
            (review / 'selected-sample.json').write_text('[]')
            (review / 'native-result.json').write_text('{}')
            (review / 'run-acceptance.json').write_text('{}')
            destination = Path(temporary) / 'review.zip'
            bundle(project, list(review.glob('*')), destination)
            with zipfile.ZipFile(destination) as archive:
                files = archive.namelist()
                self.assertIn('execution-review/run-acceptance.json', files)
                self.assertIn('relationship_compilation.json', files)
                self.assertFalse(any(name.endswith(('selected-sample.json', 'relationship-samples.json', 'native-result.json')) for name in files))

    def test_password_and_encoded_form_remain_redacted(self):
        with patch.dict(os.environ, {'SBT_REL_PASSWORD': 'one & two'}):
            result = redact('password=one%20%26%20two&username=u; one & two')
            self.assertNotIn('one', result)


if __name__ == '__main__':
    unittest.main()
