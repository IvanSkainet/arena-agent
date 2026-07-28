"""``code.run`` -- execute agent-authored code under the operator posture.

v4.102.0, slice 1. The tool is classified DANGEROUS (so it needs approval, or
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
    code = args.get("code")
    if not isinstance(code, str):
        return {"isError": True, "content": [{
            "type": "text", "text": "ERROR: 'code' must be a string"}]}
    lang = str(args.get("lang", "python3"))
    timeout = args.get("timeout")
    posture = _posture.load_posture()
    result = _runner.run_code_sync(code, lang, posture,
                                   timeout=int(timeout) if timeout else None)
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
            "code": {"type": "string", "description": "source code to execute"},
            "lang": {"type": "string",
                     "description": "interpreter name (must be in the posture's "
                                    "runtimes allowlist unless runtime=any)",
                     "default": "python3"},
            "timeout": {"type": "integer",
                        "description": "wall-clock seconds (capped by posture)"},
        }, "required": ["code"], "additionalProperties": False},
    },
]
