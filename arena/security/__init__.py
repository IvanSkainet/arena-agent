"""Security gate domain package.

Holds the alert-processing logic that ``scripts/security_alerts_check.py``
used to carry itself. The script stays as the CLI entrypoint; the
decisions live here, where they can be imported and tested directly
(#190).
"""

from arena.security.alerts import SEVERITY_ORDER, code_scanning_ref, collect, main

__all__ = ["SEVERITY_ORDER", "code_scanning_ref", "collect", "main"]
