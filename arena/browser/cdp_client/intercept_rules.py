"""CDP network interception components."""
from __future__ import annotations

from typing import TYPE_CHECKING

from arena.browser.cdp_client.common import List
from arena.browser.cdp_client.intercept_rule import InterceptRule


class CDPNetworkInterceptRulesMixin:
    if TYPE_CHECKING:  # pragma: no cover - typing only
        # Supplied by the concrete class that mixes this in. Declared, not
        # assigned: annotations only, so runtime behaviour is unchanged.
        # Written down because an undeclared interface lets a real typo
        # hide among the noise it generates.
        _active: bool

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
