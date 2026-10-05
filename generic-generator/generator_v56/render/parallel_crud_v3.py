"""Concurrent CRUD schedules with symbolic IDs and runtime REST callbacks.

Every branch in this module is decided at sampling time. HTTP codes and
server-assigned identifiers are handled exclusively by actuation callbacks.
"""
from __future__ import annotations

import json
import re

from .naming import js_string, safe_identifier
from .stories_js import _minimal_values, _value_js, _request_body_schemas_for_operation
from .parallel_crud import _parallel_update_choice
from ..inference.values import generate_value
from ..request_variants import select_request_variant


def _rv(owner, field):
    return 'sbt_' + re.sub(r'[^A-Za-z0-9_]', '_', owner + '_' + field)


def _arg(field, context='__args'):
    return context + '[' + js_string(safe_identifier(field)) + ']'


def _url(op, context='__args'):
    parts = re.split(r'(\{[^}]+\})', op.op.path)
    return ' + '.join(_arg(part[1:-1], context) if part.startswith('{') else js_string(part)
                      for part in parts if part)


def _body(op, context='__args', opaque=None, override=None):
    if override is not None:
        return override
    if opaque is not None:
        return 'JSON.stringify(' + opaque + ')'
    if not op.op.request_body:
        return None
    names = op.body_props
    if not names:
        raise ValueError('No contract-derived body for ' + op.op.path)
    fields = ','.join(js_string(raw) + ':' + _arg(raw, context) for raw in names)
    return 'JSON.stringify({' + fields + '})'


def _rule_expression(value, context):
    if isinstance(value, str) and re.fullmatch(r'\$\{[A-Za-z][A-Za-z0-9_]*\}', value):
        return _arg(value[2:-1], context)
    if isinstance(value, list):
        return '[' + ','.join(_rule_expression(item, context) for item in value) + ']'
    if isinstance(value, dict):
        return '{' + ','.join(js_string(key) + ':' + _rule_expression(item, context)
                              for key, item in value.items()) + '}'
    return _value_js(value)


def _validate_request_rules(plan, request_rules):
    if request_rules is None:
        return {}
    if not isinstance(request_rules, dict):
        raise ValueError('request_rules must be a mapping')
    operations = {op.op.method + ' ' + op.op.path: op for ep in plan.entities for op in ep.ops}
    for key, rule in request_rules.items():
        if key not in operations or not isinstance(rule, dict) or not rule.get('evidence'):
            raise ValueError('Request rule lacks an OpenAPI operation or evidence: ' + key)
        if any(field not in ('defaults', 'headers', 'accept_statuses', 'evidence',
                             'setup_create', 'refresh_update', 'race_enabled',
                             'exclusive_parent', 'race_field', 'config_map_race',
                             'config_map_update')
               for field in rule):
            raise ValueError('Unsupported request rule field for ' + key)
        if 'defaults' in rule and (not isinstance(rule['defaults'], dict) or
                                   operations[key].op.method != 'POST'):
            raise ValueError('Create defaults require an OpenAPI POST: ' + key)
        if 'accept_statuses' in rule and (not isinstance(rule['accept_statuses'], list) or
                                          any(type(code) is not int or code < 200 or code >= 300
                                              for code in rule['accept_statuses'])):
            raise ValueError('Invalid successful statuses for ' + key)
        if 'setup_create' in rule:
            setup = rule['setup_create']
            if (not isinstance(setup, dict) or
                    set(setup) != {'operation', 'capture_field', 'body'} or
                    setup['operation'] not in operations or
                    not setup['operation'].startswith('POST ') or
                    not isinstance(setup['body'], dict) or
                    setup['capture_field'] not in ('id',)):
                raise ValueError('Invalid setup create dependency for ' + key)
        if 'refresh_update' in rule and (rule['refresh_update'] is not True or
                                         operations[key].op.method != 'PUT'):
            raise ValueError('Update refresh requires an OpenAPI PUT: ' + key)
        if 'race_enabled' in rule and (rule['race_enabled'] is not True or
                                       operations[key].op.method != 'PUT'):
            raise ValueError('Disjoint race requires an OpenAPI PUT: ' + key)
        if 'race_field' in rule:
            props = _request_body_schemas_for_operation(operations[key])
            field = rule['race_field']
            if (operations[key].op.method != 'PUT' or not rule.get('race_enabled') or
                    not isinstance(field, str) or field not in props or
                    props[field].get('readOnly') or
                    props[field].get('type') != 'object' or
                    not isinstance(props[field].get('additionalProperties'), dict)):
                raise ValueError('Race field must be a writable OpenAPI object map: ' + key)
        if 'config_map_update' in rule or 'config_map_race' in rule:
            op = operations[key]
            props = _request_body_schemas_for_operation(op)
            config = props.get('config', {})
            keys = rule.get('config_map_race') or [rule.get('config_map_update')]
            if (op.op.method != 'PUT' or
                    ('config_map_race' in rule and not rule.get('race_enabled')) or
                    not isinstance(keys, list) or len(keys) not in (1, 2) or
                    any(not isinstance(k, str) or not k for k in keys) or
                    len(set(keys)) != len(keys) or config.get('type') != 'object' or
                    not isinstance(config.get('additionalProperties'), dict) or
                    config.get('readOnly')):
                raise ValueError('Config update requires writable OpenAPI map keys: ' + key)
        if 'exclusive_parent' in rule:
            operation = operations[key]
            entity = next(ep for ep in plan.entities if operation in ep.ops)
            dependencies = sorted({edge.target for edge in entity.dependencies},
                                  key=lambda dep: (-dep.count('/'), dep))
            if (operation.op.method != 'POST' or not dependencies or
                    rule['exclusive_parent'] != dependencies[0]):
                raise ValueError('Exclusive parent must be the primary create dependency: ' + key)
    return request_rules


def _race_choice(entity, update, request_rules):
    if not update or not entity.get_op:
        return None
    op = update[5]
    rule = request_rules.get(op.op.method + ' ' + op.op.path, {})
    if not rule.get('race_enabled'):
        return None
    if rule.get('config_map_race'):
        return (0, 'config', 'config', _request_body_schemas_for_operation(op)['config'])
    if op.op.method != 'PUT':
        raise ValueError('Race requires a full PUT operation')
    preferred = ('firstName', 'lastName', 'description', 'displayName',
                 'consentText', 'name', 'alias')
    own = {safe_identifier(field) for field in entity.key.fields}
    for field in tuple(own):
        for suffix in ('name', 'alias'):
            if field.lower().endswith(suffix):
                own.add(suffix)
    override = rule.get('race_field')
    options = []
    for raw, schema in _request_body_schemas_for_operation(op).items():
        field = safe_identifier(raw)
        if (field in own or field == update[2] or
                (field not in preferred and raw != override) or
                (field != override and override is not None) or
                (field == override and schema.get('type') != 'object') or
                (field != override and schema.get('type') != 'string') or
                schema.get('enum') or
                schema.get('readOnly') or schema.get('format')):
            continue
        options.append((preferred.index(field) if field in preferred else len(preferred),
                        field, raw, schema))
    if not options:
        raise ValueError('Race rule lacks two disjoint writable fields: ' + op.op.path)
    return min(options)


def _callback(op, *, capture=None, lookup=None, store_body=None,
              changed_field=None, changed_value=None, expected=None, build_update=None,
              race_prepare=None, race_expectation=None, config_map_keys=None):
    codes = expected if expected is not None else op.success_codes
    if not codes:
        raise ValueError('No documented successful status for ' + op.op.path)
    lines = ['if (' + _value_js(codes) + '.indexOf(response.code) < 0) {'
             ' pvg.fail(' + js_string('Unexpected HTTP for ' + op.op.method + ' ' + op.op.path) +
             ' + ":" + response.code); return; }']
    if lookup:
        rv, field, expected_rv = lookup
        lines += [
            'var items; try { items = JSON.parse(response.body); }'
            ' catch(err) { pvg.fail("lookup JSON invalid"); return; }',
            'if (!Array.isArray(items)) { pvg.fail("lookup is not an array"); return; }',
            'var matches = items.filter(function(item){ return item && item[' + js_string(field) +
            '] === pvg.rtv.get(' + js_string(expected_rv) + '); });',
            'if (matches.length !== 1 || !matches[0].id) {'
            ' pvg.fail("exact lookup missing or ambiguous"); return; }',
            'pvg.rtv.set(' + js_string(rv) + ', matches[0].id);',
        ]
    if capture:
        rv, key = capture
        lines += [
            'var obj = null; try { obj = JSON.parse(response.body); } catch(err) {}',
            'var value = obj && typeof obj === "object" ? (obj[' + js_string(key) +
            '] === undefined ? obj.id : obj[' + js_string(key) + ']) : null;',
            'if (value === undefined || value === null || value === "") {',
            ' var headers = response.headers || {}; var location = headers.Location || headers.location;',
            ' if (!location) { for (var name in headers) {'
            ' if (name.toLowerCase() === "location") { location = headers[name]; break; } } }',
            ' if (location) value = String(location).split("?")[0].replace(/\\/$/, "").split("/").pop();',
            '}',
            'if (value === undefined || value === null || value === "") {'
            ' pvg.fail("create identifier unavailable"); return; }',
            'pvg.rtv.set(' + js_string(rv) + ', value);',
        ]
    if store_body:
        lines += ['try { JSON.parse(response.body); } catch(err) {'
                  ' pvg.fail("read body JSON invalid"); return; }',
                  'pvg.rtv.set(' + js_string(store_body) + ', response.body);']
    if build_update:
        body_var, update_field, update_value = build_update
        lines += ['var updateBody; try { updateBody = JSON.parse(response.body); }'
                  ' catch(err) { pvg.fail("update base JSON invalid"); return; }',
                  'if (!updateBody || typeof updateBody !== "object" ||'
                  ' Array.isArray(updateBody)) { pvg.fail("update base is not an object"); return; }',
                  ('updateBody.config=Object.assign({},updateBody.config||{});'
                   'updateBody.config[' + js_string(config_map_keys[0]) + ']=' + update_value + ';')
                  if config_map_keys else 'updateBody[' + js_string(update_field) + ']=' + update_value + ';',
                  'pvg.rtv.set(' + js_string(body_var) + ',JSON.stringify(updateBody));']
    if changed_field is not None:
        lines += ['var observed; try { observed = JSON.parse(response.body); }'
                  ' catch(err) { pvg.fail("update readback JSON invalid"); return; }',
                  'if (!observed || ' +
                  ('!observed.config || observed.config[' + js_string(config_map_keys[0]) + ']'
                   if config_map_keys else 'observed[' + js_string(changed_field) + ']') + ' !== ' +
                  changed_value + ') { pvg.fail("update readback mismatch"); return; }']
    if race_prepare:
        rv, field_a, value_a, field_b, value_b = race_prepare
        lines += [
            'var raceBase; try { raceBase=JSON.parse(response.body); }'
            ' catch(err) { pvg.fail("race base JSON invalid"); return; }',
            'if(!raceBase || typeof raceBase!=="object" || Array.isArray(raceBase))'
            ' { pvg.fail("race base is not an object"); return; }',
            ('var raceA=Object.assign({},raceBase);raceA.config=Object.assign({},raceBase.config||{});'
             'raceA.config[' + js_string(config_map_keys[0]) + ']=' + value_a + ';')
            if config_map_keys else 'var raceA=Object.assign({},raceBase);raceA[' + js_string(field_a) + ']=' + value_a + ';',
            ('var raceB=Object.assign({},raceBase);raceB.config=Object.assign({},raceBase.config||{});'
             'raceB.config[' + js_string(config_map_keys[1]) + ']=' + value_b + ';')
            if config_map_keys else 'var raceB=Object.assign({},raceBase);raceB[' + js_string(field_b) + ']=' + value_b + ';',
            'pvg.rtv.set(' + js_string(rv) +
            ',JSON.stringify({method:"PUT",A:raceA,B:raceB}));',
        ]
    if race_expectation:
        payload_rv, field_a, field_b = race_expectation
        lines += [
            'var observed; try { observed=JSON.parse(response.body); }'
            ' catch(err) { pvg.fail("race readback JSON invalid"); return; }',
            'var payload; try { payload=JSON.parse(pvg.rtv.get(' + js_string(payload_rv) + ')); }'
            ' catch(err) { pvg.fail("race payload JSON invalid"); return; }',
            'function same(a,b){if(a===b)return true;'
            'if(a===null||b===null||typeof a!=="object"||typeof b!=="object")return false;'
            'if(Array.isArray(a)!==Array.isArray(b))return false;'
            'var ka=Object.keys(a).sort(),kb=Object.keys(b).sort();'
            'if(ka.length!==kb.length)return false;'
            'for(var i=0;i<ka.length;i++){if(ka[i]!==kb[i]||!same(a[ka[i]],b[kb[i]]))return false;}'
            'return true;}',
            ('var serialA=observed && same(observed.config,payload.A.config);') if config_map_keys else
            'var serialA=observed && same(observed[' + js_string(field_a) + '],payload.A[' +
            js_string(field_a) + ']) && same(observed[' + js_string(field_b) + '],payload.A[' +
            js_string(field_b) + ']);',
            ('var serialB=observed && same(observed.config,payload.B.config);') if config_map_keys else
            'var serialB=observed && same(observed[' + js_string(field_a) + '],payload.B[' +
            js_string(field_a) + ']) && same(observed[' + js_string(field_b) + '],payload.B[' +
            js_string(field_b) + ']);',
            'if(!serialA && !serialB) {'
            ' pvg.fail("RACE_OUTCOME_UNCLASSIFIED"); return; }',
        ]
    lines += ['pvg.success("contract response verified");']
    return 'new Function("response",' + js_string(' '.join(lines)) + ')'


def _request(op, *, context='__args', opaque=None, override_body=None,
             capture=None, lookup=None, store_body=None, changed_field=None,
             changed_value=None, expected=None, query_overrides=None,
             build_update=None, race_prepare=None, race_expectation=None,
             request_rules=None, auth_token_env=None, event_tag=None,
             config_map_keys=None):
    method = op.op.method.lower()
    if method not in ('get', 'post', 'put', 'patch', 'delete'):
        raise ValueError('Unsupported CRUD method ' + method)
    rule = (request_rules or {}).get(op.op.method + ' ' + op.op.path, {})
    codes = list(expected if expected is not None else op.success_codes)
    if expected is None:
        codes = list(dict.fromkeys(codes + rule.get('accept_statuses', [])))
    token_env = auth_token_env or 'ACCESS_TOKEN'
    if not re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*', token_env):
        raise ValueError('Invalid authorization environment variable')
    headers = {'Authorization': js_string('Bearer @{getEnv(\'' + token_env + '\')}')}
    headers.update({key: _value_js(value) for key, value in rule.get('headers', {}).items()})
    options = ['headers:{' + ','.join(js_string(key) + ':' + value
                                     for key, value in headers.items()) + '}',
               'expectedResponseCodes:' + _value_js(codes)]
    body = _body(op, context, opaque, override_body)
    if body is not None:
        if (rule.get('defaults') and override_body is None and
                (opaque is None or opaque.lstrip().startswith('{'))):
            default_fields = ','.join(js_string(key) + ':' + _rule_expression(value, context)
                                      for key, value in rule['defaults'].items())
            body = 'JSON.stringify(Object.assign({' + default_fields + '},JSON.parse(' + body + ')))'
        if 'Content-Type' not in headers:
            options[0] = options[0][:-1] + ',"Content-Type":"application/json"}'
        options.append('body:' + body)
    query = {q: _arg(q, context) for q in op.query_params}
    query.update(query_overrides or {})
    if query:
        fields = []
        for raw, expression in query.items():
            if raw in (query_overrides or {}):
                fields.append('q[' + js_string(raw) + ']=' + expression + ';')
            else:
                fields.append('if(' + expression + '!==undefined && ' + expression +
                              '!==null) q[' + js_string(raw) + ']=' + expression + ';')
        options.append('parameters:(function(){var q={};' + ''.join(fields) + 'return q;})()')
    options.append('callback:' + _callback(op, capture=capture, lookup=lookup,
                                           store_body=store_body,
                                           changed_field=changed_field,
                                           changed_value=changed_value, expected=codes,
                                           build_update=build_update,
                                           race_prepare=race_prepare,
                                           race_expectation=race_expectation,
                                           config_map_keys=config_map_keys))
    url = _url(op, context)
    if event_tag:
        url = '(' + url + ') + ' + js_string(
            ('&' if '?' in op.op.path else '?') + '__sbt_event=' + event_tag)
    return 'svc.' + method + '(' + url + ',{' + ','.join(options) + '});'


def render_parallel_crud_v3(plan, slug, processes, request_rules=None,
                            auth_token_env=None, transport_registry=None):
    if not 1 <= processes <= 8 or not 1 <= plan.instances_per_entity <= 8:
        raise ValueError('logical process / entity instances out of range')
    by_key = {ep.entity.key: ep for ep in plan.entities}
    request_rules = _validate_request_rules(plan, request_rules)
    event_index = 0
    def request(op, **kwargs):
        nonlocal event_index
        event_index += 1
        options = dict(kwargs, request_rules=request_rules,
                       auth_token_env=auth_token_env,
                       event_tag='event_' + str(event_index))
        legacy = _request(op, **options)
        if transport_registry is None:
            return legacy
        context = options.get('context', '__args')
        options['context'] = '__args'
        source = _request(op, **options)
        return transport_registry.add(source, ['__args'], [context], legacy,
                                      operation=op.op.method + ' ' + op.op.path)
    children = {key: set() for key in by_key}
    for ep in plan.entities:
        for edge in ep.dependencies:
            if edge.target in by_key:
                children[edge.target].add(ep.entity.key)
    # Provengo bthreads must exchange state through events. A shared JS object
    # may appear to work for some sampled branches yet leave others waiting.
    lines = [
        '// Generated symbolic concurrent CRUD. Callback data is runtime-only.',
        '// @provengo summon rest', '// @provengo summon rtv',
    ]
    for process in range(1, processes + 1):
        for key in plan.graph.creation_order:
            ep = by_key.get(key)
            if ep is None or ep.create_op is None:
                continue
            deps = sorted({e.target for e in ep.dependencies if e.target in by_key},
                          key=lambda k: (-k.count('/'), k))
            create_rule = request_rules.get(ep.create_op.op.method + ' ' + ep.create_op.op.path, {})
            exclusive_parent = create_rule.get('exclusive_parent')
            if exclusive_parent and (not deps or deps[0] != exclusive_parent):
                raise ValueError('Exclusive parent is unavailable: ' + key)
            association = (bool(ep.create_op.op.request_body) and
                           not ep.create_op.body_props and
                           any(p.rule == 'D5:primitive_association_id_description'
                               for edge in ep.dependencies for p in edge.provenance))
            association_parents = [dep for dep in deps if dep != 'admin/realms']
            if association and len(association_parents) != 2:
                raise ValueError('Primitive association needs two resource parents: ' + key)
            update = _parallel_update_choice(ep) if ep.get_op else None
            if update:
                update_rule = request_rules.get(update[5].op.method + ' ' + update[5].op.path, {})
                if update_rule.get('config_map_race') or update_rule.get('config_map_update'):
                    update = (0, 0, 'config', 'config',
                              _request_body_schemas_for_operation(update[5])['config'], update[5])
            race = _race_choice(ep, update, request_rules)
            stages = (['readback'] if ep.get_op else []) + ['create']
            if ep.get_op:
                stages.append('read')
            if update:
                stages.append('update')
            if race:
                stages.append('race')
            if ep.delete_op:
                stages.append('delete')
            for instance in range(1, plan.instances_per_entity + 1):
                owner = 'P' + str(process) + ':' + key + ':' + str(instance)
                tag = js_string(owner)
                child_keys = sorted(children[key])
                if deps:
                    lines += [
                        'bthread("bind:' + owner + '", function(){',
                        'let available={}; let candidates=[]; let required=' + _value_js(deps) + ';',
                        'while(true){',
                        'let first=available[required[0]]||[];',
                        ('candidates=first.filter(function(anchor){return anchor.owner===' +
                         _value_js('P' + str(process) + ':' + exclusive_parent + ':' + str(instance)) +
                         ' && required.every(function(type){' if exclusive_parent else
                         'candidates=first.filter(function(anchor){return required.every(function(type){'),
                        'return (available[type]||[]).some(function(parent){'
                        'return anchor.values.realm===undefined || parent.values.realm===undefined'
                        ' || parent.values.realm===anchor.values.realm;});});});',
                        ('if(required.every(function(type){return (available[type]||[]).length===' +
                         str(plan.instances_per_entity) + ';}) && candidates.length) break;'
                         if association else 'if(candidates.length) break;'),
                        'let ready=sync({waitFor:EventSet("any-parent:' + owner + '",function(e){'
                        'return e.name==="SBT:InstanceReady" && e.data && e.data.process===' +
                        str(process) + ' && required.indexOf(e.data.entity)>=0;})});',
                        'if(!available[ready.data.entity]) available[ready.data.entity]=[];',
                        'available[ready.data.entity].push({owner:ready.data.owner,values:ready.data.values});',
                        '}',
                        'let parents={};',
                    ]
                    if association:
                        lines += [
                            'let pairs=[]; let peerType=' + _value_js(association_parents[1]) + ';',
                            'for(let ai=0;ai<candidates.length;ai++){',
                            'let anchor=candidates[ai];',
                            'let peers=available[peerType].filter(function(parent){'
                            'return anchor.values.realm===undefined || parent.values.realm===undefined'
                            ' || parent.values.realm===anchor.values.realm;});',
                            'for(let pi=0;pi<peers.length;pi++) pairs.push({anchor:ai,peer:pi});',
                            '}',
                            'if(pairs.length<' + str(plan.instances_per_entity) + ')'
                            ' throw new Error("Insufficient unique association pairs for "+' + tag + ');',
                            'let pair=pairs[' + str(instance - 1) + '];',
                        ]
                    lines += [
                        ('let options=[Event("SBT:BindParent",{child:' + tag +
                         ',type:required[0],index:pair.anchor})];'
                         if association else
                         'let options=candidates.map(function(parent,index){return Event("SBT:BindParent",'
                         '{child:' + tag + ',type:required[0],index:index});});'),
                        'let chosen=sync({request:options});',
                        'let anchor=candidates[chosen.data.index]; parents[required[0]]=anchor.values;',
                        'for(let i=1;i<required.length;i++){',
                        'let type=required[i]; let matches=available[type].filter(function(parent){'
                        'return anchor.values.realm===undefined || parent.values.realm===undefined'
                        ' || parent.values.realm===anchor.values.realm;});',
                        ('let choices=[Event("SBT:BindParent",{child:' + tag +
                         ',type:type,index:(type===' + _value_js(association_parents[1]) +
                         ' ? pair.peer : 0)})];'
                         if association else
                         'let choices=matches.map(function(parent,index){return Event("SBT:BindParent",'
                         '{child:' + tag + ',type:type,index:index});});'),
                        'let picked=sync({request:choices}); parents[type]=matches[picked.data.index].values;',
                        '}',
                        'sync({request:Event("SBT:ParentsBound",{owner:' + tag +
                        ',parents:parents})});',
                        '});',
                    ]
                if child_keys:
                    expected_child_owners = ['P' + str(process) + ':' + child + ':' + str(child_instance)
                                             for child in child_keys
                                             for child_instance in range(1, plan.instances_per_entity + 1)]
                    lines += [
                        'bthread("children:' + owner + '", function(){',
                        'let finished={}; let cleanup=false; let remaining=' +
                        str(len(expected_child_owners)) + ';',
                        'while(remaining>0 || !cleanup){',
                        'let event=sync({waitFor:EventSet("child-finish:' + owner + '",function(e){'
                        'return e.data && ((e.name==="SBT:WorkerFinished" && ' +
                        _value_js(expected_child_owners) + '.indexOf(e.data.owner)>=0)'
                        ' || (e.name==="SBT:CleanupReady" && e.data.owner===' + tag + '));})});',
                        'if(event.name==="SBT:CleanupReady") cleanup=true;',
                        'else if(!finished[event.data.owner]){'
                        'finished[event.data.owner]=true; remaining--;}',
                        '}',
                        'sync({request:Event("SBT:ChildrenFinished",{owner:' + tag + '})});',
                        '});',
                    ]
                prefix = 'p' + str(process) + '_' + safe_identifier(key.replace('/', '_')) + '_' + str(instance)
                body_rv = _rv(owner, 'read_body')
                update_body_rv = _rv(owner, 'update_body')
                update_field = update[3] if update else None
                update_value = (_value_js(generate_value(update[4], plan.seed,
                                  'parallel-crud.' + owner + '.' + update[2], for_request=True))
                                if update else None)
                config_keys = (update_rule.get('config_map_race') or
                               ([update_rule['config_map_update']]
                                if 'config_map_update' in update_rule else None)) if update else None
                if config_keys:
                    update_value = _value_js('sbt_claim_' + safe_identifier(owner))
                race_field = race[2] if race else None
                race_value = None
                if race:
                    generated = generate_value(race[3], plan.seed,
                                               'parallel-crud.' + owner + '.race.' + race[1],
                                               for_request=True)
                    if race[3].get('type') == 'object':
                        value_schema = race[3]['additionalProperties']
                        generated = {'sbt_race': generate_value(
                            value_schema, plan.seed,
                            'parallel-crud.' + owner + '.race.' + race[1] + '.sbt_race',
                            for_request=True)}
                    race_value = _value_js(generated)
                    if config_keys:
                        race_value = _value_js('sbt_attribute_' + safe_identifier(owner))
                race_first_value = None
                if race:
                    if config_keys:
                        race_first_value = _value_js('sbt_race_claim_' + safe_identifier(owner))
                    else:
                        race_first_value = _value_js(generate_value(
                            update[4], plan.seed,
                            'parallel-crud.' + owner + '.race.first.' + update[2],
                            for_request=True))
                    if race_first_value == update_value:
                        raise ValueError('Race A must differ from the preceding serial update: ' + owner)
                race_rv = _rv(owner, 'race_payload') if race else None
                # The observer waits on the worker's *symbolic* stage. Its
                # own REST GET is a real action and its callback is the oracle.
                lines += [
                    'bthread("verify:' + owner + '", function(){',
                    'for (let stage of ' + _value_js(stages) + ') {',
                    'let step=sync({waitFor:EventSet("step-or-finish:' + owner + '",function(e){'
                    'return e.data && e.data.owner===' + tag +
                    ' && ((e.name==="SBT:CrudStep" && e.data.stage===stage)'
                    ' || e.name==="SBT:WorkerFinished");})});',
                    'if(step.name==="SBT:WorkerFinished") return;',
                ]
                if ep.get_op:
                    lines += ['if(stage==="create" || stage==="readback") {',
                              request(ep.get_op, context='step.data.values'), '}']
                    # Create/readback GET needs existence; update GET also
                    # validates the modified value with a separate callback.
                    if update:
                        lines += ['if(stage==="update") ' + request(
                            ep.get_op, context='step.data.values',
                            changed_field=update_field, changed_value=update_value,
                            config_map_keys=config_keys)]
                    if race:
                        lines += ['if(stage==="race") ' + request(
                            ep.get_op, context='step.data.values',
                            race_expectation=(race_rv, update_field, race_field),
                            config_map_keys=config_keys)]
                    if 404 in ep.get_op.error_codes:
                        lines += ['if(stage==="delete") ' + request(
                            ep.get_op, context='step.data.values', expected=[404])]
                lines += ['sync({request:Event("SBT:CrudVerified",{owner:' + tag +
                          ',stage:stage,ok:true})});', '}', '});']
                has_lookup = (bool(ep.key.fields) and
                              ep.key.fields[-1].lower().endswith(('id', 'uuid')) and
                              any(op.kind == 'list' and any(q in op.query_params and
                                      safe_identifier(q) in ep.create_op.params
                                      for q in ('username', 'name', 'alias')) for op in ep.ops))
                if has_lookup:
                    lines += [
                        'bthread("verify-lookup:' + owner + '", function(){',
                        'let step=sync({waitFor:EventSet("lookup-or-finish:' + owner + '",function(e){'
                        'return e.data && e.data.owner===' + tag +
                        ' && ((e.name==="SBT:CrudStep" && e.data.stage==="lookup")'
                        ' || e.name==="SBT:WorkerFinished");})});',
                        'if(step.name==="SBT:CrudStep")'
                        ' sync({request:Event("SBT:CrudVerified",{owner:' + tag +
                        ',stage:"lookup",ok:true})});',
                        '});',
                    ]
                lines += ['bthread("crud:' + owner + '", function() {',
                          'let __args={}; let __parentBindings={};',
                          'function finish(reason){ sync({request:Event("SBT:WorkerFinished",'
                          '{process:' + str(process) + ',entity:' + js_string(key) +
                          ',owner:' + tag + ',reason:reason})}); }',
                          'function verified(stage){ sync({request:Event("SBT:CrudStep",'
                          '{owner:' + tag + ',process:' + str(process) +
                          ',entity:' + js_string(key) + ',stage:stage,'
                          'values:Object.assign({},__args)})});'
                          'sync({waitFor:EventSet("verified:' + owner + '",function(e){'
                          'return e.name==="SBT:CrudVerified" && e.data.owner===' + tag +
                          ' && e.data.stage===stage;})}); }']
                if deps:
                    lines += [
                        'let bound=sync({waitFor:EventSet("bound:' + owner + '",function(e){'
                        'return e.name==="SBT:ParentsBound" && e.data.owner===' + tag + ';})});',
                        '__parentBindings=bound.data.parents;',
                    ]
                for dep in deps:
                    lines += ['{',
                              'if(__args.realm===undefined && __parentBindings[' + js_string(dep) +
                              '].realm!==undefined) __args.realm=__parentBindings[' + js_string(dep) + '].realm;']
                    for edge in ep.dependencies:
                        if edge.target == dep:
                            field = safe_identifier(edge.field_name)
                            target_key = (field if field in {safe_identifier(k) for k in by_key[dep].key.fields}
                                          else safe_identifier(by_key[dep].key.fields[-1]))
                            lines += ['__args[' + js_string(field) + ']='
                                      '__parentBindings[' + js_string(dep) + '][' +
                                      js_string(target_key) + '];']
                    lines.append('}')
                declarations, values = _minimal_values(
                    ep.create_op, prefix, plan.seed,
                    dependency_values={safe_identifier(e.field_name):
                                       _arg(e.field_name) for e in ep.dependencies if e.target in deps})
                lines.extend(declarations)
                for field, expr in values.items():
                    lines.append('__args[' + js_string(field) + ']=' + expr + ';')
                media, create_schema = select_request_variant(ep.create_op.op)
                for raw, schema in (create_schema.get('properties', {})
                                    if isinstance(create_schema, dict) else {}).items():
                    field = safe_identifier(raw)
                    if (field not in values and field not in ('realm',) and
                            field in ('username', 'clientId', 'name', 'alias') and
                            field in ep.create_op.params and isinstance(schema, dict) and
                            schema.get('type') == 'string' and not schema.get('readOnly')):
                        lines.append('__args[' + js_string(field) + ']=' + _value_js(generate_value(
                            schema, plan.seed, 'parallel-crud.' + owner + '.create.' + field,
                            for_request=True)) + ';')
                        values[field] = 'seeded'
                opaque = None
                if ep.create_op.op.request_body and not ep.create_op.body_props:
                    if key == 'admin/realms' and ep.key.fields == ['realm']:
                        realm = generate_value({'type': 'string'}, plan.seed,
                                               'parallel-crud.' + owner + '.realm', for_request=True)
                        lines.append('__args.realm=' + _value_js(realm) + ';')
                        opaque = '{realm:__args.realm,enabled: true}'
                        values['realm'] = 'seeded'
                    else:
                        edge = next((e for e in ep.dependencies
                                     if any(p.rule == 'D5:primitive_association_id_description'
                                            for p in e.provenance)), None)
                        if edge is None:
                            raise ValueError('Opaque body has no inferred parent ID: ' + key)
                        opaque = _arg(edge.field_name)
                setup = request_rules.get(ep.create_op.op.method + ' ' + ep.create_op.op.path, {}).get('setup_create')
                if setup:
                    setup_op = next(op for entity in plan.entities for op in entity.ops
                                    if op.op.method + ' ' + op.op.path == setup['operation'])
                    setup_rv = _rv(owner, 'setup_' + setup['capture_field'])
                    setup_values = dict(setup['body'])
                    setup_values['alias'] = 'sbt_parent_' + safe_identifier(owner)
                    setup_body = 'JSON.stringify(' + _rule_expression(setup_values, '__args') + ')'
                    lines.append(request(setup_op, override_body=setup_body,
                                         capture=(setup_rv, setup['capture_field'])))
                    lines.append('__args[' + js_string('parentFlow') + ']=' +
                                 js_string('@{' + setup_rv + '}') + ';')
                own = safe_identifier(ep.key.fields[-1]) if ep.key.fields else None
                known = set(values) | {safe_identifier(e.field_name) for e in ep.dependencies}
                needs_capture = bool(own and own not in known)
                own_rv = _rv(owner, own) if needs_capture else None
                lookup_op = next((op for op in ep.ops if op.kind == 'list' and
                                  any(q in op.query_params and safe_identifier(q) in values
                                      for q in ('username', 'name', 'alias'))), None)
                lookup_label = next((q for q in ('username', 'name', 'alias') if lookup_op and
                                     q in lookup_op.query_params and safe_identifier(q) in values), None)
                use_lookup = bool(needs_capture and lookup_label and own.lower().endswith(('id', 'uuid')))
                if use_lookup and not has_lookup:
                    raise ValueError('Lookup schedule lacks a verifier for ' + owner)
                lines.append(request(ep.create_op, opaque=opaque,
                                      capture=(own_rv, own) if needs_capture and not use_lookup else None))
                if use_lookup:
                    expected_rv = _rv(owner, 'lookup_' + lookup_label)
                    lines.append('rtv.doStore(' + js_string(expected_rv) +
                                 ',' + _arg(lookup_label) + ');')
                    query = {lookup_label: _arg(lookup_label)}
                    if 'exact' in lookup_op.query_params:
                        query['exact'] = 'true'
                    lines.append(request(lookup_op, lookup=(own_rv, lookup_label,
                                                               expected_rv),
                                          query_overrides=query))
                    lines.append('verified("lookup");')
                if needs_capture:
                    lines.append('__args[' + js_string(own) + ']=' +
                                 js_string('@{' + own_rv + '}') + ';')
                for field in ep.key.fields:
                    name = safe_identifier(field)
                    if name not in known and name != own:
                        raise ValueError('Unbound composite key field ' + name + ' for ' + key)
                if ep.get_op:
                    lines += [request(ep.get_op), 'verified("readback");']
                lines += ['verified("create");',
                          'sync({request:Event("SBT:InstanceReady",{process:' + str(process) +
                          ',entity:' + js_string(key) + ',owner:' + tag +
                          ',values:Object.assign({},__args)})});']
                if ep.get_op:
                    lines += [request(ep.get_op, store_body=body_rv,
                                       build_update=(update_body_rv, update_field, update_value)
                                       if update else None, config_map_keys=config_keys), 'verified("read");']
                if update:
                    op = update[5]
                    if (request_rules.get(op.op.method + ' ' + op.op.path, {})
                            .get('refresh_update')):
                        if ep.get_op is None:
                            raise ValueError('Update refresh requires a GET: ' + key)
                        lines.append(request(ep.get_op,
                                             build_update=(update_body_rv, update_field,
                                             update_value), config_map_keys=config_keys))
                    if op.op.method == 'PATCH':
                        changed = 'JSON.stringify({' + js_string(update_field) + ':' + update_value + '})'
                    else:
                        changed = js_string('@{' + update_body_rv + '}')
                    lines += [request(op, override_body=changed), 'verified("update");']
                if race:
                    expected = update[5].success_codes
                    race_callback = (
                        'var result; try { result=JSON.parse(response.body); }'
                        ' catch(err) { pvg.fail("race response JSON invalid"); return; }'
                        'if(!result.overlap) { pvg.fail("race HTTP intervals did not overlap"); return; }'
                        'if(' + _value_js(expected) + '.indexOf(result.A)<0 || ' +
                        _value_js(expected) + '.indexOf(result.B)<0)'
                        ' { pvg.fail("race update returned unexpected status"); return; }'
                        'pvg.success("two HTTP updates overlapped");'
                    )
                    race_request = (
                        'svc.post("/__sbt_race?path="+(' + _url(update[5]) + ')+' +
                        js_string('&__sbt_event=' + safe_identifier(owner)) + ',{' +
                        'headers:{Authorization:' +
                        js_string('Bearer @{getEnv(\'' + (auth_token_env or 'ACCESS_TOKEN') + '\')}') +
                        ',"Content-Type":"application/json"},'
                        'body:' + js_string('@{' + race_rv + '}') +
                        ',expectedResponseCodes:[200],callback:new Function("response",' +
                        js_string(race_callback) + ')});'
                    )
                    if transport_registry is not None:
                        race_request = transport_registry.add(race_request, ['__args'], ['__args'], race_request,
                                                              operation='legacy configured coordinator')
                    lines += [
                        request(ep.get_op, race_prepare=(race_rv, update_field,
                                                          race_first_value, race_field, race_value),
                                config_map_keys=config_keys),
                        race_request,
                        'verified("race");',
                    ]
                if child_keys:
                    lines += ['sync({request:Event("SBT:CleanupReady",{owner:' + tag + '})});',
                              'sync({waitFor:EventSet("children-done:' + owner + '",function(e){'
                              'return e.name==="SBT:ChildrenFinished" && e.data.owner===' +
                              tag + ';})});']
                if ep.delete_op:
                    lines += [request(ep.delete_op), 'verified("delete");']
                lines += ['finish("complete");', '});']
    return '\n'.join(lines) + '\n'
