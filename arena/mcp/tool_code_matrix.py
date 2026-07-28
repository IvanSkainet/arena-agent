"""MCP tool for running a small matrix of Code Workbench jobs."""
from __future__ import annotations

import json
from typing import Any

from arena.autonomy import posture as _posture
from arena.autonomy import runner as _runner
from arena.mcp.tool_utils import text_content
from arena.workbench import projects as _projects

MATRIX_TOOL_NAMES = ("code_matrix.run",)
_MAX_MATRIX_RUNS = 8


def _res(payload: dict[str, Any]) -> dict[str, Any]:
    return text_content(json.dumps(payload, ensure_ascii=False))


def _run_one(spec: dict[str, Any], active_posture: dict[str, Any]) -> dict[str, Any]:
    ident = str(spec.get("id") or spec.get("name") or "run")[:80]
    timeout = int(spec.get("timeout")) if spec.get("timeout") else None
    argv = spec.get("argv") or []
    artifacts = spec.get("artifacts") or []
    if not isinstance(argv, list) or not isinstance(artifacts, list):
        return {"id": ident, "ok": False, "error": "argv and artifacts must be arrays"}
    if spec.get("project"):
        out = _projects.run(
            str(spec.get("project")), lang=str(spec.get("lang") or "python3"),
            entry=str(spec.get("entry") or ""), argv=[str(a) for a in argv],
            stdin=spec.get("stdin") if isinstance(spec.get("stdin"), str) else None,
            artifacts=[str(a) for a in artifacts], deps=spec.get("deps") if isinstance(spec.get("deps"), dict) else None, timeout=timeout,
        )
    else:
        files = spec.get("files")
        if files is not None and not isinstance(files, list):
            return {"id": ident, "ok": False, "error": "files must be an array"}
        code = spec.get("code", "")
        if not isinstance(code, str):
            return {"id": ident, "ok": False, "error": "code must be a string"}
        out = _runner.run_code_sync(
            code, str(spec.get("lang") or "python3"), active_posture,
            timeout=timeout, files=files, entry=spec.get("entry"),
            argv=[str(a) for a in argv],
            stdin=spec.get("stdin") if isinstance(spec.get("stdin"), str) else None,
            artifacts=[str(a) for a in artifacts],
            deps=spec.get("deps") if isinstance(spec.get("deps"), dict) else None,
        )
    out["id"] = ident
    return out


def handle_code_matrix_tool(name: str, args: dict[str, Any], *, ctx=None) -> dict[str, Any] | None:
    if name != "code_matrix.run":
        return None
    runs = args.get("runs") or []
    if not isinstance(runs, list) or not runs:
        return _res({"ok": False, "error": "runs must be a non-empty array"})
    if len(runs) > _MAX_MATRIX_RUNS:
        return _res({"ok": False, "error": f"maximum {_MAX_MATRIX_RUNS} runs per matrix"})
    active_posture = _posture.load_posture()
    results = []
    for i, spec in enumerate(runs, start=1):
        if not isinstance(spec, dict):
            results.append({"id": f"run-{i}", "ok": False, "error": "run spec must be an object"})
            continue
        if {"posture", "sandbox", "network", "privilege", "filesystem", "runtime", "runtimes", "resources"} & set(spec):
            results.append({"id": str(spec.get("id") or f"run-{i}"), "ok": False,
                            "error": "matrix run specs cannot set operator-owned posture controls"})
            continue
        results.append(_run_one({"id": f"run-{i}", **spec}, active_posture))
    return _res({"ok": all(r.get("ok") for r in results), "count": len(results), "results": results})


MATRIX_TOOLS = [
    {"name": "code_matrix.run", "description": "Run up to 8 Code Workbench jobs sequentially under the current operator posture. Each item may be a one-shot code/files run or a persistent code_project run.",
     "inputSchema": {"type": "object", "properties": {"runs": {"type": "array", "items": {"type": "object"}, "description": "Run specs: {id, lang, code/files/entry/argv/stdin/artifacts/timeout} or {id, project, entry, lang, argv, artifacts}."}}, "required": ["runs"], "additionalProperties": False}},
]
