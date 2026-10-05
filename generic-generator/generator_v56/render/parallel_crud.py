"""Opt-in concurrent CRUD stories, with independently scheduled observers."""
from __future__ import annotations

from .naming import js_string, safe_identifier
from ..request_variants import select_request_variant
from .stories_js import (_minimal_values, _op_args,
                         _request_body_schemas_for_operation,
                         _select_update_operation, _value_js)
from ..inference.values import generate_value


def _parallel_update_choice(entity):
    """Prefer descriptive fields over identity and enablement controls."""
    candidates = []
    own_keys = {safe_identifier(key) for key in entity.key.fields}
    preferred = ('firstName', 'lastName', 'description', 'displayName',
                 'consentText', 'name', 'alias')
    for op in entity.ops:
        if op.kind != 'update' or op.op.method not in ('PUT', 'PATCH'):
            continue
        for raw, schema in _request_body_schemas_for_operation(op).items():
            field = safe_identifier(raw)
            if (field in own_keys or field not in preferred or
                    schema.get('type') != 'string' or schema.get('enum') or
                    schema.get('readOnly') or schema.get('format')):
                continue
            candidates.append((preferred.index(field), 0 if op.op.method == 'PUT' else 1,
                               field, raw, schema, op))
    if candidates:
        return min(candidates, key=lambda item: (item[0], item[1], item[5].js_name))
    fallback = _select_update_operation(entity)
    if fallback and fallback[2] not in ('enabled', 'builtIn', 'clientRole',
                                         'identityProviderAlias', 'alias'):
        return fallback
    return None


def render_parallel_crud(plan, slug: str, processes: int) -> str:
    if processes < 1 or processes > 8:
        raise ValueError("logical processes must be between 1 and 8")
    if plan.instances_per_entity < 1:
        raise ValueError("instances per entity must be positive")
    by_key = {ep.entity.key: ep for ep in plan.entities}
    children = {key: [] for key in by_key}
    for ep in plan.entities:
        for edge in ep.dependencies:
            if edge.target in by_key and by_key[edge.target].create_op:
                children[edge.target].append(ep.entity.key)
    lines = [
        f'// Auto-generated parallel CRUD stories for {slug}; each process is logical.',
        '// @provengo summon rest',
        '// @provengo summon rtv',
        'const SBT_POOL = {};',
        'const SBT_FINISHED = {};',
        'bthread("parallel-crud:state", function() {',
        '  while (true) {',
        '    let e = sync({waitFor: EventSet("parallel CRUD state", function(x) {',
        '      return x.name === "SBT:InstanceReady" || x.name === "SBT:WorkerFinished";',
        '    })});',
        '    let k = e.data.process + ":" + e.data.entity;',
        '    if (e.name === "SBT:InstanceReady") {',
        '      if (!SBT_POOL[k]) SBT_POOL[k] = [];',
        '      SBT_POOL[k].push({owner:e.data.owner, values:e.data.values});',
        '    } else {',
        '      if (!SBT_FINISHED[k]) SBT_FINISHED[k] = {};',
        '      SBT_FINISHED[k][e.data.owner] = true;',
        '      if (SBT_POOL[k]) SBT_POOL[k] = SBT_POOL[k].filter(function(x) { return x.owner !== e.data.owner; });',
        '    }',
        '  }',
        '});',
    ]
    for process in range(1, processes + 1):
        for key in plan.graph.creation_order:
            ep = by_key.get(key)
            if not ep or not ep.create_op:
                continue
            deps = sorted({edge.target for edge in ep.dependencies
                           if edge.target in by_key and by_key[edge.target].create_op},
                          key=lambda target: (-target.count('/'), target))
            for instance in range(1, plan.instances_per_entity + 1):
                label = f"P{process}:{key}:{instance}"
                tag = js_string(label)
                prefix = f"p{process}_{safe_identifier(key.replace('/', '_').replace('{', '').replace('}', ''))}_{instance}"
                available_stages = (['readback'] if ep.get_op else []) + ['create']
                if ep.get_op:
                    available_stages.append('read')
                update_choice = _parallel_update_choice(ep)
                if update_choice and ep.get_op:
                    available_stages.append('update')
                if ep.delete_op:
                    available_stages.append('delete')
                lookup_op = next((op for op in ep.ops if op.kind == 'list' and
                                  any(label in op.query_params and label in ep.create_op.params
                                      for label in ('username', 'name', 'alias')) and
                                  ep.key.fields and
                                  ep.key.fields[-1].lower().endswith(('id', 'uuid'))), None)
                lookup_label = (next((label for label in ('username', 'name', 'alias')
                                      if label in lookup_op.query_params and label in ep.create_op.params), None)
                                if lookup_op else None)

                # Every verifier starts at the first synchronization point,
                # before any worker can emit its first observation event.
                lines.extend([
                    f'bthread("verify:{label}", function() {{',
                    '  for (let stage of ' + _value_js(available_stages) + ') {',
                    '    let step = sync({waitFor: EventSet("step-or-finish:' + label + '", function(e) {',
                    '      return e.data && e.data.owner === ' + tag +
                    ' && ((e.name === "SBT:CrudStep" && e.data.stage === stage) || e.name === "SBT:WorkerFinished");',
                    '    })});',
                    '    if (step.name === "SBT:WorkerFinished") return;',
                    '    let ok = step.data.success;',
                ])
                if ep.get_op:
                    get = ep.get_op
                    get_args = _op_args(get, {p: f'step.data.values[{js_string(p)}]' for p in get.params})
                    lines.extend([
                        '    if (ok && stage === "readback") {',
                        '      ok = ' + _value_js(get.success_codes) + '.indexOf(step.data.code) >= 0;',
                        '    }',
                        '    if (ok && (stage === "create" || stage === "update")) {',
                        f'      let check = {get.js_name}({get_args}, {tag} + ":verifier:" + stage);',
                        '      ok = !!check && ' + _value_js(get.success_codes) + '.indexOf(check.code) >= 0;',
                        '      if (ok && stage === "update" && step.data.changedField &&',
                        '          check.body && typeof check.body === "object") {',
                        '        ok = check.body[step.data.changedField] === step.data.changedValue;',
                        '      }',
                        '    }',
                    ])
                    if 404 in get.error_codes:
                        lines.extend([
                            '    if (ok && stage === "delete") {',
                            f'      let gone = {get.js_name}({get_args}, {tag} + ":verifier:delete");',
                            '      ok = !!gone && gone.code === 404;',
                            '    }',
                        ])
                lines.extend([
                    '    sync({request:Event("SBT:CrudVerified", {owner:' + tag +
                    ',stage:stage,ok:ok})});',
                    '    if (!ok) return;',
                    '  }',
                    '});',
                ])
                if lookup_op:
                    lines.extend([
                        f'bthread("verify-lookup:{label}", function() {{',
                        '  let e = sync({waitFor: EventSet("lookup-or-finish:' + label + '", function(x) {',
                        '    return x.data && x.data.owner === ' + tag +
                        ' && ((x.name === "SBT:CrudStep" && x.data.stage === "lookup") || x.name === "SBT:WorkerFinished");',
                        '  })});',
                        '  if (e.name === "SBT:CrudStep") {',
                        '    sync({request:Event("SBT:CrudVerified", {owner:' + tag +
                        ',stage:"lookup",ok:e.data.success})});',
                        '  }',
                        '});',
                    ])
                lines.extend([
                    f'bthread("crud:{label}", function() {{',
                    '  let __args = {};',
                    '  let __parentBindings = {};',
                    '  function finish(reason) {',
                    '    sync({request:Event("SBT:WorkerFinished", {process:' + str(process) +
                    ',entity:' + js_string(key) + ',owner:' + tag + ',reason:reason})});',
                    '  }',
                    '  function verified(stage, result, success, changedField, changedValue) {',
                    '    sync({request:Event("SBT:CrudStep", {owner:' + tag +
                    ',process:' + str(process) + ',entity:' + js_string(key) +
                    ',stage:stage,code:result ? result.code : null,success:success,' +
                    'values:Object.assign({}, __args),changedField:changedField,changedValue:changedValue})});',
                    '    let e = sync({waitFor: EventSet("verification:' + label + '", function(x) {',
                    '      return x.name === "SBT:CrudVerified" && x.data.owner === ' + tag +
                    ' && x.data.stage === stage;',
                    '    })});',
                    '    return e.data.ok;',
                    '  }',
                ])
                for dep in deps:
                    target = by_key[dep]
                    pool_key = f"{process}:{dep}"
                    lines.extend([
                        '  // Choose any verified parent, with an independent choice in the sample.',
                        '  {',
                        '  function matchingParents() {',
                        '    return (SBT_POOL[' + js_string(pool_key) + '] || []).filter(function(parent) {',
                        '      return __args.realm === undefined || parent.values.realm === __args.realm;',
                        '    });',
                        '  }',
                        '  while (!matchingParents().length) {',
                        '    if (SBT_FINISHED[' + js_string(pool_key) + '] && Object.keys(SBT_FINISHED[' + js_string(pool_key) + ']).length === ' + str(plan.instances_per_entity) + ') {',
                        '      finish("parent-unavailable"); return;',
                        '    }',
                        '    sync({waitFor: EventSet("parent:' + label + '", function(e) {',
                        '      return (e.name === "SBT:InstanceReady" || e.name === "SBT:WorkerFinished") &&',
                        '        e.data.process === ' + str(process) + ' && e.data.entity === ' + js_string(dep) + ';',
                        '    })});',
                        '  }',
                        '  let __candidates = matchingParents();',
                        '  let __options = __candidates.map(function(parent, ix) {',
                        '    return Event("SBT:BindParent", {child:' + tag + ',type:' + js_string(dep) + ',index:ix});',
                        '  });',
                        '  let __picked = sync({request:__options});',
                        '  __parentBindings[' + js_string(dep) + '] = __candidates[__picked.data.index].values;',
                        '  if (__args.realm === undefined && __parentBindings[' + js_string(dep) + '].realm !== undefined) {',
                        '    __args.realm = __parentBindings[' + js_string(dep) + '].realm;',
                        '  }',
                    ])
                    for edge in ep.dependencies:
                        if edge.target != dep:
                            continue
                        field = safe_identifier(edge.field_name)
                        parent_key = safe_identifier(target.key.fields[-1]) if target.key.fields else field
                        if field in {safe_identifier(value) for value in target.key.fields}:
                            parent_key = field
                        lines.append('  __args[' + js_string(field) + '] = __parentBindings[' + js_string(dep) + '][' + js_string(parent_key) + '];')
                    lines.append('  }')
                declarations, values = _minimal_values(
                    ep.create_op, prefix, plan.seed,
                    dependency_values={safe_identifier(e.field_name):
                                       f'__args[{js_string(safe_identifier(e.field_name))}]'
                                       for e in ep.dependencies if e.target in deps})
                # Many real OpenAPI create schemas mark a distinctive name as
                # optional although the server requires it (Keycloak users:
                # username). Seed documented identity labels per worker.
                _media, create_schema = select_request_variant(ep.create_op.op)
                properties = create_schema.get('properties', {}) if isinstance(create_schema, dict) else {}
                for raw, schema in properties.items():
                    field = safe_identifier(raw)
                    if (field in values or field not in ep.create_op.params or
                            field not in ('username', 'clientId', 'name', 'alias') or
                            not isinstance(schema, dict) or schema.get('type') != 'string' or
                            schema.get('readOnly')):
                        continue
                    values[field] = _value_js(generate_value(
                        schema, plan.seed, f'parallel-crud.{label}.create.{field}',
                        for_request=True))
                lines.extend(declarations)
                for field, expression in values.items():
                    lines.append('  __args[' + js_string(field) + '] = ' + expression + ';')
                create = ep.create_op
                opaque = create.op.request_body and not create.body_props and any(
                    v.schema.get('type') == 'string' for v in create.op.request_body.variants)
                extra = ''
                if opaque:
                    primitive_edge = next((edge for edge in ep.dependencies if any(
                        source.rule == 'D5:primitive_association_id_description'
                        for source in edge.provenance)), None)
                    if primitive_edge:
                        extra = ', __args[' + js_string(safe_identifier(primitive_edge.field_name)) + ']'
                    elif ep.entity.key == 'admin/realms' and ep.key.fields == ['realm']:
                        # Explicitly isolated empirical Keycloak fixture:
                        # the prior live gate created realms with this body.
                        realm_name = generate_value({'type': 'string'}, plan.seed,
                                                    f'parallel-crud.{label}.realm', for_request=True)
                        lines.append('  __args.realm = ' + _value_js(realm_name) + ';')
                        extra = ', {realm: __args.realm, enabled: true}'
                    else:
                        raise ValueError('Opaque create body lacks a contract-derived association '
                                         'or a verified realm fixture: ' + create.op.path)
                lines.append(f'  let created = {create.js_name}({_op_args(create, {p: f"__args[{js_string(p)}]" for p in create.params})}, {tag} + ":create"{extra});')
                lines.append('  if (!created || ' + _value_js(create.success_codes) + '.indexOf(created.code) < 0) { finish("create-failed"); return; }')
                for field in ep.key.fields:
                    name = safe_identifier(field)
                    lines.extend([
                        '  if (__args[' + js_string(name) + '] === undefined || __args[' + js_string(name) + '] === null) {',
                        '    let response = created.body;',
                        '    __args[' + js_string(name) + '] = response && typeof response === "object" ?',
                        '      (response[' + js_string(name) + '] === undefined ? response.__sbtObservedLocationId : response[' + js_string(name) + ']) : undefined;',
                        '  }',
                    ])
                    if field == ep.key.fields[-1] and lookup_op:
                        lookup_values = {p: f'__args[{js_string(p)}]' for p in lookup_op.params}
                        if 'exact' in lookup_op.query_params:
                            lookup_values['exact'] = 'true'
                        lines.extend([
                            '  if (__args[' + js_string(name) + '] === undefined || __args[' + js_string(name) + '] === null) {',
                            f'    let lookup = {lookup_op.js_name}({_op_args(lookup_op, lookup_values)}, {tag} + ":lookup");',
                            '    let items = lookup && Array.isArray(lookup.body) ? lookup.body : [];',
                            '    let matches = items.filter(function(x) { return x && x[' + js_string(lookup_label) + '] === __args[' + js_string(lookup_label) + ']; });',
                            '    let lookupOk = !!lookup && ' + _value_js(lookup_op.success_codes) + '.indexOf(lookup.code) >= 0 &&',
                            '      matches.length === 1 && matches[0].id !== undefined && matches[0].id !== null;',
                            '    if (!verified("lookup", lookup, lookupOk)) { finish("lookup-failed"); return; }',
                            '    __args[' + js_string(name) + '] = matches[0].id;',
                            '  }',
                        ])
                    lines.append('  if (__args[' + js_string(name) + '] === undefined || __args[' + js_string(name) + '] === null) { finish("create-id-unresolved"); return; }')
                if ep.get_op:
                    get = ep.get_op
                    get_args = _op_args(get, {p: f'__args[{js_string(p)}]' for p in get.params})
                    lines.extend([
                        f'  let bound = {get.js_name}({get_args}, {tag} + ":bind");',
                        '  if (!bound || ' + _value_js(get.success_codes) + '.indexOf(bound.code) < 0) { finish("create-readback-failed"); return; }',
                        '  if (bound.body && typeof bound.body === "object") {',
                    ])
                    for field in ep.key.fields:
                        name = safe_identifier(field)
                        lines.append('    if (bound.body[' + js_string(name) + '] !== undefined && bound.body[' + js_string(name) + '] !== __args[' + js_string(name) + ']) { finish("create-id-mismatch"); return; }')
                    if ep.key.fields and (ep.key.fields[-1].lower().endswith(('id', 'uuid'))):
                        own_key = safe_identifier(ep.key.fields[-1])
                        lines.append('    if (bound.body.id !== undefined && bound.body.id !== __args[' + js_string(own_key) + ']) { finish("create-id-mismatch"); return; }')
                    lines.append('  }')
                    lines.append('  if (!verified("readback", bound, true)) { finish("create-readback-verification-failed"); return; }')
                lines.append('  if (!verified("create", created, true)) { finish("create-verification-failed"); return; }')
                for field in ep.key.fields:
                    name = safe_identifier(field)
                    lines.append('  rtv.doStore(' + js_string(label + ':' + name) + ', __args[' + js_string(name) + ']);')
                lines.append('  sync({request:Event("SBT:InstanceReady", {process:' + str(process) + ',entity:' + js_string(key) + ',owner:' + tag + ',values:Object.assign({},__args)})});')
                if ep.get_op:
                    lines.extend([
                        f'  let read = {ep.get_op.js_name}({get_args}, {tag} + ":read");',
                        '  if (!verified("read", read, !!read && ' + _value_js(ep.get_op.success_codes) + '.indexOf(read.code) >= 0)) { finish("read-failed"); return; }',
                    ])
                if update_choice and ep.get_op:
                    _, _, field, raw_field, schema, op = update_choice
                    # Carry documented writable properties from an observed
                    # item GET; change one scalar field per worker.
                    lines.append('  if (read.body && typeof read.body === "object") {')
                    for param in op.body_props:
                        lines.append('    if (read.body[' + js_string(param) + '] !== undefined) __args[' + js_string(param) + '] = read.body[' + js_string(param) + '];')
                    lines.append('  }')
                    if schema.get('type') == 'boolean':
                        new_value = f'!Boolean(__args[{js_string(field)}])'
                    else:
                        new_value = _value_js(generate_value(schema, plan.seed, f'parallel-crud.{label}.{field}', for_request=True))
                    lines.append('  __args[' + js_string(field) + '] = ' + new_value + ';')
                    update_args = _op_args(op, {p: f'__args[{js_string(p)}]' for p in op.params})
                    lines.extend([
                        f'  let changed = {op.js_name}({update_args}, {tag} + ":update");',
                        '  if (!verified("update", changed, !!changed && ' + _value_js(op.success_codes) + '.indexOf(changed.code) >= 0,' + js_string(field) + ',__args[' + js_string(field) + '])) { finish("update-failed"); return; }',
                    ])
                # A parent stays alive until every potential child worker in
                # the same logical process has completed (including skips).
                for child in sorted(set(children[key])):
                    pool_key = f"{process}:{child}"
                    lines.extend([
                        '  while (!SBT_FINISHED[' + js_string(pool_key) + '] || Object.keys(SBT_FINISHED[' + js_string(pool_key) + ']).length < ' + str(plan.instances_per_entity) + ') {',
                        '    sync({waitFor: EventSet("child:' + label + '", function(e) {',
                        '      return e.name === "SBT:WorkerFinished" && e.data.process === ' + str(process) + ' && e.data.entity === ' + js_string(child) + ';',
                        '    })});',
                        '  }',
                    ])
                if ep.delete_op:
                    op = ep.delete_op
                    lines.extend([
                        f'  let deleted = {op.js_name}({_op_args(op, {p: f"__args[{js_string(p)}]" for p in op.params})}, {tag} + ":delete");',
                        '  if (!verified("delete", deleted, !!deleted && ' + _value_js(op.success_codes) + '.indexOf(deleted.code) >= 0)) { finish("delete-failed"); return; }',
                    ])
                lines.extend(['  finish("complete");', '});'])
    return '\n\n'.join(lines) + '\n'
