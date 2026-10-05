"""`validate` command: checks generated output against the OpenAPI contract
only (never touches reference/SUT files).

Rewritten after an external audit demonstrated a real tamper vulnerability:
the previous version trusted `generation_report.json`'s self-reported
operation-coverage numbers, and checked response-code "coverage" via a
*global substring search* over the whole interfaces file's text -- so a
file containing only two comment lines listing the numbers "200 201 202
204 ..." passed with `ok: true` and "100% response-code coverage".

This version re-derives the ground truth independently by re-running the
(deterministic, already-tested) parse -> infer -> plan pipeline directly
from the OpenAPI file in memory (never touching `generation_report.json`'s
*content* for this purpose), then performs real structural analysis of the
actual `interfaces.<name>.js` file on disk: it extracts each named
function's real body via brace-matching (not a line-count guess, and not
fooled by braces inside string literals), and checks -- *within that
specific function's body only* -- that the right `svc.<method>(` call is
present and that its own `expectedResponseCodes` array is a superset of
the operation's declared codes. A stub file containing only comments (or
any file where a claimed function doesn't actually exist, or exists but
doesn't call the right method, or declares the wrong codes) now correctly
fails.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional


def _find_js_files(generated_dir: Path):
    return sorted(generated_dir.glob("interfaces.*.js")), sorted(generated_dir.glob("stories.*.js"))


def _check_js_syntax(js_files) -> Dict[str, Any]:
    node = shutil.which("node")
    results = {}
    for f in js_files:
        if node:
            proc = subprocess.run([node, "--check", str(f)], capture_output=True, text=True)
            results[str(f)] = {"ok": proc.returncode == 0, "stderr": proc.stderr.strip(), "checked_with": "node --check"}
        else:
            text = f.read_text(encoding="utf-8")
            balanced = text.count("{") == text.count("}") and text.count("(") == text.count(")")
            results[str(f)] = {"ok": balanced, "stderr": "" if balanced else "unbalanced braces/parens",
                                "checked_with": "brace-balance fallback (node not installed)"}
    return results


def _check_duplicate_top_level_declarations(interfaces_files, stories_files) -> Dict[str, Any]:
    """Guards against the previously-observed 'redeclaration of var svc'
    failure when both generated files are loaded together."""
    decl_re = re.compile(r"^(var|const|let)\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*=", re.MULTILINE)
    all_names: Dict[str, list] = {}
    for f in list(interfaces_files) + list(stories_files):
        text = f.read_text(encoding="utf-8")
        for _, name in decl_re.findall(text):
            all_names.setdefault(name, []).append(str(f))
    collisions = {name: files for name, files in all_names.items() if len(set(files)) > 1}
    return {"ok": len(collisions) == 0, "collisions": collisions}


def extract_js_functions(js_text: str) -> Dict[str, str]:
    """Returns {function_name: full_source_text} for every top-level
    `function NAME(...) { ... }` in `js_text`, found via real brace
    matching (correctly skipping over braces inside string/template
    literals) rather than a fixed line count or substring search. A
    function whose declaration exists but whose body is truncated,
    missing, or replaced by a comment will simply not appear here."""
    functions: Dict[str, str] = {}
    pattern = re.compile(r"function\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*\([^)]*\)\s*\{")
    n = len(js_text)
    for m in pattern.finditer(js_text):
        name = m.group(1)
        i = m.end() - 1  # index of the opening '{'
        depth = 0
        in_string: Optional[str] = None
        start = m.start()
        while i < n:
            c = js_text[i]
            if in_string:
                if c == "\\":
                    i += 2
                    continue
                if c == in_string:
                    in_string = None
                i += 1
                continue
            if c in ('"', "'", "`"):
                in_string = c
                i += 1
                continue
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    functions[name] = js_text[start:i + 1]
                    break
            i += 1
    return functions


def _independent_ground_truth(openapi_path: str, seed: int = 1):
    """Re-derives the authoritative operation -> (js_function, method,
    declared_codes) mapping by re-running the SAME deterministic parse ->
    infer -> plan pipeline `generate` uses, directly from the OpenAPI file,
    entirely in memory. This deliberately never reads
    `generation_report.json`'s content -- only the OpenAPI file itself and
    this package's own (separately unit-tested) inference code are
    trusted, so a stale or hand-edited report on disk cannot make a
    tampered/missing JS implementation look covered."""
    from ..pipeline import run_pipeline
    result = run_pipeline(openapi_path, "validate-check", "http://localhost:1", seed=seed)
    expectations = []
    for ep in result.plan.entities:
        for op in ep.ops:
            expectations.append({
                "method": op.op.method, "path": op.op.path, "js_function": op.js_name,
                "declared_codes": sorted(set(op.success_codes) | set(op.error_codes)),
            })
    for op in result.plan.standalone_ops:
        expectations.append({
            "method": op.op.method, "path": op.op.path, "js_function": op.js_name,
            "declared_codes": sorted(set(op.success_codes) | set(op.error_codes)),
        })
    return expectations


def _verify_against_real_js(expectations: List[Dict[str, Any]], js_text: str) -> Dict[str, Any]:
    functions = extract_js_functions(js_text)
    findings = []
    covered_ops = 0
    total_declared = 0
    covered_declared = 0
    for exp in expectations:
        fn_name = exp["js_function"]
        method = exp["method"].lower()
        body = functions.get(fn_name)
        entry = {"method": exp["method"], "path": exp["path"], "js_function": fn_name}
        if body is None:
            entry["status"] = "FUNCTION_NOT_FOUND"
            findings.append(entry)
            total_declared += len(exp["declared_codes"])
            continue
        method_call_re = re.compile(r"svc\.\s*" + re.escape(method) + r"\s*\(")
        if not method_call_re.search(body):
            entry["status"] = "WRONG_OR_MISSING_METHOD_CALL"
            findings.append(entry)
            total_declared += len(exp["declared_codes"])
            continue
        codes_match = re.search(r"expectedResponseCodes\s*:\s*\[([^\]]*)\]", body)
        actual_codes = set()
        if codes_match:
            for tok in codes_match.group(1).split(","):
                tok = tok.strip()
                if tok.isdigit():
                    actual_codes.add(int(tok))
        missing_codes = [c for c in exp["declared_codes"] for _ in [0] if c not in actual_codes]
        total_declared += len(exp["declared_codes"])
        covered_declared += len(exp["declared_codes"]) - len(missing_codes)
        if missing_codes:
            entry["status"] = "MISSING_RESPONSE_CODES"
            entry["missing_codes"] = missing_codes
            entry["codes_found_in_function"] = sorted(actual_codes)
            findings.append(entry)
            continue
        covered_ops += 1
    total_ops = len(expectations)
    percent = round(100.0 * covered_declared / total_declared, 2) if total_declared else 100.0
    return {
        "total_operations": total_ops,
        "covered_operations": covered_ops,
        "uncovered_operations": [{"method": f["method"], "path": f["path"], "reason": f["status"]} for f in findings],
        "response_code_coverage": {
            "total_declared_codes": total_declared,
            "covered_declared_codes": covered_declared,
            "coverage_percent": percent,
        },
        "findings": findings,
    }


def validate_generated(openapi_path: str, generated_dir: str) -> Dict[str, Any]:
    gdir = Path(generated_dir)
    report_path = gdir / "generation_report.json"
    graph_path = gdir / "dependency_graph.json"
    interfaces_files, stories_files = _find_js_files(gdir)

    problems = []
    if not report_path.exists():
        problems.append("generation_report.json missing")
    if not graph_path.exists():
        problems.append("dependency_graph.json missing")
    if not interfaces_files:
        problems.append("no interfaces.<name>.js found")
    if not stories_files:
        problems.append("no stories.<name>.js found")

    syntax = _check_js_syntax(list(interfaces_files) + list(stories_files))
    syntax_ok = all(v["ok"] for v in syntax.values()) if syntax else False

    decls = _check_duplicate_top_level_declarations(interfaces_files, stories_files)

    interfaces_text = "\n".join(f.read_text(encoding="utf-8") for f in interfaces_files) if interfaces_files else ""

    # Independent re-derivation: never trusts generation_report.json's
    # content for coverage claims. See module docstring.
    expectations = _independent_ground_truth(openapi_path)
    verification = _verify_against_real_js(expectations, interfaces_text)

    ok = (
        not problems
        and syntax_ok
        and decls["ok"]
        and len(verification["uncovered_operations"]) == 0
    )

    return {
        "ok": ok,
        "problems": problems,
        "js_syntax": syntax,
        "declaration_collisions": decls,
        "operation_coverage": {
            "total_operations": verification["total_operations"],
            "covered_operations": verification["covered_operations"],
            "uncovered_operations": verification["uncovered_operations"],
        },
        "response_code_coverage": verification["response_code_coverage"],
        "independent_verification": {
            "method": "Re-parsed the OpenAPI file and re-ran inference/planning in memory "
                      "(never trusting generation_report.json's content); extracted each "
                      "claimed function's real body from the actual interfaces.*.js file via "
                      "brace-matching; checked the correct svc.<method>() call and "
                      "expectedResponseCodes are present INSIDE that specific function body.",
            "findings": verification["findings"],
        },
    }
