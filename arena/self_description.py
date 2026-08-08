"""What this bridge can do, in a form an agent reads without being told.

The operator's observation, and it is the sharpest thing anyone has said
about this project: *"agents just don't use the whole arsenal. Not
because the arsenal doesn't work, but because they have no hint."*

Measured on his machine: `tools/list` returns **240 tools, all with
descriptions and schemas**. The capability was never missing. What was
missing is that a model has to already know to call `tools/list`, and
then has to read 240 flat entries and infer structure from names. Most
never get past the first eight.

So this module answers three questions the bridge could always answer
but never volunteered:

* **What kind of machine am I on?** Windows, Linux, macOS, Android --
  and on Android, whether the bridge runs on the phone itself.
* **What can I do here?** Tools grouped into categories, with a count
  and a one-line purpose per group, so a model can navigate 240 entries
  instead of scrolling them.
* **What is currently stopping me?** Every guard, its live state, and
  what it blocks. An agent that hits a refusal should already know why
  and what the operator would have to flip.

That last one is the part that matters most. A refusal without an
explanation reads as a broken tool, and a model reacts by trying
something else at random. A refusal that arrives with "profile is
cautious, the operator can change it in Settings" is a fact the agent
can relay.

`categories()` is the whole surface; everything else builds on it.
Category membership is derived from the tool name prefix, which is
already the convention (`fs.read`, `mobile.tap`, `relay.send`) -- a
hand-maintained mapping would rot on the next tool added, and a stale
index is worse than none.
"""
from __future__ import annotations

from typing import Any

# Prefix -> (human label, one-line purpose). Prefixes not listed here
# still appear, under their own name: an unknown group must never be
# silently dropped, because that is how a tool becomes invisible.
# Prefix -> family. Several prefixes fold into one family on purpose:
# the raw prefixes produce 45 groups, which is the same 240-item wall
# with extra steps. `code_project`, `code_session`, `code_run` and
# `code_artifact` are one subject to a reader even though they are four
# namespaces to the code.
#
# Measured before choosing the families: mobile 40, mission 30,
# desktop 13, fs 13, scenario 12, code_* 25 across four prefixes.
PREFIX_FAMILY: dict[str, str] = {
    "exec": "shell", "sudo": "shell", "runtime": "shell",
    "fs": "files", "document": "files", "image": "files",
    "browser": "browser", "cdp": "browser",
    "mobile": "phone", "emulator": "phone",
    "desktop": "desktop", "desktop_app": "desktop",
    "input_helper": "desktop", "ocr": "desktop", "asr": "desktop",
    "memory": "memory",
    "mission": "missions", "scenario": "missions", "plan": "missions",
    "task": "missions", "watch": "missions", "hooks": "missions",
    "skill": "skills", "subagent": "skills", "react": "skills",
    "reflect": "skills", "custom": "skills", "tool_foundry": "skills",
    "relay": "relay",
    "net": "network", "service": "network",
    "sys": "system", "audit": "system", "ship": "system",
    "workbench": "system", "capability_gap": "system",
    "admin": "admin", "secrets": "admin",
    "mcp": "mcp", "mcp_server": "mcp",
    "code": "code", "code_project": "code", "code_session": "code",
    "code_run": "code", "code_artifact": "code", "code_matrix": "code",
    "git": "code",
}

# Family -> (label, one-line purpose).
FAMILY_LABELS: dict[str, tuple[str, str]] = {
    "shell": ("Shell", "Run commands on this machine."),
    "files": ("Files", "Read, write, edit files; documents and images."),
    "browser": ("Browser", "Drive a real browser: navigate, click, read, screenshot."),
    "phone": ("Phone", "Control an Android device: tap, type, screenshot, apps, camera."),
    "desktop": ("Desktop", "Windows, input injection, screen capture, OCR, speech."),
    "memory": ("Memory", "Remember and recall facts across sessions."),
    "missions": ("Missions & scheduling", "Long-running jobs, plans, watches, reports."),
    "skills": ("Skills & sub-agents", "Reusable procedures, delegation, authored tools."),
    "relay": ("Relay", "Message the operator and read their replies."),
    "network": ("Network", "HTTP, downloads, tunnels, connectivity."),
    "system": ("System", "Hardware, processes, inventory, audit, diagnostics."),
    "admin": ("Admin", "Updates, tokens, secrets, bridge management."),
    "mcp": ("MCP", "Talk to other MCP servers and author new ones."),
    "code": ("Code", "Projects, sessions, sandboxed execution, git."),
}


def _prefix(name: str) -> str:
    return name.split(".", 1)[0] if "." in name else name


def _family(name: str) -> str:
    """Which family a tool belongs to. Unknown prefixes keep their own.

    Falling back to the prefix rather than an "Other" bucket is
    deliberate: a new tool namespace should show up as itself and be
    noticed, not disappear into a pile nobody reads.
    """
    return PREFIX_FAMILY.get(_prefix(name), _prefix(name))


def categories(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group tools by prefix. Every tool lands somewhere."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for tool in tools:
        grouped.setdefault(_family(str(tool.get("name", ""))), []).append(tool)

    out: list[dict[str, Any]] = []
    for family in grouped:
        label, purpose = FAMILY_LABELS.get(
            family, (family.replace("_", " ").title(), ""))
        members = grouped[family]
        out.append({
            "id": family,
            "label": label,
            "purpose": purpose,
            "count": len(members),
            "tools": sorted(str(t.get("name", "")) for t in members),
        })
    # Biggest first: an agent skimming the list should meet the richest
    # surfaces before the one-tool corners.
    out.sort(key=lambda g: (-g["count"], g["id"]))
    return out


def guards(*, profile: str, yolo: bool, halted: bool,
           posture: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Every gate, its live state, and what it actually blocks.

    Written as data rather than prose so both the Dashboard and an agent
    consume the same thing. Divergence between "what the UI shows" and
    "what the agent is told" is how an operator ends up debugging a
    refusal that the screen says cannot happen.
    """
    return [
        {
            "id": "halt",
            "label": "HALT",
            "active": bool(halted),
            "blocking": bool(halted),
            "blocks": "Everything except read-only calls.",
            "turn_off": "POST /v1/control/unhalt, or the HALT button in Control.",
            "note": "The emergency stop. Independent of every other guard "
                    "on purpose -- a single switch that also disabled this "
                    "would remove the operator's last resort.",
        },
        {
            "id": "profile",
            "label": "Exec profile",
            "active": True,
            "value": profile,
            "blocking": profile != "owner-shell",
            "blocks": ("Commands outside the read-only allowlist, on this "
                       "machine and on attached phones."
                       if profile != "owner-shell" else "Nothing."),
            "turn_off": "Settings -> Access Profile -> Enable full shell.",
            "note": "owner-shell is what the desktop has always used: any "
                    "command the token holder could type.",
        },
        {
            "id": "yolo",
            "label": "Auto-approve (YOLO)",
            "active": bool(yolo),
            "blocking": not yolo,
            "blocks": ("Nothing outright -- but each risky tool call waits "
                       "for a human click." if not yolo else "Nothing."),
            "turn_off": "POST /v1/control/yolo with the ack token.",
            "note": "Not persisted: a restart returns to asking. An agent "
                    "loop left running unattended should not stay "
                    "auto-approved forever.",
        },
        {
            "id": "posture",
            "label": "Execution posture",
            "active": bool(posture),
            "value": posture or {},
            "blocking": bool(posture) and str((posture or {}).get("runtime")) == "allowlist",
            "blocks": "Sandboxing, network and filesystem limits for code.run.",
            "turn_off": "Control -> posture presets (naked removes the fence).",
            "note": "Independent of YOLO: auto-approval does not remove the "
                    "sandbox.",
        },
    ]


def describe(*, tools: list[dict[str, Any]], host: dict[str, Any],
             profile: str, yolo: bool, halted: bool,
             posture: dict[str, Any] | None = None,
             version: str = "") -> dict[str, Any]:
    """The whole self-description, in one object."""
    groups = categories(tools)
    active_guards = guards(profile=profile, yolo=yolo, halted=halted,
                           posture=posture)
    blocking = [g for g in active_guards if g.get("blocking")]

    return {
        "ok": True,
        "version": version,
        "host": host,
        "tool_count": len(tools),
        "categories": groups,
        "guards": active_guards,
        "blocked_by": [g["id"] for g in blocking],
        "hint": _hint(groups, blocking, host),
    }


def _hint(groups: list[dict[str, Any]], blocking: list[dict[str, Any]],
          host: dict[str, Any]) -> str:
    """One paragraph a model can act on without further calls."""
    total = sum(g["count"] for g in groups)
    where = host.get("class") or "unknown"
    if host.get("role") == "on-device":
        where = "an Android phone (running on the device itself)"
    elif where == "android":
        where = "an Android device"

    lines = [
        f"You are connected to an Arena bridge running on {where}. "
        f"{total} tools are available in {len(groups)} categories: "
        + ", ".join(f"{g['label']} ({g['count']})" for g in groups[:8])
        + ("..." if len(groups) > 8 else "")
        + ". Call tools/list for the full set with schemas.",
    ]
    if blocking:
        lines.append(
            "Currently restricted: "
            + "; ".join(f"{g['label']} -- {g['blocks']}" for g in blocking)
            + " Tell the operator what to change rather than working "
              "around it; the switches are in the Dashboard."
        )
    else:
        lines.append("No guards are currently blocking anything.")
    return " ".join(lines)
