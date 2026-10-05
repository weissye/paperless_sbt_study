"""Test wire comparisons and the authentication-only relay against a local stub."""
import contextlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.request
import urllib.parse
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from diagnose_native_auth import inspect_form, main


class AuthDiagnosticTests(unittest.TestCase):
    def test_special_characters_are_compared_after_form_decoding(self):
        password = 's e+&%é!'
        body = urllib.parse.urlencode({'username': 'a@example.com', 'password': password,
                                     'grant_type': 'password'}).encode()
        result = inspect_form(body, ['application/x-www-form-urlencoded'], 'a@example.com', password)
        self.assertTrue(result['username_matches_input'])
        self.assertTrue(result['password_matches_input'])
        self.assertTrue(result['grant_type_is_password'])
        self.assertNotIn(password, json.dumps(result))

    def test_json_wrapped_form_is_detected(self):
        body = json.dumps('grant_type=password&username=user&password=secret').encode()
        result = inspect_form(body, ['application/x-www-form-urlencoded'], 'user', 'secret')
        self.assertTrue(result['body_is_json_string'])
        self.assertFalse(result['password_matches_input'])

    def test_real_local_relay_forwards_only_auth_and_archive_has_no_secrets(self):
        username, password = 'user@example.com', 'private &+%value'
        requests = []

        class Target(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                body = self.rfile.read(int(self.headers['Content-Length']))
                values = urllib.parse.parse_qs(body.decode())
                requests.append((self.path, self.headers.get_all('Content-Type'), values))
                good = values.get('username') == [username] and values.get('password') == [password]
                reply = b'{"access_token":"PRIVATE_FAKE_TOKEN","token_type":"bearer"}' if good else b'{}'
                self.send_response(200 if good else 401)
                self.send_header('Content-Length', str(len(reply)))
                self.end_headers()
                self.wfile.write(reply)

        target = ThreadingHTTPServer(('127.0.0.1', 0), Target)
        thread = threading.Thread(target=target.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                spec = root / 'contract.json'
                spec.write_text(json.dumps({'components': {'securitySchemes': {'oauth': {'flows': {
                    'password': {'tokenUrl': '/token'}}}}}}))
                review = root / 'review.zip'

                def fake_native(command, project):
                    if command[0] == 'sample':
                        return subprocess.CompletedProcess([], 0, '', '')
                    source = (project / 'spec/js/interfaces.auth.js').read_text()
                    import re
                    url = json.loads(re.search(r'new RESTSession\(("[^"]+")', source).group(1)) + '/token'
                    body = urllib.parse.urlencode({'username': username, 'password': password, 'grant_type': 'password'}).encode()
                    with urllib.request.urlopen(urllib.request.Request(url, data=body,
                            headers={'Content-Type': 'application/x-www-form-urlencoded'})) as response:
                        self.assertEqual(response.status, 200)
                    return subprocess.CompletedProcess([], 0, 'password=' + urllib.parse.quote_plus(password), '')

                argv = ['diagnose', '--root', str(root), '--openapi', str(spec), '--base-url',
                        'http://127.0.0.1:' + str(target.server_port), '--review-zip', str(review)]
                with patch.dict(os.environ, {'SBT_REL_USERNAME': username, 'SBT_REL_PASSWORD': password}), \
                     patch('sys.argv', argv), patch('diagnose_native_auth.native', side_effect=fake_native), \
                     contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(main(), 0)
                with zipfile.ZipFile(review) as archive:
                    report = json.loads(archive.read('auth-diagnostic.json'))
                    self.assertEqual(report['direct_http_status'], 200)
                    wire = report['native_wire_requests'][0]
                    self.assertTrue(wire['password_matches_input'])
                    self.assertEqual(wire['forwarded_http_status'], 200)
                    for name in archive.namelist():
                        text = archive.read(name).decode()
                        self.assertNotIn(password, text)
                        self.assertNotIn(urllib.parse.quote_plus(password), text)
                        self.assertNotIn('PRIVATE_FAKE_TOKEN', text)
                self.assertEqual(len(requests), 2)
                self.assertTrue(all(item[0] == '/token' for item in requests))
        finally:
            target.shutdown()
            target.server_close()
            thread.join(timeout=2)


if __name__ == '__main__':
    unittest.main()
