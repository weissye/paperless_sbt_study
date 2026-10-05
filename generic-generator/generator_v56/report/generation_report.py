"""Build generation_report.json and dependency_graph.json content."""
from __future__ import annotations

from typing import Any, Dict, List

from ..parsing.model import Document
from ..render.plan import Plan


def build_dependency_graph_report(plan: Plan, dependencies) -> Dict[str, Any]:
    return {
        "nodes": plan.graph.nodes,
        "creation_order": plan.graph.creation_order,
        "deletion_order": plan.graph.deletion_order,
        "had_cycle": plan.graph.had_cycle,
        "cycle_edges_removed": [
            {
                "source": e.source, "target": e.target, "field_name": e.field_name,
                "confidence": e.confidence,
                "provenance": [p.to_dict() for p in e.provenance],
            } for e in plan.graph.cycle_edges_removed
        ],
        "edges": [
            {
                "source": e.source, "target": e.target, "field_name": e.field_name,
                "confidence": e.confidence,
                "provenance": [p.to_dict() for p in e.provenance],
            } for e in plan.graph.edges
        ],
    }


def build_generation_report(doc: Document, plan: Plan, unsupported_refs: List[str],
                             ambiguities: List[str], isolation_audit=None,
                             cli_args: Dict[str, Any] = None) -> Dict[str, Any]:
    total_ops = len(doc.operations)
    covered_ops = set()
    for ep in plan.entities:
        for op in ep.ops:
            covered_ops.add((op.op.method, op.op.path))
    for op in plan.standalone_ops:
        covered_ops.add((op.op.method, op.op.path))

    all_ops_keys = {(o.method, o.path) for o in doc.operations}
    uncovered = sorted(all_ops_keys - covered_ops)

    entities_report = []
    for ep in plan.entities:
        entities_report.append({
            "key": ep.entity.key,
            "display_name": ep.entity.display_name,
            "plural_display_name": ep.entity.plural_display_name,
            "schema_name": ep.entity.schema_name,
            "collection_path": ep.entity.collection_path,
            "item_path": ep.entity.item_path,
            "confidence": ep.entity.confidence,
            "provenance": [p.to_dict() for p in ep.entity.provenance],
            "key_fields": ep.key.fields,
            "composite_key": ep.key.composite,
            "key_confidence": ep.key.confidence,
            "key_provenance": [p.to_dict() for p in ep.key.provenance],
            "operations": [
                {
                    "method": o.op.method, "path": o.op.path, "js_function": o.js_name,
                    "kind": o.kind, "success_codes": o.success_codes,
                    "error_codes": o.error_codes, "has_default_response": o.has_default_response,
                    "source_pointer": o.source_pointer,
                } for o in ep.ops
            ],
            "dependencies": [
                {"target": d.target, "field_name": d.field_name, "confidence": d.confidence,
                 "provenance": [p.to_dict() for p in d.provenance]}
                for d in ep.dependencies
            ],
        })

    standalone_report = [
        {
            "method": o.op.method, "path": o.op.path, "js_function": o.js_name,
            "success_codes": o.success_codes, "error_codes": o.error_codes,
            "has_default_response": o.has_default_response, "source_pointer": o.source_pointer,
        } for o in plan.standalone_ops
    ]

    response_code_coverage = []
    for op in doc.operations:
        declared = op.all_response_codes
        response_code_coverage.append({
            "method": op.method, "path": op.path, "declared_codes": declared,
            "has_default": any(r.is_default for r in op.responses),
        })

    return {
        "meta": {
            "title": doc.title,
            "openapi_version": doc.openapi_version,
            "cli_args": cli_args or {},
        },
        "coverage": {
            "total_operations": total_ops,
            "covered_operations": len(covered_ops),
            "uncovered_operations": [{"method": m, "path": p} for m, p in uncovered],
        },
        "security_schemes": {
            name: {"type": s.type_, "scheme": s.scheme, "location": s.location, "param_name": s.param_name}
            for name, s in doc.security_schemes.items()
        },
        "entities": entities_report,
        "standalone_operations": standalone_report,
        "response_code_coverage": response_code_coverage,
        "unsupported_constructs": {
            "remote_refs": unsupported_refs,
            "ambiguities": ambiguities,
            "document_level": doc.unsupported,
        },
        "warnings": doc.warnings,
        "isolation_audit": {
            "opened_files": (isolation_audit.opened if isolation_audit else []),
            "denied_files": (isolation_audit.denied if isolation_audit else []),
        },
    }
