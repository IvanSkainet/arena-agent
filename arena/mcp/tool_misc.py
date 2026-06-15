"""MCP system/skill/subagent miscellaneous tools."""
from __future__ import annotations

import json
import os
import sys
from typing import Any

from arena.mcp.tool_utils import text_content


def handle_misc_tool(name: str, args: dict[str, Any], *, ctx, run_local) -> dict[str, Any] | None:
    if name == "sys.status":
        cfg = ctx.app_config()
        return text_content(json.dumps(ctx.common_status(cfg), ensure_ascii=False))

    if name == "skill.list":
        result = ctx.skills_list_sync_with_cache()
        skills = result.get("skills", [])
        return text_content(json.dumps({"ok": True, "count": len(skills), "skills": skills}, ensure_ascii=False))

    if name == "skill.run":
        sk = args.get("name", "")
        extra = args.get("args") or []
        result = ctx.skills_run_sync(sk, list(extra))
        return text_content(json.dumps(result, ensure_ascii=False))

    if name == "hooks.list":
        hooks_dir = ctx.bridge_dir / "hooks"
        pre_dir = hooks_dir / "pre_skill.d"
        post_dir = hooks_dir / "post_skill.d"
        hooks = []
        for d, phase in [(pre_dir, "pre"), (post_dir, "post")]:
            if d.exists():
                for f in sorted(d.iterdir()):
                    if f.is_file():
                        hooks.append({"phase": phase, "name": f.name, "path": str(f)})
        return text_content(json.dumps({"ok": True, "count": len(hooks), "hooks": hooks}, ensure_ascii=False))

    if name == "snapshot":
        result = ctx.skills_run_sync("system/sys-snapshot", [])
        return text_content(json.dumps(result, ensure_ascii=False))

    if name == "subagent.spawn":
        cmd_args = [sys.executable, os.path.join(ctx.bin_dir, "subagent.py"), "spawn", args.get("cmd", "")]
        if args.get("name"):
            cmd_args += ["--name", args["name"]]
        if args.get("wait", True):
            cmd_args += ["--wait"]
        cmd_args += ["--timeout", str(args.get("timeout", 300))]
        rc, out, err = run_local(cmd_args, timeout=args.get("timeout", 300) + 30)
        return text_content(out or err)

    if name == "subagent.list":
        rc, out, err = run_local([sys.executable, os.path.join(ctx.bin_dir, "subagent.py"), "list"], timeout=10)
        return text_content(out or err)

    return None
