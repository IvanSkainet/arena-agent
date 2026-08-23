"""CDP network interception components."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from arena.browser.cdp_client.intercept_rule import InterceptRule

if TYPE_CHECKING:  # pragma: no cover - typing only
    from arena.browser.cdp_client.browser import CDPBrowser

from arena.browser.cdp_client.common import Dict, List, Optional, base64, logger
from arena.browser.cdp_client.fetch_arbiter import CLAIMED, NOT_CLAIMED, get_arbiter

#: Arbiter subscriber name for the user-facing interception rules.
INTERCEPTOR_NAME = "network_interceptor"


class CDPNetworkInterceptRuntimeMixin:
    if TYPE_CHECKING:  # pragma: no cover - typing only
        # Supplied by the concrete class that mixes this in. Declared, not
        # assigned: annotations only, so runtime behaviour is unchanged.
        # Written down because an undeclared interface lets a real typo
        # hide among the noise it generates.
        _browser: CDPBrowser
        _paused_requests: Dict[str, Dict]
        _rules: List[InterceptRule]

    async def start(self, patterns: Optional[List[Dict]] = None) -> None:
        """Enable network interception.

        Args:
            patterns: Optional list of Fetch pattern dicts to pass to Fetch.enable.
                     If None, intercepts all requests.
                     Example: [{"urlPattern": "*://example.com/*"}]

        Goes through `FetchArbiter` rather than touching `Fetch` directly.
        Measured on live Chromium: a second `Fetch.enable` replaces the first
        one's patterns and `Fetch.disable` is global, so an interceptor that
        owned the domain by itself would silently disarm the #122 navigation
        guard the moment it started or stopped.
        """
        if self._active:
            return

        # Default: intercept everything
        if patterns is None:
            patterns = [{"urlPattern": "*"}]

        await get_arbiter(self._browser).register(
            INTERCEPTOR_NAME, self._on_request_paused_arbitrated, patterns=patterns
        )
        self._active = True
        logger.info("[CDPNetworkInterceptor] Interception started with %d pattern(s)", len(patterns))

    async def stop(self) -> None:
        """Disable network interception."""
        if not self._active:
            return

        await get_arbiter(self._browser).unregister(INTERCEPTOR_NAME)

        # Resume any paused requests before disabling
        for request_id, params in list(self._paused_requests.items()):
            try:
                await self._browser.send("Fetch.continueRequest", {"requestId": request_id})
            except Exception:
                pass
        self._paused_requests.clear()

        self._active = False
        logger.info("[CDPNetworkInterceptor] Interception stopped")

    async def _on_request_paused_arbitrated(self, params: Dict) -> str:
        """Arbiter adapter: report whether this request was disposed of here.

        The arbiter guarantees exactly one disposition per request, so a rule
        that matched must claim it and an unmatched one must not -- otherwise
        the request is either continued twice or stranded.
        """
        url = params.get("request", {}).get("url", "")
        resource_type = params.get("resourceType", "")
        if not any(rule.matches(url, resource_type) for rule in self._rules):
            return NOT_CLAIMED
        await self._on_request_paused(params)
        return CLAIMED

    async def _on_request_paused(self, params: Dict) -> None:
        """Handle Fetch.requestPaused — apply rules and decide action."""
        request_id = params.get("requestId", "")
        url = params.get("request", {}).get("url", "")
        resource_type = params.get("resourceType", "")

        # Find matching rule (first match wins)
        matched_rule = None
        for rule in self._rules:
            if rule.matches(url, resource_type):
                matched_rule = rule
                break

        if matched_rule is None:
            # No rule matched — continue the request normally
            try:
                await self._browser.send("Fetch.continueRequest", {"requestId": request_id})
            except Exception as e:
                logger.error("[CDPNetworkInterceptor] Failed to continue request %s: %s", request_id, e)
            return

        # Track paused request for safety-resume in stop()
        self._paused_requests[request_id] = params

        matched_rule.record_hit()
        logger.info(
            "[CDPNetworkInterceptor] Rule '%s' matched: %s %s → %s",
            matched_rule.name, params.get("request", {}).get("method", "?"),
            url[:80], matched_rule.action,
        )

        try:
            if matched_rule.action == "block":
                await self._browser.send("Fetch.failRequest", {
                    "requestId": request_id,
                    "reason": "BlockedByClient",
                })

            elif matched_rule.action == "redirect":
                # Use continueRequest with url for true network-level redirect
                await self._browser.send("Fetch.continueRequest", {
                    "requestId": request_id,
                    "url": matched_rule.redirect_url,
                })

            elif matched_rule.action == "modify_headers":
                headers = params.get("request", {}).get("headers", {})
                # Remove specified headers
                for h in matched_rule.remove_request_headers:
                    headers.pop(h, None)
                # Add/modify headers
                headers.update(matched_rule.modify_request_headers)
                # Build CDP header list
                header_list = [{"name": k, "value": v} for k, v in headers.items()]
                await self._browser.send("Fetch.continueRequest", {
                    "requestId": request_id,
                    "headers": header_list,
                })

            elif matched_rule.action == "mock":
                body_b64 = ""
                if matched_rule.mock_body:
                    body_b64 = base64.b64encode(
                        matched_rule.mock_body.encode("utf-8")
                    ).decode("ascii")
                header_list = [
                    {"name": k, "value": v}
                    for k, v in matched_rule.mock_headers.items()
                ]
                await self._browser.send("Fetch.fulfillRequest", {
                    "requestId": request_id,
                    "responseCode": matched_rule.mock_status,
                    "responseHeaders": header_list,
                    "body": body_b64,
                })

            else:
                # Unknown action — continue normally (should not happen due to validation)
                logger.warning("[CDPNetworkInterceptor] Unknown action '%s', continuing request", matched_rule.action)
                await self._browser.send("Fetch.continueRequest", {"requestId": request_id})

            # Remove from paused tracking after successful handling
            self._paused_requests.pop(request_id, None)

        except Exception as e:
            logger.error("[CDPNetworkInterceptor] Error handling paused request %s: %s", request_id, e)
            # Try to continue the request to avoid it hanging forever
            try:
                await self._browser.send("Fetch.continueRequest", {"requestId": request_id})
                self._paused_requests.pop(request_id, None)
            except Exception:
                pass
