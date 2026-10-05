"""CLI for OpenAPI-only verifier/concurrency generation."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

from .parsing.loader import load_and_resolve, load_raw
from .parsing.normalize import normalize
from .verification import derive_verification
from .cross_method import discover as discover_cross_method, empirical_update_delete
from .render.verification_js import render_verification_js
from .combined_oracles import compose as compose_combined


def order_empirical_oracles_by_dependencies(oracles, graph):
    """Order destructive experiments by transitive OpenAPI creation dependencies."""
    edges = {}
    for edge in graph.get('edges', []):
        source, target = edge.get('source'), edge.get('target')
        if (edge.get('confidence', 0) >= 0.9 and isinstance(source, str)
                and isinstance(target, str) and source != target):
            edges.setdefault(source.strip('/'), set()).add(target.strip('/'))

    def reachable(source, target):
        pending, visited = list(edges.get(source, ())), set()
        while pending:
            node = pending.pop()
            if node == target:
                return True
            if node not in visited:
                visited.add(node)
                pending.extend(edges.get(node, ()))
        return False

    executable = [o for o in oracles
                  if o.get('runtime', {}).get('ready') and o['kind'] != 'update-delete-linearizable']
    entities = {o['runtime']['entity_key'].strip('/') for o in executable
                if o['kind'] == 'empirical-update-delete'}
    if any(reachable(entity, entity) for entity in entities):
        raise ValueError('OpenAPI dependency cycle among destructive concurrency oracles; '
                         'cannot safely schedule without additional evidence')
    for i, parent in enumerate(executable):
        if parent['kind'] != 'empirical-update-delete':
            continue
        parent_entity = parent['runtime']['entity_key'].strip('/')
        children = [j for j, child in enumerate(executable)
                    if i != j and child['kind'] == 'empirical-update-delete'
                    and reachable(child['runtime']['entity_key'].strip('/'), parent_entity)]
        if children:
            parent['runtime']['wait_for_closed_oracles'] = children


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="openapi_to_sbt.verification_cli")
    parser.add_argument("--openapi", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--max-field-pairs", type=int, default=6)
    parser.add_argument("--max-concurrency-width", type=int, choices=(2, 3), default=3,
                        help="Maximum same-resource operations in a generated epoch (default 3)")
    parser.add_argument("--json-disjoint", action="store_true",
                        help="Opt in to JSON PATCH disjoint-field candidates guarded by two serial orders")
    parser.add_argument("--combined-campaign", action="store_true",
                        help="Generate opt-in NO-OP, disjoint PUT, and cross-entity scenarios")
    parser.add_argument("--cross-method-discovery", action="store_true",
                        help="Write an OpenAPI-derived cross-method proof-gap inventory; no candidate is marked executable")
    parser.add_argument("--empirical-update-delete", action="store_true",
                        help="Opt in to PATCH/DELETE histories with three isolated created items and serial controls")
    parser.add_argument("--empirical-update-delete-put", metavar="OPERATION_ID",
                        help="Experimental full read-derived PUT/DELETE, one OpenAPI operationId")
    parser.add_argument("--generation-report",
                        help="Generator report with the canonical InstanceReady entity labels")
    parser.add_argument("--prefix-before-concurrency", type=int, default=0,
                        help="Require this many verified same-resource rounds before each epoch (0 disables)")
    parser.add_argument("--post-join-observation", action="store_true",
                        help="Use an adapter-owned read under a same-resource HTTP lease")
    parser.add_argument("--require-serial-controls", action="store_true",
                        help="Skip epochs whose generated serial operations do not succeed")
    parser.add_argument("--exclude-concurrency-operation", action="append", default=[],
                        help="Omit concurrency candidates for this OpenAPI operationId; contract and state verifiers remain")
    parser.add_argument("--include-concurrency-operation", action="append", default=[],
                        help="Run only matching concurrency operationIds; contract and state verifiers remain")
    parser.add_argument("--include-concurrency-oracle", action="append", default=[],
                        help="Select exact OpenAPI-derived concurrency oracle IDs after composing optional families")
    parser.add_argument("--exclusive-control-lease", action="store_true",
                        help="Hold a concrete resource lease through the selected oracle's controls and epoch")
    parser.add_argument("--fail-on-contract-only", action="store_true")
    args = parser.parse_args(argv)
    if args.exclusive_control_lease and (len(args.include_concurrency_oracle) != 1 or
                                          not args.post_join_observation or
                                          not args.require_serial_controls):
        parser.error('--exclusive-control-lease requires one selected oracle, serial controls, and post-join observation')
    source = Path(args.openapi)
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    if not 0 <= args.prefix_before_concurrency <= 16:
        parser.error("--prefix-before-concurrency must be 0..16")
    if args.combined_campaign and (not args.prefix_before_concurrency or
                                   not args.require_serial_controls or
                                   not args.post_join_observation):
        parser.error('--combined-campaign requires positive prefix depth, serial controls, and leased post-join observations')
    try:
        resolved, unsupported = load_and_resolve(str(source))
        raw = load_raw(str(source))
        doc = normalize(resolved, raw)
        result = derive_verification(doc, source.read_bytes(), max(1, args.max_field_pairs),
                                     json_disjoint=args.json_disjoint)
        if args.empirical_update_delete or args.empirical_update_delete_put:
            if not args.generation_report:
                parser.error("--empirical-update-delete requires --generation-report")
            result['concurrency_oracles'] = empirical_update_delete(
                doc, allow_put=bool(args.empirical_update_delete_put),
                selected_operation=args.empirical_update_delete_put)
            if args.empirical_update_delete_put and (len(result['concurrency_oracles']) != 1 or
                                                     result['concurrency_oracles'][0]['method'] != 'PUT'):
                parser.error('PUT/DELETE target lacks documented create, complete item read, and writable field')
            generation_report = json.loads(Path(args.generation_report).read_text(encoding='utf-8'))
            entities = generation_report.get('entities', [])
            for oracle in result['concurrency_oracles']:
                matching = [entity for entity in entities if
                            entity.get('collection_path') == oracle['runtime']['entity_key'] and
                            entity.get('plural_display_name') and
                            any(op.get('source_pointer') == oracle['runtime']['create_source_pointer']
                                and op.get('kind') == 'create'
                                for op in entity.get('operations', []))]
                if len(matching) != 1:
                    raise ValueError('No unique generated InstanceReady entity for ' + oracle['oracle_id'])
                oracle['runtime']['instance_ready_label'] = matching[0]['plural_display_name']
            result['counts']['concurrency_oracles'] = len(result['concurrency_oracles'])
            result['policy']['empirical_update_delete'] = True
            if args.empirical_update_delete_put:
                result['policy']['empirical_update_delete_put'] = args.empirical_update_delete_put
            print('OPENAPI_EMPIRICAL_UPDATE_DELETE ready=%d' % len(result['concurrency_oracles']))
        if args.cross_method_discovery:
            candidates = discover_cross_method(doc)
            (out / f"cross-method-plan.{args.name}.json").write_text(
                json.dumps({"schema_version": 1, "candidates": candidates,
                            "runtime_ready": 0,
                            "policy": "discovery-only: serial controls and reference fixtures are required before execution"},
                           indent=2, sort_keys=True) + "\n", encoding="utf-8")
            print("OPENAPI_CROSS_METHOD_DISCOVERY candidates=%d relation=%d update_delete=%d ready=0" % (
                len(candidates), sum(x['family'] == 'relation-put-delete' for x in candidates),
                sum(x['family'] == 'update-delete' for x in candidates)))
        excluded = set(args.exclude_concurrency_operation)
        included = set(args.include_concurrency_operation)
        if included:
            original = result['concurrency_oracles']
            if included - {o['operation_id'] for o in original}:
                parser.error('No concurrency candidate for operationId: ' + ', '.join(sorted(included - {o['operation_id'] for o in original})))
            result['concurrency_oracles'] = [o for o in original if o['operation_id'] in included]
            result['counts']['concurrency_oracles'] = len(result['concurrency_oracles'])
            result['policy']['included_concurrency_operations'] = sorted(included)
        if excluded:
            original = result["concurrency_oracles"]
            known = {o["operation_id"] for o in original}
            if excluded - known:
                parser.error("No concurrency candidate for operationId: " + ", ".join(sorted(excluded - known)))
            result["concurrency_oracles"] = [o for o in original if o["operation_id"] not in excluded]
            result["counts"]["concurrency_oracles"] = len(result["concurrency_oracles"])
            result["policy"]["excluded_concurrency_operations"] = sorted(excluded)
        if args.max_concurrency_width != 3:
            result['concurrency_oracles'] = [o for o in result['concurrency_oracles']
                                             if o.get('width', o.get('width_range', [2, 2])[0])
                                             <= args.max_concurrency_width]
            for oracle in result['concurrency_oracles']:
                if 'width_range' in oracle:
                    oracle['width_range'][1] = min(oracle['width_range'][1],
                                                   args.max_concurrency_width)
            result['counts']['concurrency_oracles'] = len(result['concurrency_oracles'])
            result['policy']['max_concurrency_width'] = args.max_concurrency_width
        if args.combined_campaign:
            additional = compose_combined(result['concurrency_oracles'])
            result['concurrency_oracles'].extend(additional)
            result['counts']['concurrency_oracles'] = len(result['concurrency_oracles'])
            result['policy']['combined_campaign'] = True
        if args.include_concurrency_oracle:
            requested = set(args.include_concurrency_oracle)
            known = {oracle['oracle_id'] for oracle in result['concurrency_oracles']}
            if requested - known:
                parser.error('Unknown concurrency oracle ID: ' + ', '.join(sorted(requested - known)))
            result['concurrency_oracles'] = [oracle for oracle in result['concurrency_oracles']
                                             if oracle['oracle_id'] in requested]
            result['counts']['concurrency_oracles'] = len(result['concurrency_oracles'])
            result['policy']['included_concurrency_oracles'] = sorted(requested)
        if args.exclusive_control_lease:
            oracle = result['concurrency_oracles'][0]
            if oracle.get('kind') != 'disjoint-put-serial-outcomes' or not oracle.get('runtime', {}).get('ready'):
                parser.error('exclusive control lease requires one executable disjoint PUT oracle')
            oracle['exclusive_control_lease'] = True
            result['policy']['exclusive_control_lease'] = 'proxy-held-concrete-resource-controls-through-epoch'
        if args.empirical_update_delete or args.empirical_update_delete_put:
            # The regular generator already derives producer dependencies from
            # the OpenAPI create bodies. A child resource must finish its
            # destructive experiment before another oracle deletes its parent.
            graph_path = Path(args.generation_report).with_name('dependency_graph.json')
            graph = json.loads(graph_path.read_text(encoding='utf-8')) if graph_path.exists() else {}
            order_empirical_oracles_by_dependencies(result['concurrency_oracles'], graph)
        if args.prefix_before_concurrency:
            for oracle in result["concurrency_oracles"]:
                if oracle.get("runtime", {}).get("ready") and oracle["kind"] != "update-delete-linearizable":
                    oracle["prefix_min_rounds"] = args.prefix_before_concurrency
        if args.post_join_observation:
            result['policy']['post_join_observation'] = 'adapter-held-resource-http-lease'
        if args.require_serial_controls:
            result['policy']['require_serial_controls'] = True
        result["unsupported_refs"] = unsupported
        manifest = out / f"verification-manifest.{args.name}.json"
        coverage = out / f"verifier-coverage.{args.name}.json"
        concurrency = out / f"concurrency-plan.{args.name}.json"
        verification_js = out / f"verification.{args.name}.js"
        manifest.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        coverage.write_text(json.dumps({
            "schema_version": 1, "source": result["source"], "policy": result["policy"],
            "counts": result["counts"], "coverage_complete": result["coverage_complete"],
            "manual_assumptions": result["manual_assumptions"],
            "mutation_coverage": result["mutation_coverage"],
        }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        concurrency.write_text(json.dumps({
            "schema_version": 1, "source": result["source"], "policy": result["policy"],
            "oracles": result["concurrency_oracles"],
        }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        options = (["post-join-observation"] if args.post_join_observation else []) + (
            ["require-serial-controls"] if args.require_serial_controls else [])
        verification_js.write_text(render_verification_js(
            result, args.name, "long-interleaving" if args.combined_campaign else "full", *options),
            encoding="utf-8")
    except Exception as exc:
        print(f"ERROR: verifier generation failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"name": args.name, **result["counts"],
                      "coverage_complete": result["coverage_complete"]}, sort_keys=True))
    print("OPENAPI_VERIFIER_GENERATION_PASS")
    if args.fail_on_contract_only and result["counts"]["contract_only_mutations"]:
        print("OPENAPI_VERIFIER_STATE_COVERAGE_INCOMPLETE")
        return 3
    return 0 if result["coverage_complete"] and not unsupported else 3


if __name__ == "__main__":
    raise SystemExit(main())
