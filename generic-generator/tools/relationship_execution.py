"""Native Provengo sampling/replay with explicit symbolic and runtime evidence."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import zipfile


def digest(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def failure_excerpt(output):
    """Prefer the first actual runtime failure over later skipped actuation."""
    safe = redact(output)
    lines = safe.splitlines()
    for index, line in enumerate(lines):
        if re.search(r'\b(?:WARN|ERR|ERROR)\b.*\b(?:FAIL:|ERROR:|Relationship readback mismatch:)', line):
            return '\n'.join(lines[max(0, index - 2):index + 4])[:4000]
    return safe[-4000:]


def audit_samples(samples, plan):
    if not isinstance(samples, list) or not samples:
        raise ValueError('A nonempty native sample array is required.')
    tasks = {t['id']: t for t in plan['tasks']}
    orders = []
    for sample in samples:
        if not isinstance(sample, list):
            raise ValueError('Unsupported native sample format.')
        boot = False
        active = None
        done = set()
        order = []
        complete = 0
        for event in sample:
            name = event.get('name')
            data = event.get('data') or {}
            if name == 'SBT:RelBootstrapDone':
                if boot:
                    raise ValueError('Duplicate bootstrap completion.')
                boot = True
            elif name == 'SBT:RelTask':
                task = data.get('id')
                if not boot or active is not None or task not in tasks or task in done:
                    raise ValueError('Invalid task admission in native sample.')
                if not set(tasks[task]['after']).issubset(done):
                    raise ValueError('Native sample violates task prerequisites.')
                active = task
                order.append(task)
            elif name == 'SBT:RelTaskDone':
                if active is None or data.get('id') != active:
                    raise ValueError('Native sample completes an unowned task.')
                done.add(active)
                active = None
            elif name == 'SBT:RelScenarioComplete':
                if active is not None or done != set(tasks) or data.get('tasks') != len(tasks):
                    raise ValueError('Native scenario completion is incomplete.')
                complete += 1
        if not boot or active is not None or done != set(tasks) or complete != 1:
            raise ValueError('Truncated native sample; no complete scenario was observed.')
        orders.append(order)
    return {'status': 'NATIVE_SYMBOLIC_SAMPLES_COMPLETE', 'sample_count': len(orders),
            'distinct_task_orders': len({tuple(x) for x in orders}), 'tasks_per_sample': len(tasks),
            'task_orders': orders, 'server_requests_sent': 0, 'live_accepted': False}


def strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from strings(item)


def find_receipt(text, structured=None):
    candidates = [text] + list(strings(structured))
    decoder = json.JSONDecoder()
    for candidate in candidates:
        for match in re.finditer(r"(?:SBT_REL_LIVE_RECEIPT\s+|setting\s+'sbt_rel_execution_receipt'\s+to\s+')(\{)", candidate):
            try:
                receipt, _ = decoder.raw_decode(candidate[match.start(1):])
            except ValueError:
                continue
            if isinstance(receipt, dict) and receipt.get('status') == 'LIVE_CALLBACKS_COMPLETE':
                return receipt
    return None


if __package__:
    from .semantic_receipts import validate_semantic_receipts
    from .reference_receipts import validate_reference_receipts
    from .transfer_receipts import validate_transfer_receipts
    from .route_receipts import validate_route_receipts
    from .copy_receipts import validate_copy_receipts
    from .identity_receipts import validate_identity_receipts
else:
    from semantic_receipts import validate_semantic_receipts
    from reference_receipts import validate_reference_receipts
    from transfer_receipts import validate_transfer_receipts
    from route_receipts import validate_route_receipts
    from copy_receipts import validate_copy_receipts
    from identity_receipts import validate_identity_receipts

def validate_negative_receipts(receipt, plan):
    expected = {t['id']: t for t in plan['tasks'] if t['kind'] == 'negative_link'}
    records = receipt.get('negative_tests', [])
    if not isinstance(records, list) or len(records) != len(expected):
        raise ValueError('Native receipt lacks complete negative relationship verification.')
    seen = set()
    for record in records:
        if not isinstance(record, dict):
            raise ValueError('Invalid negative relationship receipt.')
        task = expected.get(record.get('task_id'))
        if not task or record['task_id'] in seen or record.get('source_unchanged') is not True or record.get('code') not in task['rejection_codes'] or record.get('cycle_length') != len(task['cycle_path']):
            raise ValueError('Negative receipt has an unqualified status, state change or cycle length.')
        if task.get('verify_cycle_members'):
            checks = record.get('member_checks')
            if record.get('all_members_unchanged') is not True or not isinstance(checks, list) or len(checks) != len(task['cycle_path']) or any(not isinstance(check, dict) or check.get('unchanged') is not True or not isinstance(check.get('instance'), str) for check in checks) or sorted(check['instance'] for check in checks) != sorted(task['cycle_path']):
                raise ValueError('Negative receipt lacks complete unchanged cycle member evidence.')
        seen.add(record['task_id'])


def validate_legal_receipts(receipt, plan):
    expected = {t['id']: t for t in plan['tasks'] if t.get('legal_readback') and t['kind'] != 'negative_link'}
    if not expected:
        return
    records = receipt.get('legal_tests', [])
    if not isinstance(records, list) or len(records) != len(expected):
        raise ValueError('Native receipt lacks complete legal relationship readbacks.')
    seen = set()
    for record in records:
        task = expected.get(record.get('task_id')) if isinstance(record, dict) else None
        if not task or task['id'] in seen or record.get('source_readback') is not True or sorted(record.get('targets_read', [])) != sorted(task['target_instances']):
            raise ValueError('Legal relationship receipt lacks source or target readback.')
        observed, identities = record.get('observed'), record.get('expected')
        if not isinstance(observed, list) or not isinstance(identities, list) or len(identities) != len(task['target_instances']) or any(value is None or value not in observed for value in identities) or (task['kind'] == 'unlink' and observed):
            raise ValueError('Legal relationship receipt has an invalid relationship state.')
        seen.add(task['id'])


def validate_shared_update_receipts(receipt, plan):
    expected = {t['id']: t for t in plan['tasks'] if t['kind'] == 'shared_update'}
    if not expected:
        return
    records = receipt.get('shared_updates', [])
    if not isinstance(records, list) or len(records) != len(expected):
        raise ValueError('Native receipt lacks complete shared update readbacks.')
    seen = set()
    for record in records:
        task = expected.get(record.get('task_id')) if isinstance(record, dict) else None
        if not task or task['id'] in seen or record.get('target') != task['source_instance'] or record.get('field') != task['field'] or record.get('target_readback') is not True or not isinstance(record.get('expected'), str) or not record['expected'].endswith('-' + task['value'] + '-' + task['source_instance'].split('#')[-1]) or record.get('before') == record.get('expected'):
            raise ValueError('Invalid shared target update receipt.')
        checks = record.get('referrers', [])
        if not isinstance(checks, list) or len(checks) != len(task['referrers']):
            raise ValueError('Incomplete shared referrer readbacks.')
        observed = []
        for check in checks:
            if not isinstance(check, dict) or check.get('identities_preserved') is not True or not isinstance(check.get('before'), list) or not isinstance(check.get('after'), list) or sorted(check['before']) != sorted(check['after']) or record.get('target_id') is None or record['target_id'] not in check['before']:
                raise ValueError('Shared referrer identities were not preserved.')
            reference = next((r for r in task['referrers'] if r['instance'] == check.get('instance') and r['field_path'] == check.get('field_path')), None)
            if reference and reference.get('object_path'):
                values = check.get('embedded_values')
                if check.get('object_path') != reference['object_path'] or check.get('value_field') != reference['value_field'] or not isinstance(values, list) or not values or len(values) != check['before'].count(record['target_id']) or any(v != record['expected'] for v in values):
                    raise ValueError('Shared update lacks fresh embedded value readbacks.')
            observed.append((check.get('instance'), check.get('field_path')))
        if sorted(observed) != sorted((r['instance'], r['field_path']) for r in task['referrers']):
            raise ValueError('Wrong shared referrers in native receipt.')
        seen.add(task['id'])


def validate_deletion_receipts(receipt, plan):
    expected = {t['id']: t for t in plan['tasks'] if t['kind'] in ('detached_delete', 'attached_delete')}
    if not expected:
        return
    records = receipt.get('detached_deletions', [])
    if not isinstance(records, list) or len(records) != len(expected):
        raise ValueError('Incomplete detached deletion receipts.')
    seen = set()
    for record in records:
        task = expected.get(record.get('task_id')) if isinstance(record, dict) else None
        if not task or task['id'] in seen or record.get('target') != task['source_instance'] or record.get('target_id') is None or record.get('target_deleted') is not True or record.get('absence_code') not in task['absent_codes']:
            raise ValueError('Invalid deletion absence receipt.')
        if task['kind'] == 'attached_delete' and record.get('attached_at_delete') is not True:
            raise ValueError('Deletion while attached was not explicitly observed.')
        checks = record.get('checks', [])
        if not isinstance(checks, list) or len(checks) != len(task['checks']):
            raise ValueError('Incomplete deletion source/control checks.')
        observed = []
        for check in checks:
            source = next((c for c in task['checks'] if c['instance'] == check.get('instance')), None) if isinstance(check, dict) else None
            if not source or check.get('field_path') != source['field_path'] or check.get('detached') is not source['detached'] or not isinstance(check.get('before'), list) or not isinstance(check.get('after'), list):
                raise ValueError('Invalid deletion source/control check.')
            wanted = sorted(v for v in check['before'] if not source['detached'] or v != record['target_id'])
            if (record['target_id'] in check['before']) != source['detached'] or sorted(check['after']) != wanted or check.get('expected') != wanted or check.get('other_relationships_preserved') is not True or not isinstance(check.get('protected_before'), dict) or check['protected_before'] != check.get('protected_after') or sorted(check['protected_before']) != sorted(source['protected_fields']):
                raise ValueError('Deletion left a reference or changed unrelated bindings.')
            observed.append(check['instance'])
        if sorted(observed) != sorted(c['instance'] for c in task['checks']):
            raise ValueError('Duplicate or missing deletion source/control check.')
        seen.add(task['id'])


def redact(value):
    if isinstance(value, dict):
        return {key: '<REDACTED>' if key.lower() in ('password', 'access_token', 'refresh_token', 'token', 'auth_token', 'authorization')
                else redact(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, str):
        from urllib.parse import quote, quote_plus
        secrets = {v for k,v in os.environ.items() if k == 'SBT_REL_PASSWORD' or (k.startswith('SBT_IDP_') and k.endswith('_PASSWORD'))}
        for secret in secrets:
            if secret:
                for variant in sorted({secret, quote(secret, safe=''), quote_plus(secret)}, key=len, reverse=True):
                    value = value.replace(variant, '<REDACTED>')
        value = re.sub(r'[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}', '<REDACTED_TOKEN>', value)
        value = re.sub(r"(setting\s+'(?:sbt_rel_token|idp_token_[A-Za-z0-9_]+)'\s+to\s+')[^']*", r'\1<REDACTED_TOKEN>', value)
        value = re.sub(r'(?i)Token\s+[a-f0-9]{40}\b', 'Token <REDACTED>', value)
        value = re.sub(r'(?i)Bearer\s+[^\s"\\,}]+', 'Bearer <REDACTED>', value)
        value = re.sub(r'(?i)(password=)[^&\s"\\]+', r'\1<REDACTED>', value)
        value = re.sub(r'(?i)(["\x27](?:access_token|refresh_token|auth_token|token|password)["\x27]\s*:\s*["\x27])[^"\x27]*', r'\1<REDACTED>', value)
    return value


def write(path, data):
    Path(path).write_text(json.dumps(data, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def model_hashes(project):
    paths = sorted((project / 'spec/js').glob('*.js'))
    paths += [project / 'relationship_scenario_plan.json', project / 'relationship_compilation.json']
    return {str(path.relative_to(project)): digest(path) for path in paths}


def secret_values(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if key.lower() in ('access_token', 'refresh_token', 'token', 'auth_token', 'password') and isinstance(item, str):
                yield item
            yield from secret_values(item)
    elif isinstance(value, list):
        for item in value:
            yield from secret_values(item)
    elif isinstance(value, str):
        try:
            nested = json.loads(value)
        except ValueError:
            return
        if isinstance(nested, (dict, list)):
            yield from secret_values(nested)


def windows_batch_command(args, comspec='cmd.exe'):
    """Return a raw cmd command line without a second list2cmdline conversion."""
    # cmd /s /c strips one outer quote pair. Quote every inner argument so
    # paths containing spaces or command separators remain single arguments.
    # Passing this as a list would escape its inner quotes using backslashes,
    # which cmd does not interpret as quote escapes.
    if any(any(c in str(value) for c in ('"', '\r', '\n', '\0', '%')) for value in args):
        raise ValueError('Unsupported character in Windows batch command argument.')
    inner = ' '.join('"' + str(value) + '"' for value in args)
    return subprocess.list2cmdline([comspec]) + ' /d /s /v:off /c "' + inner + '"'


def native(command, project):
    executable = shutil.which('provengo')
    if not executable:
        raise ValueError('Provengo was not found on PATH.')
    args = [executable] + command + [str(project)]
    # Windows requires cmd.exe to launch a batch entry point. Credentials remain
    # in the child environment and are never included in command arguments.
    if os.name == 'nt' and executable.lower().endswith(('.cmd', '.bat')):
        args = windows_batch_command(args, os.environ.get('COMSPEC', 'cmd.exe'))
    return subprocess.run(args, capture_output=True, text=True, encoding='utf-8',
                          errors='replace', timeout=600, check=False)


def bundle(project, report_paths, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in list((project / 'spec/js').glob('*.js')) + list(project.glob('*.json')) + report_paths:
            if path.is_file() and path.name not in {'native-result.json', 'relationship-samples.json', 'selected-sample.json'}:
                archive.write(path, path.relative_to(project))


def select_run_source(samples, sample_id, samples_path, report_dir):
    # One audited sample can be replayed directly without duplicating its large
    # serialized callbacks. Multi-sample selection preserves the existing path.
    if len(samples) == 1 and sample_id == 1:
        return samples_path
    selected = report_dir / 'selected-sample.json'
    write(selected, [samples[sample_id - 1]])
    return selected


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['sample', 'run'])
    parser.add_argument('--project', required=True, type=Path)
    parser.add_argument('--size', type=int, default=3)
    parser.add_argument('--sample-id', type=int, default=1)
    parser.add_argument('--review-zip', required=True, type=Path)
    args = parser.parse_args()
    project = args.project.resolve()
    report_dir = project / 'execution-review'
    report_dir.mkdir(exist_ok=True)
    compilation = json.loads((project / 'relationship_compilation.json').read_text(encoding='utf-8-sig'))
    plan = json.loads((project / 'relationship_scenario_plan.json').read_text(encoding='utf-8-sig'))
    samples_path = project / 'relationship-samples.json'
    report_path = report_dir / (args.mode + '-acceptance.json')
    output_path = report_dir / (args.mode + '-output.txt')
    result_path = report_dir / 'native-result.json'
    status = {'status': 'NOT_ACCEPTED', 'mode': args.mode, 'live_accepted': False,
              'reset_replay_accepted': False, 'automatic_retry': False, 'automatic_deletion': False}
    try:
        if compilation['status'] != 'COMPILED_NOT_LIVE_ACCEPTED' or not all(t['executable'] for t in plan['tasks']):
            raise ValueError('An executable compiled relationship project is required.')
        if args.mode == 'sample':
            if not 1 <= args.size <= 20:
                raise ValueError('Sample size must be between 1 and 20.')
            if samples_path.exists():
                raise ValueError('Samples already exist. Generate a new project to sample again.')
            response = native(['sample', '--algorithm', 'random', '--size', str(args.size),
                               '--max-length', str(max(600, 2 * compilation['task_count'] + compilation['http_requests_per_complete_schedule'] + 4)), '-o', str(samples_path)], project)
            output_path.write_text(redact(response.stdout + '\n' + response.stderr), encoding='utf-8')
            if response.returncode:
                raise ValueError('Native sampling returned exit code ' + str(response.returncode) + '\n' + redact(response.stdout + '\n' + response.stderr)[-4000:])
            status.update(audit_samples(json.loads(samples_path.read_text()), plan))
            if status['sample_count'] != args.size:
                raise ValueError('Native sampler did not produce the requested number of samples.')
            status['samples_sha256'] = digest(samples_path)
            status['model_sha256'] = model_hashes(project)
        else:
            if not os.environ.get('SBT_REL_USERNAME') or not os.environ.get('SBT_REL_PASSWORD'):
                raise ValueError('Username and password must be supplied by the PowerShell wrapper.')
            accepted = json.loads((report_dir / 'sample-acceptance.json').read_text())
            if accepted.get('status') != 'NATIVE_SYMBOLIC_SAMPLES_COMPLETE' or accepted.get('samples_sha256') != digest(samples_path) or accepted.get('model_sha256') != model_hashes(project):
                raise ValueError('Native samples require a successful matching audit before live replay.')
            samples = json.loads(samples_path.read_text())
            audit_samples(samples, plan)
            if not 1 <= args.sample_id <= len(samples):
                raise ValueError('Sample ID is outside the sampled range.')
            selected = select_run_source(samples, args.sample_id, samples_path, report_dir)
            # Release audited samples before starting Java.
            del samples
            __import__('gc').collect()
            response = native(['--batch-mode', 'run', '--run-source', str(selected), '--run-id', '1',
                               '--output-file', str(result_path)], project)
            output = response.stdout + '\n' + response.stderr
            structured = None
            if result_path.exists():
                raw = result_path.read_text(encoding='utf-8-sig')
                try:
                    structured = json.loads(raw)
                    write(result_path, redact(structured))
                except ValueError:
                    result_path.write_text(redact(raw), encoding='utf-8')
            for secret in secret_values(structured):
                if secret:
                    output = output.replace(secret, '<REDACTED>')
            receipt = find_receipt(output, structured)
            output_path.write_text(redact(output), encoding='utf-8')
            status.update(native_exit_code=response.returncode, sample_id=args.sample_id)
            if response.returncode:
                raise ValueError('Native live replay returned exit code ' + str(response.returncode) + '\n' + failure_excerpt(output))
            if not receipt:
                status['status'] = 'INCONCLUSIVE_RECEIPT_MISSING'
                raise ValueError('Native exit was zero but the complete runtime receipt was not observed.')
            if plan.get('identity_program') or any(t['kind']=='copy_isolation' for t in plan['tasks']):
                status['runtime_receipt'] = receipt
            validate_negative_receipts(receipt, plan)
            validate_legal_receipts(receipt, plan)
            validate_shared_update_receipts(receipt, plan)
            validate_deletion_receipts(receipt, plan)
            validate_reference_receipts(receipt, plan)
            validate_semantic_receipts(receipt, plan)
            validate_transfer_receipts(receipt, plan)
            validate_route_receipts(receipt, plan)
            validate_copy_receipts(receipt, plan)
            validate_identity_receipts(receipt, plan)
            if receipt.get('task_count') != compilation['task_count'] or receipt.get('response_count') != compilation['http_requests_per_complete_schedule'] or receipt.get('owned_instances') != sum(map(len, plan['instances'].values())):
                raise ValueError('Runtime receipt does not cover the complete generated model.')
            status.update(status='NATIVE_RELATIONSHIP_CALLBACKS_PASS', live_accepted=True, runtime_receipt=receipt)
    except (ValueError, OSError, KeyError, subprocess.TimeoutExpired) as error:
        status.update(error=str(error), live_accepted=False)
        if args.mode == 'sample':
            status['status'] = 'NATIVE_SYMBOLIC_SAMPLING_NOT_ACCEPTED'
        elif status['status'] != 'INCONCLUSIVE_RECEIPT_MISSING':
            status['status'] = 'NATIVE_LIVE_REPLAY_NOT_ACCEPTED'
    finally:
        # Raw native result files are excluded from the review archive. They are
        # scrubbed in place even when replay cannot produce acceptance evidence.
        if result_path.exists():
            result_path.write_text(redact(result_path.read_text(encoding='utf-8-sig')), encoding='utf-8')
        write(report_path, redact(status))
        bundle(project, list(report_dir.glob('*')), args.review_zip)
    print(status['status'])
    print('Review ZIP: ' + str(args.review_zip))
    if status.get('error'):
        print(status['error'])
    print('No automatic deletion, retry, rollback, or full server reset/replay was performed.')
    return 0 if status['status'] in {'NATIVE_SYMBOLIC_SAMPLES_COMPLETE', 'NATIVE_RELATIONSHIP_CALLBACKS_PASS'} else 1


if __name__ == '__main__':
    sys.exit(main())
