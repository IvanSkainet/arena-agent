"""Chat extension scaffold regressions."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_chat_extension_scaffold_exists():
    base = ROOT / "chat_extension"
    manifest = json.loads((base / "manifest.json").read_text(encoding="utf-8"))
    background = (base / "background.js").read_text(encoding="utf-8")
    content = (base / "content.js").read_text(encoding="utf-8")
    parser = (base / "parser.js").read_text(encoding="utf-8")
    adapter_sites = (base / "adapter_sites.js").read_text(encoding="utf-8")
    popup = (base / "popup.js").read_text(encoding="utf-8")
    popup_html = (base / "popup.html").read_text(encoding="utf-8")
    sidepanel = (base / "sidepanel.js").read_text(encoding="utf-8")
    popup_css = (base / "popup.css").read_text(encoding="utf-8")
    sidepanel_html = (base / "sidepanel.html").read_text(encoding="utf-8")
    adapters = (base / "adapters.js").read_text(encoding="utf-8")
    insert_strategies = (base / "insert_strategies.js").read_text(encoding="utf-8")
    insert_history = (base / "insert_history.js").read_text(encoding="utf-8")
    readme = (base / "README.md").read_text(encoding="utf-8")
    assert manifest["manifest_version"] == 3
    assert "background.js" in manifest["background"]["service_worker"]
    assert manifest["version"] == "0.14.41"
    assert "https://*.ts.net/*" in manifest["host_permissions"]
    assert "https://*.trycloudflare.com/*" in manifest["host_permissions"]
    assert manifest["action"]["default_popup"] == "popup.html"
    assert manifest["side_panel"]["default_path"] == "sidepanel.html"
    # v4.48.0 adds shadow_toolbar.js as the 7th content script (before
    # content.js) to expose window.arenaCreateShadowToolbar /
    # arenaDestroyShadowToolbar / arenaShadowToolbarButton to content.js.
    # The first 6 stay locked to preserve script ordering guarantees --
    # parser/adapters/strategies/settings/history must all be evaluated
    # before shadow_toolbar or content see them.
    assert manifest["content_scripts"][0]["js"][:6] == ["adapter_sites.js", "parser.js", "adapters.js", "insert_strategies.js", "settings.js", "insert_history.js"]
    assert manifest["content_scripts"][0]["js"][6] == "shadow_toolbar.js"
    # v0.14.2: diag.js sibling module carries the ring buffer +
    # late-submit poller so content.js stays under the 700-line
    # product-modularity threshold. Must load before content.js.
    assert manifest["content_scripts"][0]["js"][7] == "diag.js"
    assert manifest["content_scripts"][0]["js"][8] == "content.js"
    # v4.48.0: shadow_toolbar.css must be reachable from a content
    # script via chrome.runtime.getURL(); web_accessible_resources
    # publishes it against <all_urls>.
    war = manifest.get("web_accessible_resources", [])
    assert any(
        "shadow_toolbar.css" in (entry.get("resources") or [])
        and "<all_urls>" in (entry.get("matches") or [])
        for entry in war
    ), "shadow_toolbar.css must be listed in web_accessible_resources"
    assert "arena.preview" in background
    assert "arena.execute" in background
    assert "arena.testConnection" in background
    assert "arena.instructions" in background
    assert "/v1/extension/instructions" in background
    assert "arena.openSidePanel" in background
    assert "arena.replayHistory" in background
    assert "arena.clearHistory" in background
    assert "arena.scanPage" in background
    assert "scanActivePage" in background
    assert "```arena-tool" in parser
    assert "```jsonl" in parser
    assert "function_call_start" in parser
    assert "Insert" in content
    assert "Send" in content
    assert "Panel" in content
    assert "saveBtn" in popup_html
    assert "autoExecuteSafe" in popup_html
    assert "autoSubmitResult" in popup_html
    assert "insertStrategy" in popup_html
    assert "directDomText" in popup_html
    assert "directDomBlocks" in popup_html
    assert "directDomPreWrap" in popup_html
    assert "Auto (recommended)" in popup_html
    assert "Debug: native insertText" in popup_html
    assert "pageControlsBtn" in popup_html
    assert "scanBtn" in popup_html
    assert "panelBtn" in popup_html
    assert "arenaInstructionsBtn" in popup_html
    assert "jsonlInstructionsBtn" in popup_html
    assert "clearBtn" in popup_html
    assert "arena.getConfig" in popup
    assert "insertStrategy" in popup
    assert "arenaModeSummary" in popup
    assert "copyInstructions" in popup
    assert "chrome.runtime.lastError" in popup
    assert "describeBridgeResult" in background
    assert "payload_fingerprint" in background
    assert "historyAggregateKey" in background
    assert "HISTORY_AGGREGATE_MS" in background
    assert "normalizeBridgeUrl" in background
    assert "http://${url}" in background
    assert "bridgeFallbackBase" in background
    assert "bridgeFetchOnce" in background
    assert "bridge_url_fallback" in background
    assert "chrome.storage.local.set({bridgeToken})" in background
    assert "chrome.storage.sync.remove('bridgeToken')" in background
    assert "chrome.tabs.create" in background
    assert "resultErrorText" in content
    assert "attachControls(host, bar)" in content
    assert "mountedControls" in content
    assert "cleanupStaleControls" in content
    assert "arena.clearPageControls" in content
    assert "scanPageDiagnostics" in content
    assert "content_version" in content
    assert "manifest_version" in content
    assert "insert_script_version" in content
    assert "versionSummary" in content
    assert "arena.scanPage" in content
    assert "Arena ·" in content
    assert "controlsHost" in content
    assert "arenaCandidateHost" in adapters
    assert "arenaPruneAncestorCandidates" in adapters
    assert "arenaComposerSelection" in adapters
    assert "arenaSubmitButtonSelection" in adapters
    assert "scope_buttons" in adapters
    assert "visible_scope_buttons" in adapters
    assert "clearPageControls" in popup
    assert "scanPage" in popup
    assert "notifyActiveTab" in popup
    assert "Config load error" in popup
    assert "Saved, but verify failed" in popup
    assert "refreshBtn" in sidepanel_html
    assert "clearBtn" in sidepanel_html
    assert "runHistoryAction" in sidepanel
    assert "renderCardHeader" in sidepanel
    assert "arena-history-card" in popup_css
    assert "arenaInsertAndSubmit" in insert_strategies
    assert "arenaInsertEventTiming" in insert_history
    assert "arenaTryEditableInsert" in insert_strategies
    assert "ARENA_SITE_ADAPTERS" in adapter_sites
    assert "chat.deepseek.com" in adapter_sites
    assert "kimi.com" in adapter_sites
    assert "chat.qwen.ai" in adapter_sites
    # v0.14.1: three sites added after real-world scan-report review.
    assert "www.kimi.com" in adapter_sites, "www.kimi.com host alias missing -- Kimi's real URL uses the www.* subdomain"
    assert "chat.mistral.ai" in adapter_sites, "chat.mistral.ai adapter missing -- was falling back to generic"
    # GitHub Copilot lives under github.com/copilot/*; its hosts list
    # includes the bare github.com and a Copilot-only URL guard would
    # need the JS-side path check that adapter selection already does.
    assert "'copilot'" in adapter_sites or '"copilot"' in adapter_sites, \
        "copilot adapter name missing -- github.com/copilot was falling back to generic"
    # Version banner inside content.js and insert_strategies.js must
    # follow the extension version (was drifting at 0.13.27 while
    # manifest was 0.14.0 in v4.48.0 -- caught in v0.14.1 scan-reports).
    assert "ARENA_CONTENT_SCRIPT_VERSION = '0.14.41'" in content or \
        'ARENA_CONTENT_SCRIPT_VERSION = "0.14.41"' in content
    # v0.14.6: data-testid="user-message" removed from user-authored
    # attr list -- scan-reports on Grok / DuckAI / Arena.ai showed the
    # sites use that testid on the MESSAGE LIST CONTAINER, not just
    # on user turns, and every mount short-circuited. Regression guard:
    # the tuple ['data-testid', 'user-message'] must NOT be back in
    # the _USER_AUTHOR_ATTRS list. (Claude's `arenaIsAssistantNode`
    # still uses the same testid, but that is a Claude-specific site
    # check where the site really does honour the semantic.)
    adapters_body_v6 = (base / "adapters.js").read_text(encoding="utf-8")
    assert "['data-testid', 'user-message']" not in adapters_body_v6, (
        "data-testid='user-message' must not be in _USER_AUTHOR_ATTRS "
        "-- Grok / DuckAI use it on the whole message list container"
    )
    # v0.14.6: Qwen toolbar overlap fix -- shadow host now sits above
    # site action rows via position:relative + max int-safe z-index.
    shadow_css_v6 = (base / "shadow_toolbar.css").read_text(encoding="utf-8")
    assert "z-index: 10" in shadow_css_v6
    assert "position: relative" in shadow_css_v6
    assert "isolation: isolate" in shadow_css_v6
    # v0.14.5: user-authored filter reports WHY it matched so scan-page
    # events_recent tells us which ancestor / attribute / class hit.
    # Also switched to strict-equal on attr values (was includes(), which
    # made class="user-listing" trip the check).
    adapters_js_body_v5 = (base / "adapters.js").read_text(encoding="utf-8")
    assert "arenaWhyUserAuthored" in adapters_js_body_v5, (
        "adapters.js must expose arenaWhyUserAuthored so events_recent "
        "records the reason a block was skipped"
    )
    # Strict-equal or token match, no bare includes on attribute values.
    assert "lv === val" in adapters_js_body_v5
    # Composer target that was detached from the DOM must be cleared
    # from the cache (Qwen re-render on model switch).
    assert "__arenaLastComposerTarget = null" in adapters_js_body_v5, (
        "arenaComposerSelection must null out a detached last-composer hint"
    )
    # v0.14.4: plain-contenteditable insert plan puts directDomBlocks
    # first for multi-line payloads on non-ProseMirror composers
    # (Perplexity, Kimi) -- v0.14.3 had it as the third fallback
    # after wipe-between-strategies, which shipped a duplicate paste
    # when the wipe was unreliable. Assert directDomBlocks appears
    # earlier than paragraphFallback in the plan branch.
    insert_js = (base / "insert_strategies.js").read_text(encoding="utf-8")
    assert "'directDomBlocks', 'paragraphFallback'" in insert_js, (
        "plan must lead with directDomBlocks for plain contenteditable "
        "-- v0.14.3 wipe-chain shipped duplicate pastes on Perplexity/Kimi"
    )
    # v0.14.4: generic adapter is `passive` -- never mounts on unlisted
    # sites (previous versions mounted on GitHub READMEs that quoted
    # MCP JSONL, see bug #9 in the v0.14.3 scan-report).
    adapter_sites_js = (base / "adapter_sites.js").read_text(encoding="utf-8")
    # v0.14.27: generic moved to passiveUnlessComposer + strictJsonlFencing.
    assert ("passive: true" in adapter_sites_js
            or ("passiveUnlessComposer: true" in adapter_sites_js
                and "strictJsonlFencing: true" in adapter_sites_js)), (
        "generic adapter must guard against unlisted-site mounts"
    )
    assert "adapter.passive" in content or "adapter && adapter.passive" in content
    # v0.14.4: user-authored filter no longer walks form/composer
    # ancestors -- those heuristics caused Grok / DuckAI to skip
    # every chat block. Only explicit user-role attributes and a
    # narrow class-substring set trigger the skip.
    adapters_js_body = (base / "adapters.js").read_text(encoding="utf-8")
    assert "if (tag === 'form')" not in adapters_js_body, (
        "form-ancestor heuristic must not resurface -- caused massive "
        "false-positive SKIPS on Grok / DuckAI in v0.14.2/3"
    )
    assert "composerSelectors" in adapters_js_body  # still present in adapters
    # But composerSelectors check inside arenaIsInUserAuthoredNode is gone --
    # count occurrences (was 1 inside the helper before v0.14.4).
    # controlsHost hoists <div>-wrapped <pre> so Qwen no longer drifts
    # the toolbar above the site "..." menu.
    assert "querySelector('pre')" in content or 'querySelector("pre")' in content
    # v0.14.2 additions -- assert the new machinery is wired in.
    # (a) copilot must be pinned to the /copilot path prefix; the
    #     bare github.com hosts entry alone lets the adapter false-
    #     positive on any repository README that quotes MCP JSONL.
    assert "pathPrefix: '/copilot'" in adapter_sites
    # (b) arena.ai + duckai adapters must exist so they stop falling
    #     to the generic adapter (both were reported in scan-reports).
    assert "'arenaai'" in adapter_sites and "'arena.ai'" in adapter_sites
    assert "'duckai'" in adapter_sites and "'duck.ai'" in adapter_sites
    # (c) manifest must permit the new hosts so the content script
    #     actually loads there.
    for host_glob in ('https://arena.ai/*', 'https://duck.ai/*'):
        assert host_glob in manifest["host_permissions"], \
            f"{host_glob} missing from host_permissions"
    # (d) user-authored-node filter must be present -- guards against
    #     the false-positive "detected on user message" pattern seen
    #     on Grok / Copilot / DuckAI / Arena.ai scan-reports.
    adapters_js = (base / "adapters.js").read_text(encoding="utf-8")
    assert "arenaIsInUserAuthoredNode" in adapters_js
    # (e) diagnostics ring buffer + late-submit rescan + Enter fallback.
    #     Ring buffer + poller live in the diag.js sibling module
    #     (content.js consumes them off window to stay under the
    #     700-line product-modularity threshold).
    diag_js = (base / "diag.js").read_text(encoding="utf-8")
    assert "_arenaDiagPushEvent" in diag_js
    assert "arenaWaitForSubmit" in diag_js
    assert "events_recent" in content   # still surfaced via scanPageDiagnostics
    assert "enter-key-fallback" in (base / "insert_strategies.js").read_text(encoding="utf-8")
    # (f) parser must accept the inline `arguments` variant on the
    # start event (some models emit it that way instead of separate
    # `parameter` rows) -- caught in scan-report as "missing 'path'
    # argument" even though the payload had one.
    assert "row.arguments" in parser, (
        "parser.js must read arguments from function_call_start rows, "
        "not only from separate `type:\"parameter\"` rows"
    )
    assert (base / "manifest.json").exists()
    # Ensure www.kimi.com is listed in host_permissions too, otherwise
    # the content script would not even load on the URL the user hits.
    assert "https://www.kimi.com/*" in manifest["host_permissions"], \
        "www.kimi.com missing from host_permissions"
    assert "arenaMessageFingerprint" in adapters
    assert "arenaPayloadFingerprint" in adapters
    assert "arenaPayloadSemanticFingerprint" in adapters
    assert "arenaStableHash" in adapters
    assert "arenaDetectionText" in adapters
    assert "arenaIsComposerNode" in adapters
    assert "previewSummary" in content
    assert "dismissedControls" in content
    assert "mountedPayloadSemantics" in content
    assert "mountedSemanticOwners" in content
    assert "executionResults" in content
    assert "detectedPayloads" in content
    assert "payload_fingerprint" in content
    assert "detectedDetail" in content
    assert "suppressCurrentControls" in content
    assert "dismissed_controls" in content
    assert "arenaSplitJsonObjects" in parser
    assert "showPageControls" in popup
    assert "showControlsBtn" in popup_html
    assert "arena.showPageControls" in content
    assert "formatInsertText" in content
    assert "arenaRecordInsertEvent" in content
    assert "arena.insertEvent" in insert_history
    assert "attemptsSummary" in content
    assert "Auto used" in content
    assert "/v1/extension/execute" in readme

    # v4.48.0: Shadow DOM toolbar helpers must exist and expose the
    # three public entry-points content.js relies on.
    shadow_js = (base / "shadow_toolbar.js").read_text(encoding="utf-8")
    shadow_css = (base / "shadow_toolbar.css").read_text(encoding="utf-8")
    assert "arenaCreateShadowToolbar" in shadow_js
    assert "arenaDestroyShadowToolbar" in shadow_js
    assert "arenaShadowToolbarButton" in shadow_js
    # attachShadow with mode:'open' is the recipe MCP SuperAssistant
    # uses; we picked it for the same debugging-friendliness reason.
    assert "attachShadow" in shadow_js
    assert "mode: 'open'" in shadow_js or 'mode: "open"' in shadow_js
    # CSS must scope its rules to :host so a page that dropped the
    # extension's shadow root into an outer selector cannot bleed
    # into our own styling.
    assert ":host" in shadow_css
    assert ".arena-toolbar" in shadow_css
    assert ".arena-btn" in shadow_css

    # content.js must call the shadow-toolbar factory and stop using
    # the pre-v4.48.0 inline-style pattern for the injected bar.
    assert "arenaCreateShadowToolbar" in content
    assert "arenaShadowToolbarButton" in content or "arena-btn" in content
    # Explicit inline styles like `bar.style.cssText = ...` were
    # removed in v4.48.0; a regression that re-introduces them would
    # leak page styles back into the toolbar. Strip JS comment lines
    # first so a docstring mentioning the removed pattern (e.g. the
    # rationale block above makeButton) does not false-positive.
    import re as _re
    content_no_comments = _re.sub(r"^\s*//.*$", "", content, flags=_re.MULTILINE)
    content_no_comments = _re.sub(r"/\*.*?\*/", "", content_no_comments, flags=_re.DOTALL)
    assert "bar.style.cssText" not in content_no_comments, (
        "content.js still assigns bar.style.cssText outside comments -- "
        "the Shadow DOM refactor collapsed toolbar styling into "
        "shadow_toolbar.css and this leak resurrects light-DOM styles."
    )

