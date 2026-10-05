from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path

from . import __version__
from .isolation import InputAllowList, IsolationSession, IsolationViolation
from .pipeline import run_pipeline
from .reproducibility import build_reproducibility_block


def _write(path: str, content: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(content, encoding="utf-8")


def cmd_generate(args: argparse.Namespace) -> int:
    if not (1 <= args.long_story_min_rounds <= args.long_story_max_rounds <= 16):
        print("ERROR: long story rounds must satisfy 1 <= min <= max <= 16", file=sys.stderr)
        return 2
    if not 1 <= args.logical_processes <= 8:
        print("ERROR: logical processes must be between 1 and 8", file=sys.stderr)
        return 2
    if args.auth_token_env and not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", args.auth_token_env):
        print("ERROR: auth token environment variable name is invalid", file=sys.stderr)
        return 2
    out_dir = Path(args.output)
    interfaces_path = out_dir / f"interfaces.{args.name}.js"
    stories_path = out_dir / f"stories.{args.name}.js"
    report_path = out_dir / "generation_report.json"
    graph_path = out_dir / "dependency_graph.json"
    profile_path = getattr(args, 'relationship_profile', None)
    runtime_path = getattr(args, 'relationship_runtime', None)
    compile_requested = getattr(args, 'compile_relationships', False)
    maps_requested = getattr(args, 'resource_maps', False) or bool(profile_path)
    map_paths = [out_dir / (name + '.json') for name in
                 ('resource_catalog', 'operation_map', 'relationship_map')] if maps_requested else []
    if profile_path:
        map_paths.append(out_dir / 'relationship_scenario_plan.json')
    if compile_requested:
        map_paths.append(out_dir / 'relationship_compilation.json')

    existing = [p for p in (interfaces_path, stories_path, report_path, graph_path, *map_paths) if p.exists()]
    if existing and not args.force:
        print(f"ERROR: refusing to overwrite existing file(s) without --force: "
              f"{[str(p) for p in existing]}", file=sys.stderr)
        return 2

    allow_list = InputAllowList(allowed_files=[args.openapi])
    if profile_path:
        allow_list.add_file(profile_path)
    if runtime_path:
        allow_list.add_file(runtime_path)
    if args.overrides:
        allow_list.add_file(args.overrides)
    if args.verified_values:
        allow_list.add_file(args.verified_values)
    allow_list.add_dir(str(out_dir))

    overrides = None
    if args.overrides:
        overrides = json.loads(Path(args.overrides).read_text(encoding="utf-8"))
        if overrides.get('request_rules'):
            expected_hash = overrides.get('source_openapi_sha256')
            if expected_hash != hashlib.sha256(Path(args.openapi).read_bytes()).hexdigest():
                print('ERROR: request rules were reviewed for a different OpenAPI file',
                      file=sys.stderr)
                return 2

    # Keep the report path-independent.  Prior versions embedded absolute or
    # caller-selected output paths here, making otherwise identical generations
    # differ across folders.  Exact run paths belong in run_metadata.json, not
    # in the semantic generation report.
    source_sha256 = hashlib.sha256(Path(args.openapi).read_bytes()).hexdigest()
    cli_args = {
        "command": "generate",
        "source_openapi_sha256": source_sha256,
        "name": args.name, "base_url": args.base_url, "seed": args.seed,
        "instances_per_entity": args.instances_per_entity,
        "instances_per_action": args.instances_per_action,
        "story_profile": args.story_profile,
        "generator_version": __version__,
    }
    if compile_requested:
        if not profile_path or not runtime_path:
            print('ERROR: compilation requires relationship profile and runtime configuration.', file=sys.stderr)
            return 2
        cli_args['compile_relationships'] = True
        cli_args['relationship_profile_sha256'] = hashlib.sha256(Path(profile_path).read_bytes()).hexdigest()
        cli_args['relationship_runtime_sha256'] = hashlib.sha256(Path(runtime_path).read_bytes()).hexdigest()
    if args.story_profile == "parallel-crud":
        cli_args["logical_processes"] = args.logical_processes
    if overrides and overrides.get('request_rules'):
        cli_args['request_rules_sha256'] = hashlib.sha256(
            Path(args.overrides).read_bytes()).hexdigest()
    if args.auth_token_env:
        cli_args["auth_token_env"] = args.auth_token_env
    if (args.long_story_min_rounds, args.long_story_max_rounds) != (3, 6):
        cli_args["long_story_rounds"] = [args.long_story_min_rounds, args.long_story_max_rounds]
    if args.emit_prefix_witnesses:
        cli_args["emit_prefix_witnesses"] = True
    if args.json_delete_bodies:
        cli_args["json_delete_bodies"] = True
    if args.optional_enum_dependency_branch:
        cli_args["optional_enum_dependency_branch"] = True
    verified_values = None
    if args.verified_values:
        verified_values = json.loads(Path(args.verified_values).read_text(encoding="utf-8"))
        if not isinstance(verified_values, dict):
            print("ERROR: verified values must be a JSON object", file=sys.stderr)
            return 2
        cli_args["verified_values_sha256"] = hashlib.sha256(
            Path(args.verified_values).read_bytes()).hexdigest()
    if args.verified_update_carry:
        cli_args["verified_update_carry"] = sorted(set(args.verified_update_carry))

    try:
        with IsolationSession(allow_list) as session:
            try:
                result = run_pipeline(
                    args.openapi, args.name, args.base_url, args.seed,
                    allow_list=allow_list, overrides=overrides, cli_args=cli_args,
                    instances_per_entity=args.instances_per_entity,
                    instances_per_action=args.instances_per_action,
                    story_profile=args.story_profile,
                    long_rounds=(args.long_story_min_rounds, args.long_story_max_rounds),
                    emit_prefix_witnesses=args.emit_prefix_witnesses,
                    json_delete_bodies=args.json_delete_bodies,
                    optional_enum_dependency_branch=args.optional_enum_dependency_branch,
                    verified_values=verified_values,
                    verified_update_carry=tuple(sorted(set(args.verified_update_carry))),
                    logical_processes=args.logical_processes,
                    auth_token_env=args.auth_token_env,
                    include_resource_maps=maps_requested,
                    relationship_profile=json.loads(Path(profile_path).read_text(encoding='utf-8')) if profile_path else None,
                    compile_relationship_model=compile_requested,
                    relationship_runtime=json.loads(Path(runtime_path).read_text(encoding='utf-8')) if runtime_path else None,
                )
            finally:
                result_audit = session.audit
    except IsolationViolation as e:
        print(f"ERROR: isolation violation: {e}", file=sys.stderr)
        return 3
    except Exception as e:
        print(f"ERROR: generation failed: {e}", file=sys.stderr)
        return 1

    # Audit counts are retained without host-specific paths so the report is
    # byte-stable when the same input is generated in a different directory.
    result.generation_report["isolation_audit"] = {
        # Successful generation is allowed to depend only on explicitly
        # allow-listed inputs.  Do not encode the number/path of incidental
        # interpreter imports: that can vary by Python environment and is not
        # a semantic input.  Any denied read remains a hard generation error.
        "denied_file_count": len(result_audit.denied),
        "policy": "allow-listed OpenAPI/config inputs only; environment-specific paths excluded from deterministic report",
    }
    result.generation_report["reproducibility"] = build_reproducibility_block(
        source_sha256=source_sha256, generator_version=__version__,
        seed=args.seed, instances_per_entity=args.instances_per_entity,
        instances_per_action=args.instances_per_action, base_url=args.base_url,
        interfaces_js=result.interfaces_js, stories_js=result.stories_js,
        dependency_graph_report=result.dependency_graph_report,
    )

    _write(str(interfaces_path), result.interfaces_js)
    _write(str(stories_path), result.stories_js)
    _write(str(report_path), json.dumps(result.generation_report, indent=2, sort_keys=True))
    _write(str(graph_path), json.dumps(result.dependency_graph_report, indent=2, sort_keys=True))
    for map_path in map_paths:
        data = result.resource_maps[map_path.stem]
        data['source_openapi_sha256'] = source_sha256
        if map_path.stem == 'relationship_compilation':
            data['runtime_profile_sha256'] = hashlib.sha256(Path(runtime_path).read_bytes()).hexdigest()
        if map_path.stem == 'relationship_scenario_plan':
            data['profile_sha256'] = hashlib.sha256(Path(profile_path).read_bytes()).hexdigest()
        _write(str(map_path), json.dumps(data, indent=2, sort_keys=True))

    print(f"Generated:\n  {interfaces_path}\n  {stories_path}\n  {report_path}\n  {graph_path}")
    for map_path in map_paths:
        print('  ' + str(map_path))
    if result.doc.unsupported:
        print("WARNINGS (unsupported constructs):", file=sys.stderr)
        for w in result.doc.unsupported:
            print(f"  - {w}", file=sys.stderr)
    return 0


def cmd_inspect(args: argparse.Namespace) -> int:
    allow_list = InputAllowList(allowed_files=[args.openapi])
    report_dir = Path(args.report)
    allow_list.add_dir(str(report_dir))
    try:
        with IsolationSession(allow_list):
            result = run_pipeline(args.openapi, "inspect", "http://localhost:5000", 1,
                                   allow_list=allow_list,
                                   cli_args={"command": "inspect", "openapi": args.openapi})
    except Exception as e:
        print(f"ERROR: inspection failed: {e}", file=sys.stderr)
        return 1

    _write(str(report_dir / "generation_report.json"),
           json.dumps(result.generation_report, indent=2, sort_keys=True))
    _write(str(report_dir / "dependency_graph.json"),
           json.dumps(result.dependency_graph_report, indent=2, sort_keys=True))

    cov = result.generation_report["coverage"]
    print(f"Title: {result.doc.title}")
    print(f"Operations: {cov['total_operations']} total, {cov['covered_operations']} coverable")
    print(f"Entities inferred: {len(result.plan.entities)}")
    if result.doc.unsupported:
        print("Unsupported constructs:")
        for w in result.doc.unsupported:
            print(f"  - {w}")
    print(f"Full report written to {report_dir / 'generation_report.json'}")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    from .validate.static_validate import validate_generated
    result = validate_generated(args.openapi, args.generated)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("ok") else 1


def cmd_compare_reference(args: argparse.Namespace) -> int:
    from .compare.reference_comparator import run_comparison
    result = run_comparison(
        openapi_path=args.openapi, generated_dir=args.generated,
        reference_stories=args.reference_stories, reference_interfaces=args.reference_interfaces,
        report_dir=args.report,
    )
    print(f"compare-reference complete. Reports written to {args.report}")
    return 0 if result.get("mandatory_failures", 0) == 0 else 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="openapi_to_sbt")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="command", required=True)

    g = sub.add_parser("generate", help="Generate a Provengo SBT model from an OpenAPI contract.")
    g.add_argument("--openapi", required=True)
    g.add_argument("--output", required=True)
    g.add_argument("--name", required=True)
    g.add_argument("--base-url", required=True)
    g.add_argument("--seed", type=int, default=1)
    g.add_argument(
        "--instances-per-entity", type=int, default=1,
        help="Number of concurrent CRUD producer stories generated for every creatable entity (default: 1, "
             "i.e. the original single-instance-per-entity behavior). Values above 1 are a genuine opt-in "
             "enhancement: pass e.g. 5 explicitly for broader fan-out/cross-binding coverage. Left at the "
             "previous default of 5, this silently changed behavior for every existing caller that didn't "
             "pass the flag at all (including this project's own scripts/run_e2e.py and "
             "tests/integration/test_e2e.py) -- found because it broke the Todoist end-to-end test: a "
             "5-instance fan-out concentrates more section creates onto the same project instance than "
             "that SUT's own 'max 3 sections per project' business rule allows, a real interaction that was "
             "invisible at single-instance scale and has nothing to do with OpenAPI contract coverage.",
    )
    g.add_argument(
        "--instances-per-action", type=int, default=1,
        help="Number of repeated stories for non-CRUD actions (default: 1). See --instances-per-entity for "
             "why this defaults to the original behavior rather than silently changing it.",
    )
    g.add_argument(
        "--story-profile", choices=("full", "minimal-smoke", "validated-lifecycle", "validated-action-lifecycle", "validated-relation-lifecycle", "relation-kind-campaign", "interleaved-relational-lifecycle", "interleaved-relational-exploration", "multi-resource-interleaving", "multi-resource-verified-obligations", "multi-resource-verified-resources", "long-interleaving", "concurrency-breadth", "parallel-crud"), default="full",
        help="Story execution profile. minimal-smoke sends only required request fields, "
             "runs entity creation plus dependency-wired POST actions, and omits cleanup.",
    )
    g.add_argument("--force", action="store_true")
    g.add_argument("--resource-maps", action="store_true",
                   help="Emit evidence-bearing resource, operation and relationship maps without changing legacy stories.")
    g.add_argument("--relationship-profile", metavar='JSON',
                   help="Emit a review-only multi-instance relationship plan using a generic resource scope configuration.")
    g.add_argument("--compile-relationships", action='store_true',
                   help="Compile relationship tasks into actual Provengo stories with runtime-only identity binding.")
    g.add_argument("--relationship-runtime", metavar='JSON',
                   help="Contract-pinned generic bootstrap, writable defaults and externally qualified action bindings.")
    g.add_argument("--logical-processes", type=int, default=1,
                   help="Independent logical process groups in one parallel-crud sample (1..8).")
    g.add_argument("--auth-token-env", metavar="ENV_NAME",
                   help="Read a bearer token from this environment variable at REST actuation time.")
    g.add_argument("--long-story-min-rounds", type=int, default=3)
    g.add_argument("--long-story-max-rounds", type=int, default=6)
    g.add_argument("--emit-prefix-witnesses", action="store_true")
    g.add_argument("--json-delete-bodies", action="store_true",
                   help="Opt in to documented JSON DELETE request bodies in generated REST interfaces")
    g.add_argument("--optional-enum-dependency-branch", action="store_true",
                   help="Explore optional XId dependency when type enum includes X; require successful create and read")
    g.add_argument("--verified-values", help="Opt-in JSON operationId -> verified create string or action/update array body fields; use only serially confirmed fixtures")
    g.add_argument("--verified-update-carry", action="append", default=[], metavar="OPERATION_ID",
                   help="Opt in a serially verified update: carry identical writable scalar fields from the item GET")
    g.add_argument("--overrides", help="Path to a JSON file of generic overrides for ambiguous constructs.")
    g.set_defaults(func=cmd_generate)

    i = sub.add_parser("inspect", help="Report entities/operations/ambiguities without writing JS.")
    i.add_argument("--openapi", required=True)
    i.add_argument("--report", required=True)
    i.set_defaults(func=cmd_inspect)

    v = sub.add_parser("validate", help="Static validation of generated output against the OpenAPI contract only.")
    v.add_argument("--openapi", required=True)
    v.add_argument("--generated", required=True)
    v.set_defaults(func=cmd_validate)

    c = sub.add_parser("compare-reference", help="Independent post-generation structural/semantic comparison.")
    c.add_argument("--openapi", required=True)
    c.add_argument("--generated", required=True)
    c.add_argument("--reference-stories", required=True)
    c.add_argument("--reference-interfaces", required=True)
    c.add_argument("--report", required=True)
    c.set_defaults(func=cmd_compare_reference)

    return p


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
