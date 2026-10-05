"""Read-only audit: sample completeness, foreign server and protected state."""
import copy
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from tools.audit_route_state import load_campaign, queries_for, render, classify, inspect_samples, receipt_from
from tools import audit_route_state

ROOT = Path(__file__).resolve().parents[1]
CAMPAIGN = Path(os.environ.get('ROUTE_AUDIT_TEST_CAMPAIGN', str(ROOT.parent / 'evidence/route-identity-20261004-231327/campaign-original.zip')))


@unittest.skipUnless(CAMPAIGN.is_file(), 'Preserved route campaign required')
class RouteStateAuditTests(unittest.TestCase):
    def setUp(self):
        self.plan = load_campaign(CAMPAIGN, ROOT / 'compatibility/contracts/mealie.json')
        self.queries = queries_for(self.plan)
        self.version = 'v3.28.0'

    def healthy(self):
        entries = [dict(index=-2, code=200, body={'version': self.version}),
                   dict(index=-1, code=200, body={'id': self.plan['cases'][0]['record']['pending']['before']['userId']})]
        for q in self.queries:
            case = self.plan['cases'][q['case_index']]
            rec = case['record']
            if q['kind'] == 'requested':
                entries.append(dict(index=q['index'], code=404, body={'detail': 'not found'}))
                continue
            if q['instance'] in case['task']['targets']:
                body = copy.deepcopy(rec['initial_targets'][q['expected_id']])
            else:
                body = copy.deepcopy(rec['baselines'][q['instance']])
                body['id'] = q['expected_id']
            entries.append(dict(index=q['index'], code=200, body=body))
        return dict(status='READ_ONLY_CALLBACKS_COMPLETE', observations=entries)

    def test_all_six_original_hashes_controls_and_queries(self):
        self.assertEqual(len(self.plan['controls']), 2)
        self.assertEqual(len(self.queries), 28)
        self.assertEqual(len({q['path'] for q in self.queries}), 28)
        result = classify(self.plan, self.queries, self.healthy(), self.version)
        self.assertEqual({r['status'] for r in result['cases']}, {'DIRECT_SLUG_IGNORED_STATE_PRESERVED'})

    def test_missing_resources_are_not_bug_evidence(self):
        receipt = self.healthy()
        for item in receipt['observations']:
            if item['index'] >= 0:
                item.update(code=404, body={'detail': 'not found'})
        result = classify(self.plan, self.queries, receipt, self.version)
        self.assertEqual(result['status'], 'ORIGINAL_RESOURCES_UNAVAILABLE')
        self.assertFalse(result['new_bug_confirmed'])

    def test_recorded_child_replacement_and_updated_views_are_accepted(self):
        receipt = self.healthy()
        identity = self.plan['cases'][0]['record']['ids'][0]
        new_id = '22222222-2222-4222-8222-222222222222'
        def hydrate(node):
            if isinstance(node, dict):
                if node.get('id') == identity:
                    for key in ('dateUpdated', 'updatedAt'):
                        if key in node:node[key] = '2026-10-05T03:45:01.123456Z'
                    if 'recipeInstructions' in node:node['recipeInstructions'][0]['id'] = new_id
                for child in node.values():hydrate(child)
            elif isinstance(node, list):
                for child in node:hydrate(child)
        for entry in receipt['observations']:
            hydrate(entry['body'])
        result = classify(self.plan, self.queries, receipt, self.version)
        self.assertEqual(result['cases'][0]['status'], 'DIRECT_SLUG_IGNORED_STATE_PRESERVED')
        self.assertEqual(result['cases'][0]['child_identity_replacements'][0]['after'], new_id)

    def test_quantity_identity_name_and_new_alias_changes_are_not_hidden(self):
        for fault in ('quantity', 'identity', 'name', 'alias', 'other_time', 'instruction_text'):
            receipt = self.healthy()
            q = next(q for q in self.queries if q['case_index'] == 0 and q['instance'] == self.plan['cases'][0]['task']['targets'][0] and q['kind'] == 'original')
            entry = next(e for e in receipt['observations'] if e['index'] == q['index'])
            if fault == 'quantity':entry['body']['recipeIngredient'][0]['quantity'] = 999
            elif fault == 'identity':entry['body']['id'] = '11111111-1111-4111-8111-111111111111'
            elif fault == 'name':entry['body']['name'] = 'unexpected'
            elif fault == 'instruction_text':entry['body']['recipeInstructions'][0]['text'] = 'corrupted'
            elif fault == 'other_time':
                other = next(q for q in self.queries if q['case_index'] == 0 and q['instance'] == self.plan['cases'][0]['task']['targets'][2])
                next(e for e in receipt['observations'] if e['index'] == other['index'])['body']['updatedAt'] = '2026-10-06T00:00:00Z'
            else:
                requested = next(q for q in self.queries if q['case_index'] == 0 and q['kind'] == 'requested')
                next(e for e in receipt['observations'] if e['index'] == requested['index']).update(code=200, body=entry['body'])
            result = classify(self.plan, self.queries, receipt, self.version)
            self.assertEqual(result['cases'][0]['status'], 'STATE_DISCREPANCY_REQUIRES_QUALIFICATION', fault)

    def test_incomplete_or_duplicate_receipt_is_rejected(self):
        receipt = self.healthy();receipt['observations'].pop()
        with self.assertRaises(ValueError):classify(self.plan, self.queries, receipt, self.version)
        receipt = self.healthy();receipt['observations'][-1] = receipt['observations'][0]
        with self.assertRaises(ValueError):classify(self.plan, self.queries, receipt, self.version)

    @unittest.skipUnless(os.environ.get('PROVENGO_TEST_JAR'), 'Native jar required')
    def test_native_read_only_present_and_foreign_server(self):
        jar = str(Path(os.environ['PROVENGO_TEST_JAR']).resolve())
        expected = self.healthy()
        mapping = {q['path']: next(e for e in expected['observations'] if e['index'] == q['index']) for q in self.queries}
        owner = expected['observations'][1]['body']
        calls = []
        state = {'missing': False}
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):pass
            def respond(self, code, body):
                value = json.dumps(body).encode();self.send_response(code);self.send_header('Content-Type', 'application/json');self.send_header('Content-Length', str(len(value)));self.end_headers();self.wfile.write(value)
            def do_POST(self):
                calls.append(('POST', self.path));self.rfile.read(int(self.headers.get('Content-Length', 0)))
                if self.path != '/api/auth/token':return self.respond(500, {})
                self.respond(200, dict(access_token='local-test-token', token_type='bearer'))
            def do_GET(self):
                calls.append(('GET', self.path))
                if self.path == '/openapi.json':return self.respond(200, {'info': {'version': 'v3.28.0'}})
                if self.path == '/api/users/self':return self.respond(200, owner)
                if state['missing']:return self.respond(404, {'detail': 'not found'})
                entry = mapping[self.path];self.respond(entry['code'], entry['body'])
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True);thread.start()
        try:
            with tempfile.TemporaryDirectory() as temp:
                project = Path(temp) / 'project'
                render(project, self.queries, f'http://127.0.0.1:{server.server_port}')
                self.assertNotIn('auditSvc.', (project / 'spec/js/stories.route-audit.js').read_text())
                command = ['java', '-Xmx512m', '-jar', jar]
                sample = subprocess.run(command + ['sample', '--size', '1', '--max-length', '40', '-o', 'samples.json', str(project)], capture_output=True, text=True, timeout=60)
                self.assertEqual(sample.returncode, 0, sample.stdout[-1000:] + sample.stderr[-1000:])
                samples = json.loads((project / 'samples.json').read_text());inspect_samples(samples)
                truncated = copy.deepcopy(samples);truncated[0].pop()
                # Removing a REST request, rather than a terminal scheduler marker, must fail.
                truncated = [[e for e in samples[0] if (e.get('data') or {}).get('url') != self.queries[-1]['path'] and not (e.get('data') or {}).get('url', '').endswith(self.queries[-1]['path'])]]
                with self.assertRaises(ValueError):inspect_samples(truncated)
                for missing in (False, True):
                    state['missing'] = missing;calls.clear()
                    env = dict(os.environ, SBT_REL_USERNAME='local', SBT_REL_PASSWORD='local')
                    run = subprocess.run(command + ['--batch-mode', 'run', '--run-source', 'samples.json', '--run-id', '1', str(project)], env=env, capture_output=True, text=True, timeout=60)
                    self.assertEqual(run.returncode, 0, run.stdout[-1500:] + run.stderr[-1500:])
                    receipt = receipt_from(run.stdout + run.stderr)
                    result = classify(self.plan, self.queries, receipt, self.version)
                    self.assertEqual(result['status'], 'ORIGINAL_RESOURCES_UNAVAILABLE' if missing else 'READ_ONLY_STATE_AUDIT_COMPLETE')
                    self.assertEqual(len(calls), 31)
                    self.assertEqual(sum(method == 'POST' for method, path in calls), 1)
                    self.assertEqual({path for method, path in calls if method == 'POST'}, {'/api/auth/token'})
                study = Path(temp) / 'study'
                contract = study / 'generic-generator/compatibility/contracts/mealie.json'
                contract.parent.mkdir(parents=True)
                contract.write_bytes((ROOT / 'compatibility/contracts/mealie.json').read_bytes())
                def launch(args, path):
                    return subprocess.run(command + args + [str(path)], capture_output=True, text=True, timeout=60)
                argv = ['audit', '--root', str(study), '--campaign', str(CAMPAIGN.resolve()),
                        '--expected-sha256', hashlib.sha256(CAMPAIGN.read_bytes()).hexdigest(),
                        '--base-url', f'http://127.0.0.1:{server.server_port}']
                state['missing'] = True;calls.clear();console = io.StringIO()
                with patch('sys.argv', argv), patch.object(audit_route_state, 'native', launch), patch.object(Path, 'home', return_value=Path(temp)), patch.dict(os.environ, SBT_REL_USERNAME='local', SBT_REL_PASSWORD='AUDIT_SECRET_CHECK_123'), contextlib.redirect_stdout(console):
                    self.assertEqual(audit_route_state.main(), 0)
                self.assertEqual(len(calls), 31)
                self.assertNotIn('AUDIT_SECRET_CHECK_123', console.getvalue())
                reports = list((study / 'provengo').glob('*/audit-report.json'))
                self.assertEqual(json.loads(reports[0].read_text())['status'], 'ORIGINAL_RESOURCES_UNAVAILABLE')
                audit_log = (reports[0].parent / 'run-output.txt').read_text()
                self.assertNotIn('AUDIT_SECRET_CHECK_123', audit_log)
                self.assertNotIn("setting 'audit_token' to 'local-test-token'", audit_log)
                self.assertEqual(len(list((Path(temp) / 'Downloads').glob('*.zip'))), 1)
                calls.clear();argv[argv.index('--expected-sha256') + 1] = '0' * 64
                with patch('sys.argv', argv), patch.object(audit_route_state, 'native', launch), patch.object(Path, 'home', return_value=Path(temp)), contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(audit_route_state.main(), 1)
                self.assertEqual(calls, [])
        finally:
            server.shutdown();server.server_close();thread.join(timeout=5)


if __name__ == '__main__':unittest.main()
