"""CDP network interception components."""
from __future__ import annotations

from cdp_browser_modules.common import *  # noqa: F401,F403

from cdp_browser_modules.intercept_rule import InterceptRule

class CDPNetworkInterceptRulesMixin:
    def active(self) -> bool:
        """Whether interception is currently active."""
        return self._active

    def add_rule(self, rule: InterceptRule) -> None:
        """Add an interception rule."""
        self._rules.append(rule)

    def remove_rule(self, name: str) -> bool:
        """Remove a rule by name. Returns True if found and removed."""
        before = len(self._rules)
        self._rules = [r for r in self._rules if r.name != name]
        return len(self._rules) < before

    def get_rules(self) -> List[InterceptRule]:
        """Get all rules."""
        return list(self._rules)

    def clear_rules(self) -> None:
        """Remove all rules."""
        self._rules.clear()

    def block_urls(self, *url_patterns: str, name: str = "") -> None:
        """Block requests matching any of the URL patterns.

        Args:
            url_patterns: Substrings to match in request URLs
            name: Optional name for the rule set
        """
        for i, pattern in enumerate(url_patterns):
            self.add_rule(InterceptRule(
                name=f"{name or 'block'}-{i}",
                url_pattern=pattern,
                action="block",
            ))

    def add_redirect(self, from_pattern: str, to_url: str, name: str = "redirect") -> None:
        """Redirect requests matching a URL pattern to a different URL.

        Args:
            from_pattern: Substring to match in request URLs
            to_url: URL to redirect to
            name: Rule name
        """
        self.add_rule(InterceptRule(
            name=name,
            url_pattern=from_pattern,
            action="redirect",
            redirect_url=to_url,
        ))

    def mock_endpoint(self, url_pattern: str, body: str, status: int = 200,
                      content_type: str = "application/json", name: str = "mock") -> None:
        """Mock responses for requests matching a URL pattern.

        Args:
            url_pattern: Substring to match in request URLs
            body: Response body string
            status: HTTP status code (default: 200)
            content_type: Content-Type header (default: application/json)
            name: Rule name
        """
        self.add_rule(InterceptRule(
            name=name,
            url_pattern=url_pattern,
            action="mock",
            mock_status=status,
            mock_body=body,
            mock_content_type=content_type,
        ))
