"""Independently recompute quantitative and merge expectations from ordered receipts."""
import copy
import json
import math


def validate_semantic_receipts(receipt, plan):
    cfg = plan.get('semantic_program')
    if cfg is None:
        return
    tasks = {t['id']: t for t in plan['tasks'] if t['kind'].startswith('semantic_')}
    records = receipt.get('semantic_tests', [])
    if len(records) != len(tasks) or len({r.get('task_id') for r in records}) != len(tasks):
        raise ValueError('Incomplete or duplicate semantic receipts.')
    owned = {r['instance']: r for r in receipt['owned_records']}
    expected_owned = {i for values in plan['instances'].values() for i in values}
    if len(owned) != len(receipt['owned_records']) or set(owned) != expected_owned:
        raise ValueError('Semantic ownership bindings are incomplete.')
    def identity(instance, field):
        value = owned[instance]['route'].get(field)
        if not isinstance(value, str) or not value:
            raise ValueError('Semantic identity binding is missing.')
        return value
    tolerance = cfg['tolerance']
    def number(value):
        if type(value) not in (int, float) or not math.isfinite(value) or value < -tolerance:
            raise ValueError('Invalid independently observed semantic quantity.')
        return value
    def maps(left, right):
        if not isinstance(left, dict) or not isinstance(right, dict):
            raise ValueError('Semantic quantity maps are required.')
        for k in set(left) | set(right):
            a, b = number(left.get(k, 0)), number(right.get(k, 0))
            if abs(a-b) > tolerance*max(1, abs(a), abs(b)):
                raise ValueError('Independent semantic quantity mismatch.')
    def views(expected, observed):
        if set(expected) != set(observed):
            raise ValueError('Semantic view coverage differs.')
        for i in expected:
            if set(expected[i]) != set(observed[i]):
                raise ValueError('Semantic view fields differ.')
            for field in expected[i]:
                maps(expected[i][field], observed[i][field])
    def clean(value):
        return {k: number(v) for k, v in value.items() if abs(v) > tolerance}
    init = records[0]
    if init.get('kind') != 'semantic_init' or init.get('task_id') != 'semantic:init':
        raise ValueError('Semantic baseline must precede mutations.')
    state = copy.deepcopy(init['initial'])
    view_kinds = {v['instance']: v['view_kind'] for v in tasks['semantic:init']['checks']}
    if set(state) != set(view_kinds):
        raise ValueError('Incomplete semantic baseline views.')
    known_ids = {v for r in owned.values() for v in r['route'].values() if isinstance(v, str)}
    resource_ids = {identity(i, cfg['resource_identity']) for i in plan['instances'][cfg['resource_type']]}
    for i, view in state.items():
        if set(view) != ({'totals', 'references'} if view_kinds[i] == 'container' else {'totals'}):
            raise ValueError('Invalid semantic baseline fields.')
        totals = view['totals']
        if not totals:
            raise ValueError('Empty semantic baseline quantity view.')
        for k, v in totals.items():
            parts = json.loads(k)
            if len(parts) != len(cfg['reference_measure']['key_paths']) or any(p not in known_ids for p in parts) or parts[cfg['merge_key_index']] not in resource_ids:
                raise ValueError('Unowned semantic baseline group identity.')
            number(v)
        if view_kinds[i] == 'container':
            if view.get('references') != {} or abs(sum(totals.values())-cfg['baseline_container_total']) > tolerance:
                raise ValueError('Invalid manual quantity baseline.')
        elif ('baseline_reference_total' in cfg and (abs(sum(totals.values())-cfg['baseline_reference_total']) > tolerance or any(abs(v/cfg['baseline_reference_item_quantity']-round(v/cfg['baseline_reference_item_quantity'])) > tolerance for v in totals.values()))) or ('baseline_reference_total' not in cfg and any(abs(v-cfg['baseline_reference_item_quantity']) > tolerance for v in totals.values())):
            raise ValueError('Invalid controlled reference quantity baseline.')
    done = {'semantic:init'}
    retired = set()
    for record in records[1:]:
        task = tasks.get(record.get('task_id'))
        if task is None or task['kind'] != record.get('kind') or not (set(task['after']) & set(tasks)).issubset(done):
            raise ValueError('Semantic receipt order violates task dependencies.')
        views(state, record['before'])
        expected = copy.deepcopy(state)
        if task['kind'] == 'semantic_contribution':
            source, target = task['reference_instance'], task['source_instance']
            ref = identity(source, cfg['reference_identity'])
            if (record.get('container'), record.get('reference_instance'), record.get('reference_id'), record.get('amount')) != (target, source, ref, task['amount']):
                raise ValueError('Semantic contribution identity or amount differs from plan.')
            amount = task['amount']
            for k, v in state[source]['totals'].items():
                expected[target]['totals'][k] = expected[target]['totals'].get(k, 0)+amount*v
            expected[target]['totals'] = clean(expected[target]['totals'])
            expected[target]['references'][ref] = expected[target]['references'].get(ref, 0)+amount
            expected[target]['references'] = clean(expected[target]['references'])
        elif task['kind'] == 'semantic_merge':
            source, target = task['from_instance'], task['to_instance']
            before, after = identity(source, cfg['resource_identity']), identity(target, cfg['resource_identity'])
            if source in retired or target in retired or before == after:
                raise ValueError('Merge uses a retired or identical resource.')
            if (record.get('from_instance'), record.get('to_instance'), record.get('from_id'), record.get('to_id')) != (source, target, before, after):
                raise ValueError('Merge identity differs from typed owned bindings.')
            if record.get('source_absent') is not True or record.get('absence_code') not in task['absent_codes'] or owned[source].get('deleted') is not True or owned[source].get('merged_into') != after:
                raise ValueError('Merge source absence evidence is missing.')
            collisions = 0
            for view in expected.values():
                totals = {}
                for k, value in view['totals'].items():
                    parts = json.loads(k)
                    if parts[cfg['merge_key_index']] == before:
                        parts[cfg['merge_key_index']] = after
                    key = json.dumps(parts, separators=(',', ':'))
                    totals[key] = totals.get(key, 0)+value
                collisions += len(view['totals'])-len(totals)
                view['totals'] = clean(totals)
            if cfg.get('require_merge_collision') and (collisions < 1 or record.get('collision_groups') != collisions):
                raise ValueError('Independent merge collision coverage was not observed.')
            retired.add(source)
        else:
            raise ValueError('Unexpected semantic task kind.')
        views(expected, record['expected'])
        checks = record['checks']
        if len(checks) != len(view_kinds) or len({c['instance'] for c in checks}) != len(view_kinds):
            raise ValueError('Incomplete independent semantic readbacks.')
        for check in checks:
            i = check['instance']
            if view_kinds.get(i) != check['view_kind']:
                raise ValueError('Incorrect semantic readback type.')
            views({i: expected[i]}, {i: check['observed']})
        state = expected
        done.add(task['id'])
    if done != set(tasks):
        raise ValueError('Missing semantic transitions.')
