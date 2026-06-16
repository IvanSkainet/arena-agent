"""CDP network interception components."""
from __future__ import annotations

from cdp_browser_modules.common import *  # noqa: F401,F403

from cdp_browser_modules.intercept_rule import InterceptRule

class CDPNetworkInterceptRuntimeMixin:
    async def start(self, patterns: Optional[List[Dict]] = None) -> None:
        """Enable network interception.

        Args:
            patterns: Optional list of Fetch pattern dicts to pass to Fetch.enable.
                     If None, intercepts all requests.
                     Example: [{"urlPattern": "*://example.com/*"}]
        """
        if self._active:
            return

        # Default: intercept everything
        if patterns is None:
            patterns = [{"urlPattern": "*"}]

        await self._browser.send("Fetch.enable", {
            "patterns": patterns,
            "handleAuthRequests": False,
        })

        self._browser.on("Fetch.requestPaused", self._on_request_paused)
        self._active = True
        logger.info("[CDPNetworkInterceptor] Interception started with %d pattern(s)", len(patterns))

    async def stop(self) -> None:
        """Disable network interception."""
        if not self._active:
            return

        self._browser.off("Fetch.requestPaused", self._on_request_paused)

        # Resume any paused requests before disabling
        for request_id, params in list(self._paused_requests.items()):
            try:
                await self._browser.send("Fetch.continueRequest", {"requestId": request_id})
            except Exception:
                pass
        self._paused_requests.clear()

        try:
            await self._browser.send("Fetch.disable")
        except Exception:
            pass

        self._active = False
        logger.info("[CDPNetworkInterceptor] Interception stopped")

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
