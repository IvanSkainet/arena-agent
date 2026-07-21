"""v0.14.42 / v4.52.5 tests: supported-host ranker for Scan Now.

Full DOM behaviour verified in jstest/smoke_v525.js.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CHAT_EXT = REPO_ROOT / "chat_extension"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def test_manifest_version_bumped():
    assert json.loads(_read(CHAT_EXT / "manifest.json"))["version"] in ("0.14.42",)


def test_content_script_version_bumped():
    assert "const ARENA_CONTENT_SCRIPT_VERSION = '0.14.42';" in _read(CHAT_EXT / "content.js")


def test_insert_strategies_version_bumped():
    assert "return '0.14.42';" in _read(CHAT_EXT / "insert_strategies.js")


def test_readme_mentions_v4_52_5():
    src = _read(CHAT_EXT / "README.md")
    assert "0.14.42" in src
    assert ("v4.52.5" in src or "v4.52.6" in src or "v4.53.0" in src or "v4.53.1" in src)


def test_constants_version_bumped():
    assert any(v in _read(REPO_ROOT / 'arena' / 'constants.py') for v in ('VERSION = "4.52.5"', 'VERSION = "4.52.6"', 'VERSION = "4.53.0"', 'VERSION = "4.53.1"', 'VERSION = "4.54.0"', 'VERSION = "4.54.1"', 'VERSION = "4.55.0"', 'VERSION = "4.55.1"', 'VERSION = "4.56.0"', 'VERSION = "4.57.0"', 'VERSION = "4.58.0"', 'VERSION = "4.59.0"', 'VERSION = "4.59.1"', 'VERSION = "4.60.0"', 'VERSION = "4.60.1"', 'VERSION = "4.60.2"', 'VERSION = "4.60.3"))


def test_pyproject_version_bumped():
    assert any(v in _read(REPO_ROOT / 'pyproject.toml') for v in ('version = "4.52.5"', 'version = "4.52.6"', 'version = "4.53.0"', 'version = "4.53.1"', 'version = "4.54.0"', 'version = "4.54.1"', 'version = "4.55.0"', 'version = "4.55.1"', 'version = "4.56.0"', 'version = "4.57.0"', 'version = "4.58.0"', 'version = "4.59.0"', 'version = "4.59.1"', 'version = "4.58.0"', 'version = "4.59.0"', 'version = "4.59.1"', 'version = "4.60.0"', 'version = "4.60.1"', 'version = "4.60.2"', 'version = "4.60.3"))


# ------------------------------------------------------------------
# Background: supported-host ranker
# ------------------------------------------------------------------

def test_background_has_supported_hosts_set():
    src = _read(CHAT_EXT / "background.js")
    assert "ARENA_SUPPORTED_CHAT_HOSTS" in src
    for host in ("chat.deepseek.com", "chat.qwen.ai", "chat.mistral.ai",
                 "gemini.google.com", "chat.z.ai", "claude.ai",
                 "chatgpt.com", "chat.openai.com", "openrouter.ai",
                 "grok.com", "kimi.com", "www.kimi.com",
                 "t3.chat", "arena.ai", "duck.ai", "perplexity.ai"):
        assert host in src, f"missing supported host: {host}"


def test_background_supported_hosts_match_adapter_sites():
    """The supported-host set in background.js MUST be a superset
    of every `hosts: [...]` entry in adapter_sites.js -- otherwise
    Scan Now will refuse to talk to a tab that our own content
    script actually injects on."""
    bg = _read(CHAT_EXT / "background.js")
    adapters = _read(CHAT_EXT / "adapter_sites.js")

    # Pull the set literal from background.js.
    m = re.search(r"const ARENA_SUPPORTED_CHAT_HOSTS = new Set\(\[(.+?)\]\);",
                  bg, flags=re.DOTALL)
    assert m, "supported hosts set not parseable"
    supported = set(re.findall(r"'([^']+)'", m.group(1)))

    # Path-scoped adapter hosts are ALLOWED to be excluded from
    # the plain set (they land in ARENA_PATH_SCOPED_ADAPTERS).
    m2 = re.search(r"const ARENA_PATH_SCOPED_ADAPTERS = \[(.+?)\];",
                   bg, flags=re.DOTALL)
    path_scoped = set()
    if m2:
        for entry in re.finditer(r"host:\s*'([^']+)'", m2.group(1)):
            path_scoped.add(entry.group(1))

    # Every `hosts: [...]` in adapter_sites.js must be covered.
    missing = []
    for hosts_block in re.finditer(r"hosts:\s*\[([^\]]+)\]", adapters):
        for host_match in re.finditer(r"'([^']+)'", hosts_block.group(1)):
            host = host_match.group(1)
            if host not in supported and host not in path_scoped:
                missing.append(host)
    assert not missing, (
        f"background.js supported set out of sync with adapter_sites.js -- "
        f"missing: {missing}. Add them to ARENA_SUPPORTED_CHAT_HOSTS or "
        f"ARENA_PATH_SCOPED_ADAPTERS."
    )


def test_background_ranker_prefers_supported_host():
    """Supported host must dominate other ranker signals."""
    src = _read(CHAT_EXT / "background.js")
    assert "score += 1000" in src


def test_background_path_scoped_adapters_present():
    """Copilot lives at github.com/copilot, DuckAI at
    duckduckgo.com/chat -- both must be path-checked, not
    treated as blanket hosts."""
    src = _read(CHAT_EXT / "background.js")
    assert "ARENA_PATH_SCOPED_ADAPTERS" in src
    assert "/copilot" in src
    assert "/chat" in src


def test_background_friendly_unsupported_active_tab_error():
    src = _read(CHAT_EXT / "background.js")
    assert "active tab is not a supported chat site" in src
    # The friendly message should NAME the supported sites so the
    # user knows what to open.
    for named in ("ChatGPT", "Claude", "Gemini", "Qwen", "DeepSeek"):
        assert named in src, f"friendly error should name {named}"


def test_background_diagnostic_exposes_supported_count():
    src = _read(CHAT_EXT / "background.js")
    assert "supported_tabs_seen" in src


def test_background_tabSummary_flags_supported():
    """Per-tab dump must carry an `is_supported` flag so the
    sidepanel can visually mark supported tabs."""
    src = _read(CHAT_EXT / "background.js")
    assert "is_supported" in src


# ------------------------------------------------------------------
# Sidepanel: supported-tab highlighting
# ------------------------------------------------------------------

def test_sidepanel_renders_supported_count():
    src = _read(CHAT_EXT / "sidepanel.js")
    assert "supported_tabs_seen" in src


def test_sidepanel_highlights_supported_tabs_in_sample():
    src = _read(CHAT_EXT / "sidepanel.js")
    # Bold "supported" tag in the sample-tabs list.
    assert "<b>supported</b>" in src or "'supported'" in src
    # Callout that supported tabs are bolded in the hint text.
    assert "supported chat sites bolded" in src
