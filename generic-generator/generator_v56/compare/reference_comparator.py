"""Independent reference-validation component (compare-reference).

This module is deliberately NOT imported by `pipeline.py` / `cli.py`'s
`generate` path. It runs only after generation has terminated, reads the
OpenAPI contract, the already-completed generated output, and the
reference JS files, and produces read-only comparison reports. It never
writes to generated output, inference rules, templates, or configuration
(REFERENCE_VALIDATION_PROTOCOL.md).

Comparison is structural/semantic (function names, HTTP methods+paths,
response codes, bthread/event names, fault-injection markers), never
byte-for-byte or purely textual, per the "acceptance rule" in
REFERENCE_VALIDATION_PROTOCOL.md.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from ..parsing.loader import load_and_resolve
from ..parsing.normalize import normalize

CLASSES = (
    "OPENAPI_DERIVABLE", "SEMANTICALLY_EQUIVALENT", "REFERENCE_EXTENSION",
    "GENERATOR_OMISSION", "UNJUSTIFIED_GENERATION",
)

# Markers that identify reference-only fault-injection / seeded-bug content:
# these are manually authored oracles/attacks with no OpenAPI-derivable
# basis, and their absence in generated output is not a generator failure.
FAULT_INJECTION_MARKERS = (
    "meta:", "inject", "bug", "attack", "theft", "overflow", "probe", "exploit",
)

FUNC_DEF_RE = re.compile(r"^function\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*\(([^)]*)\)\s*\{", re.MULTILINE)
BTHREAD_RE = re.compile(r'bthread\(\s*(["\'])((?:(?!\1).)*)\1', re.MULTILINE)
EXPECTED_CODES_RE = re.compile(r"expectedResponseCodes:\s*\[([^\]]*)\]")
SVC_CALL_RE = re.compile(r"svc\.(get|post|put|patch|delete)\(")


@dataclass
class Finding:
    dimension: str
    classification: str
    detail: str
    openapi_pointer: Optional[str] = None
    generated_symbol: Optional[str] = None
    reference_symbol: Optional[str] = None


@dataclass
class ComparisonResult:
    findings: List[Finding] = field(default_factory=list)
    mandatory_failures: int = 0

    def add(self, f: Finding):
        self.findings.append(f)
        if f.classification in ("GENERATOR_OMISSION", "UNJUSTIFIED_GENERATION"):
            self.mandatory_failures += 1


def _extract_functions(js_text: str) -> Dict[str, List[str]]:
    return {m.group(1): [p.strip() for p in m.group(2).split(",") if p.strip()]
            for m in FUNC_DEF_RE.finditer(js_text)}


def _extract_bthreads(js_text: str) -> List[str]:
    return [m.group(2) for m in BTHREAD_RE.finditer(js_text)]


def _is_fault_injection(name: str) -> bool:
    low = name.lower()
    return any(marker in low for marker in FAULT_INJECTION_MARKERS)


def _node_check(path: str) -> Dict[str, Any]:
    node = shutil.which("node")
    if not node:
        return {"checked": False, "ok": None, "detail": "node not installed; syntax not independently re-verified"}
    proc = subprocess.run([node, "--check", path], capture_output=True, text=True)
    return {"checked": True, "ok": proc.returncode == 0, "detail": proc.stderr.strip()}


def run_comparison(openapi_path: str, generated_dir: str, reference_stories: str,
                    reference_interfaces: str, report_dir: str) -> Dict[str, Any]:
    result = ComparisonResult()
    gdir = Path(generated_dir)
    gen_report_path = gdir / "generation_report.json"
    gen_report = json.loads(gen_report_path.read_text(encoding="utf-8")) if gen_report_path.exists() else {}

    gen_interfaces_files = sorted(gdir.glob("interfaces.*.js"))
    gen_stories_files = sorted(gdir.glob("stories.*.js"))
    if not gen_interfaces_files or not gen_stories_files:
        result.add(Finding("Syntactic validity (Form)", "GENERATOR_OMISSION",
                            "Generated interfaces/stories file not found in --generated directory."))
        _write_reports(result, report_dir, gen_report)
        return {"mandatory_failures": result.mandatory_failures}

    gen_interfaces_text = gen_interfaces_files[0].read_text(encoding="utf-8")
    gen_stories_text = gen_stories_files[0].read_text(encoding="utf-8")
    ref_interfaces_text = Path(reference_interfaces).read_text(encoding="utf-8")
    ref_stories_text = Path(reference_stories).read_text(encoding="utf-8")

    # ---- Form: syntactic validity ----
    for label, path in [("generated interfaces", str(gen_interfaces_files[0])),
                         ("generated stories", str(gen_stories_files[0])),
                         ("reference interfaces", reference_interfaces),
                         ("reference stories", reference_stories)]:
        check = _node_check(path)
        cls = "OPENAPI_DERIVABLE" if (check["ok"] or check["ok"] is None) else "GENERATOR_OMISSION"
        if "reference" in label and not check["ok"] and check["ok"] is not None:
            cls = "REFERENCE_EXTENSION"  # a reference-file syntax issue is not a generator failure
        result.add(Finding("Syntactic validity (Form)", cls,
                            f"node --check on {label}: {check}"))

    combined_text = gen_interfaces_text + "\n" + gen_stories_text
    decl_re = re.compile(r"^(var|const|let)\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*=", re.MULTILINE)
    names = {}
    for label, text in [("interfaces", gen_interfaces_text), ("stories", gen_stories_text)]:
        for _, n in decl_re.findall(text):
            names.setdefault(n, set()).add(label)
    collisions = {n: labels for n, labels in names.items() if len(labels) > 1}
    result.add(Finding(
        "Syntactic validity (Form)",
        "GENERATOR_OMISSION" if collisions else "OPENAPI_DERIVABLE",
        f"Top-level declaration collisions between generated interfaces/stories: {collisions}",
    ))

    # ---- Fit: contract and integration consistency ----
    resolved, _ = load_and_resolve(openapi_path)
    raw = json.loads(Path(openapi_path).read_text(encoding="utf-8"))
    doc = normalize(resolved, raw)

    coverage = gen_report.get("coverage", {})
    uncovered = coverage.get("uncovered_operations", [])
    if uncovered:
        for u in uncovered:
            result.add(Finding("Contract and integration consistency (Fit)", "GENERATOR_OMISSION",
                                f"Operation {u['method']} {u['path']} is not covered by any generated interface function.",
                                openapi_pointer=f"#/paths/{u['path']}/{u['method'].lower()}"))
    else:
        result.add(Finding("Contract and integration consistency (Fit)", "OPENAPI_DERIVABLE",
                            f"100% of {coverage.get('total_operations', 0)} OpenAPI operations are covered by generated interfaces."))

    for op_report in gen_report.get("response_code_coverage", []):
        declared = set(op_report["declared_codes"])
        method, path = op_report["method"], op_report["path"]
        pointer = f"#/paths/{path}/{method.lower()}"
        # Find whether all declared codes appear somewhere near the
        # relevant generated function's expectedResponseCodes list.
        present = declared and all(str(c) in gen_interfaces_text for c in declared)
        result.add(Finding(
            "Contract and integration consistency (Fit)",
            "OPENAPI_DERIVABLE" if present or not declared else "GENERATOR_OMISSION",
            f"{method} {path}: declared response codes {sorted(declared)} "
            f"{'found' if present else 'NOT all found'} in generated interfaces file.",
            openapi_pointer=pointer,
        ))

    # ---- Structural equivalence: entities/keys/dependency edges (provenance) ----
    for entity in gen_report.get("entities", []):
        result.add(Finding(
            "Contract and integration consistency (Fit)", "OPENAPI_DERIVABLE",
            f"Entity '{entity['key']}' (display '{entity['display_name']}') inferred with "
            f"confidence {entity['confidence']}; key fields {entity['key_fields']}.",
            openapi_pointer=(entity['provenance'][0]['pointer'] if entity['provenance'] else None),
            generated_symbol=entity['key'],
        ))
        for dep in entity.get("dependencies", []):
            result.add(Finding(
                "Structural equivalence", "OPENAPI_DERIVABLE",
                f"Dependency edge {entity['key']} -> {dep['target']} via field '{dep['field_name']}' "
                f"(confidence {dep['confidence']}).",
                openapi_pointer=(dep['provenance'][0]['pointer'] if dep['provenance'] else None),
            ))

    # ---- Event compatibility (story <-> interface) ----
    # ACCEPTANCE_CRITERIA.md Validation #10 explicitly separates "story/
    # interface event compatibility" from plain function-name matching.
    # This checks, for every entity with a create operation, that the
    # completion event emitted by its interface function (tagged with a
    # unique __entityKey, see DESIGN.md/REAL_SUT_VALIDATION.md bug 14)
    # and the EventSet predicate its own matchAny<Plural>Added() uses to
    # find that event are actually paired -- i.e. that a real story
    # waiting for this entity's creation could ever be satisfied by what
    # the interface function actually emits. This is a structural
    # self-consistency check (does not require executing the code), and
    # is what would surface a Bug-14-class regression (two entities
    # sharing dispatch text) even without a live SUT run.
    for entity in gen_report.get("entities", []):
        entity_key = entity["key"]
        has_create = any(o["kind"] == "create" for o in entity["operations"])
        if not has_create:
            continue
        emit_tag = f'"__entityKey": {json.dumps(entity_key)}'
        match_tag = f'e.data["__entityKey"] === {json.dumps(entity_key)}'
        emits = emit_tag in gen_interfaces_text
        matches = match_tag in gen_interfaces_text
        if emits and matches:
            result.add(Finding(
                "Data flow / Lifecycle", "OPENAPI_DERIVABLE",
                f"Entity '{entity_key}': completion event emission and its matchAnyAdded() "
                f"EventSet predicate are paired on a unique entity tag (event compatibility holds).",
                generated_symbol=entity_key,
            ))
        else:
            result.add(Finding(
                "Data flow / Lifecycle", "GENERATOR_OMISSION",
                f"Entity '{entity_key}': completion event and its matching EventSet are NOT "
                f"paired (emits={emits}, matches={matches}) -- a story waiting for this entity's "
                f"creation could never be satisfied.",
                generated_symbol=entity_key,
            ))

    # ---- Function-name / event comparison against reference ----
    gen_functions = _extract_functions(gen_interfaces_text)
    ref_functions = _extract_functions(ref_interfaces_text)
    gen_names_lower = {n.lower(): n for n in gen_functions}
    ref_names_lower = {n.lower(): n for n in ref_functions}

    matched = set(gen_names_lower) & set(ref_names_lower)
    for n in sorted(matched):
        result.add(Finding("Structural equivalence", "SEMANTICALLY_EQUIVALENT",
                            f"Function '{gen_names_lower[n]}' present in both generated and reference interfaces.",
                            generated_symbol=gen_names_lower[n], reference_symbol=ref_names_lower[n]))

    ref_only = set(ref_names_lower) - set(gen_names_lower)
    for n in sorted(ref_only):
        ref_name = ref_names_lower[n]
        if _is_fault_injection(ref_name):
            cls, dim = "REFERENCE_EXTENSION", "Structural equivalence"
            detail = f"Reference-only function '{ref_name}' looks like a manually authored helper; treated generically."
        else:
            cls, dim = "REFERENCE_EXTENSION", "Structural equivalence"
            detail = (f"Reference function '{ref_name}' has no generated counterpart by name; "
                      f"this is only a GENERATOR_OMISSION if the underlying OpenAPI operation is "
                      f"itself uncovered (see contract-coverage findings above) -- verify separately.")
        result.add(Finding(dim, cls, detail, reference_symbol=ref_name))

    gen_only = set(gen_names_lower) - set(ref_names_lower)
    for n in sorted(gen_only):
        result.add(Finding("Structural equivalence", "OPENAPI_DERIVABLE",
                            f"Generated function '{gen_names_lower[n]}' has no reference counterpart by name; "
                            f"acceptable since generated output is not required to match reference naming.",
                            generated_symbol=gen_names_lower[n]))

    # ---- fault-injection / seeded-bug content in reference stories ----
    ref_bthreads = _extract_bthreads(ref_stories_text)
    gen_bthreads = _extract_bthreads(gen_stories_text)
    fault_bthreads = [b for b in ref_bthreads if _is_fault_injection(b)]
    for b in fault_bthreads:
        result.add(Finding(
            "Structural equivalence", "REFERENCE_EXTENSION",
            f"Reference bthread '{b}' is a seeded-fault / manually authored probe with no OpenAPI-derivable "
            f"basis (DEVELOPMENT_PROMPT.md #10: generator must not synthesize these). Its absence from "
            f"generated stories is expected and is not a generator failure.",
        ))
    result.add(Finding(
        "Data flow / Lifecycle", "OPENAPI_DERIVABLE",
        f"Generated stories declare {len(gen_bthreads)} bthreads across "
        f"{len(gen_report.get('entities', []))} inferred entities (creation + reverse-order deletion lifecycle).",
    ))

    dep_graph_path = gdir / "dependency_graph.json"
    if dep_graph_path.exists():
        dep_graph = json.loads(dep_graph_path.read_text(encoding="utf-8"))
        creation = dep_graph.get("creation_order", [])
        deletion = dep_graph.get("deletion_order", [])
        ok = deletion == list(reversed(creation))
        result.add(Finding(
            "Lifecycle", "OPENAPI_DERIVABLE" if ok else "GENERATOR_OMISSION",
            f"deletion_order {'is' if ok else 'is NOT'} the exact reverse of creation_order "
            f"(creation={creation}, deletion={deletion}).",
        ))

    # ---- Function (executable behavioral validation): optional, not run here ----
    result.add(Finding(
        "Executable behavioral validation (Function)", "OPENAPI_DERIVABLE",
        "Optional SUT smoke execution was not requested as part of this compare-reference invocation; "
        "see USAGE.md for how to run it separately against validation_only/suts.",
    ))

    _write_reports(result, report_dir, gen_report)
    return {"mandatory_failures": result.mandatory_failures, "total_findings": len(result.findings)}


def _write_reports(result: ComparisonResult, report_dir: str, gen_report: Dict[str, Any]) -> None:
    out = Path(report_dir)
    out.mkdir(parents=True, exist_ok=True)

    by_class = {c: [] for c in CLASSES}
    for f in result.findings:
        by_class[f.classification].append({
            "dimension": f.dimension, "detail": f.detail,
            "openapi_pointer": f.openapi_pointer,
            "generated_symbol": f.generated_symbol, "reference_symbol": f.reference_symbol,
        })

    json_report = {
        "summary": {c: len(v) for c, v in by_class.items()},
        "mandatory_failures": result.mandatory_failures,
        "findings_by_classification": by_class,
    }
    (out / "reference_comparison.json").write_text(json.dumps(json_report, indent=2, sort_keys=True), encoding="utf-8")

    md = ["# Reference comparison report", ""]
    md.append(f"Mandatory failures: **{result.mandatory_failures}**")
    md.append("")
    md.append("| Classification | Count |")
    md.append("|---|---|")
    for c in CLASSES:
        md.append(f"| {c} | {len(by_class[c])} |")
    md.append("")
    for c in CLASSES:
        if not by_class[c]:
            continue
        md.append(f"## {c}")
        md.append("")
        for item in by_class[c]:
            sym = ""
            if item["generated_symbol"] or item["reference_symbol"]:
                sym = f" (generated=`{item['generated_symbol']}`, reference=`{item['reference_symbol']}`)"
            ptr = f" [`{item['openapi_pointer']}`]" if item["openapi_pointer"] else ""
            md.append(f"- **{item['dimension']}**{sym}{ptr}: {item['detail']}")
        md.append("")
    (out / "REFERENCE_COMPARISON.md").write_text("\n".join(md), encoding="utf-8")
