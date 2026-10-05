import copy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from generator_v56.render.credential_auth import validate_credential_auth
from tools.relationship_execution import redact, secret_values

class CredentialAuthTests(unittest.TestCase):
    def setUp(self):
        self.raw = json.loads((ROOT.parent / 'model/paperless-openapi.json').read_text())
        self.policy = json.loads((ROOT.parent / 'profiles/paperless-native-runtime.json').read_text())['authentication']
    def test_declared_token_binding(self):
        self.assertEqual(validate_credential_auth(self.raw, self.policy)['header'], 'Authorization')
    def test_undocumented_token_rejected(self):
        self.policy['token_field'] = 'guessed_token'
        with self.assertRaisesRegex(ValueError, 'token field'): validate_credential_auth(self.raw, self.policy)
    def test_nonheader_scheme_rejected(self):
        self.policy['security_scheme'] = 'cookieAuth'
        with self.assertRaisesRegex(ValueError, 'header apiKey'): validate_credential_auth(self.raw, self.policy)
    def test_required_extra_credential_rejected(self):
        self.raw['components']['schemas']['PaperlessAuthTokenRequest']['required'].append('code')
        with self.assertRaisesRegex(ValueError, 'other required fields'): validate_credential_auth(self.raw, self.policy)
    def test_literal_secret_header_rejected(self):
        self.policy['headers']['Authorization'] = 'Token SECRET'
        with self.assertRaisesRegex(ValueError, 'static noncredential'): validate_credential_auth(self.raw, self.policy)
    def test_new_token_redaction(self):
        token = 'a' * 40
        value = {'token': token, 'auth_token': token, 'nested': 'Token ' + token}
        self.assertNotIn(token, json.dumps(redact(value)))
        self.assertEqual(len(list(secret_values(value))), 2)

if __name__ == '__main__': unittest.main()
