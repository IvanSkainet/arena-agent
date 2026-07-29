"""Tool Foundry v1.

A foundry project is an existing Code Workbench project that contains a small
manifest (default: ``.arena-tool.json``).  The manifest describes how to run the
project, what input schema the future tool accepts, and test cases that prove it
works before publication.  Publishing creates a normal ``custom.<name>`` tool
that wraps ``code_project.run``; the runtime path therefore stays behind the
same dispatcher, HALT gate, posture policy, artifacts, and audit semantics as
any other Workbench run.
"""
from __future__ import annotations

import json
import re
from typing import Any

from arena.mcp import custom_tools
from arena.workbench import projects

DEFAULT_MANIFEST = ".arena-tool.json"
_TOKEN = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
_ALLOWED_RUN_KEYS = {"lang", "entry", "argv", "stdin", "artifacts", "timeout", "use_project_deps", "deps"}


def _load_manifest(project: str, manifest_path: str = DEFAULT_MANIFEST) -> tuple[dict[str, Any] | None, str | None]:
    res = projects.read(project, manifest_path, max_bytes=200_000)
    if not res.get("ok"):
        return None, str(res.get("error") or "manifest not found")
    try:
        doc = json.loads(str(res.get("text") or "{}"))
    except json.JSONDecodeError as e:
        return None, f"invalid JSON manifest: {e}"
    if not isinstance(doc, dict):
        return None, "manifest must be a JSON object"
    return doc, None


def _template(value: Any, args: dict[str, Any]) -> Any:
    if isinstance(value, str):
        m = _TOKEN.fullmatch(value.strip())
        if m:
            return args.get(m.group(1))
        return _TOKEN.sub(lambda mm: "" if args.get(mm.group(1)) is None else str(args.get(mm.group(1))), value)
    if isinstance(value, list):
        return [_template(v, args) for v in value]
    if isinstance(value, dict):
        return {k: _template(v, args) for k, v in value.items()}
    return value


def _as_list(v: Any) -> list[Any]:
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def _tool_name(doc: dict[str, Any]) -> str:
    return custom_tools.normalize_name(str(doc.get("name") or ""))


def _validate_manifest_shape(doc: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    name = _tool_name(doc)
    if not name or name == "custom.":
        errors.append("manifest.name is required")
    if name in custom_tools.MGMT_NAMES:
        errors.append(f"manifest.name {name!r} is reserved")
    desc = str(doc.get("description") or "").strip()
    if not desc:
        errors.append("manifest.description is required")
    schema = doc.get("input_schema") or doc.get("inputSchema")
    err = custom_tools.validate_schema(schema)
    if err:
        errors.append(f"input_schema: {err}")
    run = doc.get("run")
    if not isinstance(run, dict):
        errors.append("manifest.run must be an object")
    else:
        unknown = sorted(set(run) - _ALLOWED_RUN_KEYS)
        if unknown:
            errors.append(f"manifest.run has unsupported keys: {', '.join(unknown)}")
        if not str(run.get("entry") or "").strip():
            errors.append("manifest.run.entry is required")
        argv = run.get("argv", [])
        artifacts = run.get("artifacts", [])
        if not isinstance(argv, list):
            errors.append("manifest.run.argv must be an array")
        if not isinstance(artifacts, list):
            errors.append("manifest.run.artifacts must be an array")
    tests = doc.get("tests")
    if not isinstance(tests, list) or not tests:
        errors.append("manifest.tests must be a non-empty array")
    else:
        for i, t in enumerate(tests):
            if not isinstance(t, dict):
                errors.append(f"tests[{i}] must be an object")
                continue
            if not isinstance(t.get("args", {}), dict):
                errors.append(f"tests[{i}].args must be an object")
            if t.get("expect") is not None and not isinstance(t.get("expect"), dict):
                errors.append(f"tests[{i}].expect must be an object")
    return errors


def _run_args(project: str, run: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
    rendered = _template(run, args)
    return {
        "name": project,
        "lang": str(rendered.get("lang") or "python3"),
        "entry": str(rendered.get("entry") or ""),
        "argv": [str(a) for a in _as_list(rendered.get("argv"))],
        "stdin": rendered.get("stdin") if isinstance(rendered.get("stdin"), str) else None,
        "artifacts": [str(a) for a in _as_list(rendered.get("artifacts"))],
        "deps": rendered.get("deps") if isinstance(rendered.get("deps"), dict) else None,
        "use_project_deps": bool(rendered.get("use_project_deps", False)),
        "timeout": int(rendered.get("timeout")) if rendered.get("timeout") else None,
    }


def _artifact_text(run_result: dict[str, Any], path: str) -> str:
    for art in run_result.get("artifacts") or []:
        if str(art.get("path") or "") == path:
            return str(art.get("text") or art.get("base64") or "")
    return ""


def _check_expect(run_result: dict[str, Any], expect: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    if "ok" in expect and bool(run_result.get("ok")) != bool(expect.get("ok")):
        failures.append(f"expected ok={bool(expect.get('ok'))}, got ok={bool(run_result.get('ok'))}")
    for needle in _as_list(expect.get("stdout_contains")):
        if str(needle) not in str(run_result.get("stdout") or ""):
            failures.append(f"stdout missing {needle!r}")
    for needle in _as_list(expect.get("stderr_contains")):
        if str(needle) not in str(run_result.get("stderr") or ""):
            failures.append(f"stderr missing {needle!r}")
    artifact_contains = expect.get("artifact_contains")
    if isinstance(artifact_contains, dict):
        checks = [{"path": p, "contains": v} for p, v in artifact_contains.items()]
    else:
        checks = _as_list(artifact_contains)
    for item in checks:
        if not isinstance(item, dict):
            failures.append("artifact_contains entries must be objects or path->contains map")
            continue
        path = str(item.get("path") or "")
        needle = str(item.get("contains") if "contains" in item else item.get("text", ""))
        text = _artifact_text(run_result, path)
        if not path or not text:
            failures.append(f"artifact {path!r} not found in run result")
        elif needle not in text:
            failures.append(f"artifact {path!r} missing {needle!r}")
    return failures


def list_candidates() -> dict[str, Any]:
    rows = []
    listed = projects.list_projects()
    for p in listed.get("projects") or []:
        files = p.get("files") or []
        has_manifest = DEFAULT_MANIFEST in files
        row = {"project": p.get("name"), "has_manifest": has_manifest, "manifest_path": DEFAULT_MANIFEST if has_manifest else None}
        if has_manifest:
            doc, err = _load_manifest(str(p.get("name") or ""), DEFAULT_MANIFEST)
            row["valid_shape"] = bool(doc is not None and not _validate_manifest_shape(doc))
            if doc:
                row["tool"] = _tool_name(doc)
            if err:
                row["error"] = err
        rows.append(row)
    return {"ok": True, "count": len(rows), "projects": rows}


def validate(project: str, manifest_path: str = DEFAULT_MANIFEST, *, run_tests: bool = True) -> dict[str, Any]:
    doc, err = _load_manifest(project, manifest_path)
    if err:
        return {"ok": False, "project": project, "manifest_path": manifest_path, "errors": [err], "tests": []}
    assert doc is not None
    errors = _validate_manifest_shape(doc)
    tests_out: list[dict[str, Any]] = []
    if errors:
        return {"ok": False, "project": project, "manifest_path": manifest_path, "tool": _tool_name(doc), "errors": errors, "tests": tests_out}
    if run_tests:
        run = doc["run"]
        for i, test in enumerate(doc.get("tests") or []):
            name = str(test.get("name") or f"test-{i}")
            args = test.get("args") or {}
            call = _run_args(project, run, args)
            res = projects.run(
                call["name"], lang=call["lang"], entry=call["entry"], argv=call["argv"],
                stdin=call["stdin"], artifacts=call["artifacts"], deps=call["deps"],
                use_project_deps=call["use_project_deps"], timeout=call["timeout"],
            )
            failures = _check_expect(res, test.get("expect") or {"ok": True})
            ok = bool(res.get("ok")) and not failures
            tests_out.append({
                "name": name,
                "ok": ok,
                "failures": failures,
                "run_id": res.get("run_id"),
                "stdout": str(res.get("stdout") or "")[:2000],
                "stderr": str(res.get("stderr") or "")[:2000],
                "artifacts": res.get("artifacts") or [],
            })
    test_failures = [t for t in tests_out if not t.get("ok")]
    return {
        "ok": not errors and not test_failures,
        "project": project,
        "manifest_path": manifest_path,
        "tool": _tool_name(doc),
        "description": str(doc.get("description") or ""),
        "errors": errors,
        "tests": tests_out,
        "test_count": len(tests_out),
        "run_tests": run_tests,
    }


def _publish_call_args(project: str, doc: dict[str, Any]) -> dict[str, Any]:
    run = doc["run"]
    out: dict[str, Any] = {
        "name": project,
        "lang": run.get("lang", "python3"),
        "entry": run.get("entry"),
        "argv": run.get("argv", []),
        "artifacts": run.get("artifacts", []),
        "use_project_deps": bool(run.get("use_project_deps", False)),
    }
    for key in ("stdin", "timeout", "deps"):
        if key in run:
            out[key] = run[key]
    return out


def publish(project: str, manifest_path: str = DEFAULT_MANIFEST, *, run_tests: bool = True) -> dict[str, Any]:
    checked = validate(project, manifest_path, run_tests=run_tests)
    if not checked.get("ok"):
        return {"ok": False, "project": project, "validated": checked, "error": "validation failed; tool not published"}
    doc, err = _load_manifest(project, manifest_path)
    if err or doc is None:
        return {"ok": False, "project": project, "error": err or "manifest not found"}
    res = custom_tools.create_tool(
        str(doc.get("name") or ""),
        str(doc.get("description") or ""),
        doc.get("input_schema") or doc.get("inputSchema") or {},
        call={"tool": "code_project.run", "args": _publish_call_args(project, doc)},
    )
    return {
        "ok": bool(res.get("ok")),
        "project": project,
        "manifest_path": manifest_path,
        "tool": (res.get("tool") or {}).get("name") or _tool_name(doc),
        "validated": checked,
        "published": res,
    }
