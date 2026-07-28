"""``code.run`` -- execute agent-authored code under the operator posture.

The tool is classified DANGEROUS (so it needs approval, or
YOLO to auto-approve); the *fence* it runs under is the operator's posture,
which the agent CANNOT influence: any posture/axis key in the arguments is
rejected, and the active posture is read server-side from the operator store.
Combined with the runner's fail-closed behaviour, this means the agent can run
code only inside whatever fence the operator set (or, in the labeled extreme
posture, unfenced), and can never widen that fence itself.
"""
from __future__ import annotations

import json
from typing import Any

from arena.autonomy import posture as _posture
from arena.autonomy import runner as _runner
from arena.mcp.tool_utils import text_content

# Axes the operator controls; the agent must never be able to set them.
_OVERRIDE_KEYS = frozenset({
    "posture", "sandbox", "network", "privilege", "filesystem",
    "runtime", "runtimes", "resources",
})


def handle_code_tool(name: str, args: dict[str, Any], *, ctx) -> dict[str, Any] | None:
    if name != "code.run":
        return None
    leak = _OVERRIDE_KEYS & set(args or {})
    if leak:
        return {"isError": True, "content": [{
            "type": "text",
            "text": (f"ERROR: code.run does not accept posture controls "
                     f"{sorted(leak)}; the execution posture is operator-owned "
                     f"and cannot be set by the agent.")}]}
    code = args.get("code", "")
    files = args.get("files")
    if not isinstance(code, str):
        return {"isError": True, "content": [{
            "type": "text", "text": "ERROR: 'code' must be a string"}]}
    if files is not None and not isinstance(files, list):
        return {"isError": True, "content": [{
            "type": "text", "text": "ERROR: 'files' must be an array"}]}
    if not code and not files:
        return {"isError": True, "content": [{
            "type": "text", "text": "ERROR: provide either 'code' or 'files'"}]}
    lang = str(args.get("lang", "python3"))
    timeout = args.get("timeout")
    argv = args.get("argv") or []
    artifacts = args.get("artifacts") or []
    if not isinstance(argv, list):
        return {"isError": True, "content": [{"type": "text", "text": "ERROR: 'argv' must be an array"}]}
    if not isinstance(artifacts, list):
        return {"isError": True, "content": [{"type": "text", "text": "ERROR: 'artifacts' must be an array"}]}
    posture = _posture.load_posture()
    result = _runner.run_code_sync(
        code, lang, posture,
        timeout=int(timeout) if timeout else None,
        files=files, entry=args.get("entry"), argv=[str(a) for a in argv],
        stdin=args.get("stdin") if isinstance(args.get("stdin"), str) else None,
        artifacts=[str(a) for a in artifacts],
        deps=args.get("deps") if isinstance(args.get("deps"), dict) else None,
    )
    return text_content(json.dumps(result, ensure_ascii=False))


CODE_TOOLS = [
    {
        "name": "code.run",
        "description": (
            "Execute code YOU author, under the OPERATOR's execution posture "
            "(the composable fence: sandbox/network/privilege/filesystem/runtime "
            "axes). Classified dangerous -> needs approval, or YOLO to "
            "auto-approve; the fence itself is NOT yours to set: passing any "
            "posture axis is rejected, and the active posture is read "
            "server-side. The runner is fail-closed: if the posture demands a "
            "sandbox this platform cannot engage, execution is refused rather "
            "than run unfenced. Returns {ok, exit_code, stdout, stderr, "
            "sandbox_action, enforced, note} where `enforced` honestly lists "
            "which axes the fence actually confined on this platform."
        ),
        "inputSchema": {"type": "object", "properties": {
            "code": {"type": "string", "description": "source code to execute (single-file mode; optional when files+entry are provided)"},
            "files": {"type": "array", "description": "Optional multi-file workspace: [{path, content, encoding?}]. Paths are relative to scratch.",
                      "items": {"type": "object", "properties": {
                          "path": {"type": "string"},
                          "content": {"type": "string"},
                          "encoding": {"type": "string", "enum": ["utf-8", "base64"], "default": "utf-8"}
                      }, "required": ["path", "content"], "additionalProperties": False}},
            "entry": {"type": "string", "description": "Relative workspace file to run as entrypoint (required for multi-file project mode)."},
            "argv": {"type": "array", "items": {"type": "string"}, "description": "Command-line arguments passed after the entry file."},
            "stdin": {"type": "string", "description": "Optional stdin text for the process."},
            "artifacts": {"type": "array", "items": {"type": "string"}, "description": "Glob patterns inside scratch to return after execution, e.g. ['out/*.json']."},
            "deps": {"type": "object", "description": "Optional dependency install. supports deps.python=[package specs], deps.npm=[package specs], and deps.go=true; requires posture network=open."},
            "lang": {"type": "string",
                     "description": "interpreter name (must be in the posture's "
                                    "runtimes allowlist unless runtime=any)",
                     "default": "python3"},
            "timeout": {"type": "integer",
                        "description": "wall-clock seconds (capped by posture)"},
        }, "required": [], "additionalProperties": False},
    },
]
