# arena-agent development Makefile.
#
# Contributor entry points. Every check that CI runs is also
# runnable locally via `make security-scan`, so "passes locally"
# means "passes in CI".

PYTHON ?= python3
PYTEST ?= $(PYTHON) -m pytest
PIP    ?= $(PYTHON) -m pip

.PHONY: help test lint security-scan security-bandit security-semgrep security-pip-audit install-security-tools clean

help:
	@echo "arena-agent make targets:"
	@echo ""
	@echo "  test                    -- run the pytest suite"
	@echo "  lint                    -- ruff critical rules (F821, F811) + full report"
	@echo "  security-scan           -- run every security gate CI runs (bandit, semgrep, pip-audit)"
	@echo "  security-bandit         -- bandit only"
	@echo "  security-semgrep        -- semgrep only (9 rule packs)"
	@echo "  security-pip-audit      -- pip-audit only"
	@echo "  install-security-tools  -- pip install the security tools"
	@echo "  clean                   -- remove report artifacts + __pycache__"
	@echo ""
	@echo "See SECURITY.md for the full threat model and env-var reference."

# --------------------------------------------------------------------
# Test suite
# --------------------------------------------------------------------
# Same two flaky tests CI deselects, so the local run mirrors CI. If
# you're debugging one of the deselected tests, run it directly.
test:
	$(PYTEST) tests/ \
	    --deselect tests/test_superpowers_layout.py::test_sync_script_exists_and_executable \
	    --deselect tests/test_tunnels_probe.py::test_probe_tcp_timeout_short

# --------------------------------------------------------------------
# Lint
# --------------------------------------------------------------------
lint:
	@echo "-- critical (blocking) --"
	ruff check . --select F821,F811
	@echo "-- full report (informational) --"
	ruff check . --statistics || true

# --------------------------------------------------------------------
# Security scans
# --------------------------------------------------------------------
# `security-scan` is the umbrella target CI runs. Split subtargets
# exist for iteration (rerun just semgrep after a nosemgrep edit,
# without waiting for bandit + pip-audit).
security-scan: security-bandit security-semgrep security-pip-audit
	@echo ""
	@echo "================================================================"
	@echo "  All security gates PASSED"
	@echo "================================================================"

# bandit: 0 HIGH + 0 MEDIUM required. LOW is treated as code hygiene.
# --skip B101 = assert-used; asserts are legitimate in test code and
# a handful of runtime invariants.
security-bandit:
	@echo "-- bandit --"
	@bandit -r arena/ --skip B101 -f json -o /tmp/bandit-local.json > /dev/null 2>&1 || true
	@$(PYTHON) scripts/security_gate.py bandit /tmp/bandit-local.json

# semgrep: 9 rule packs, must exit with 0 findings.
security-semgrep:
	@echo "-- semgrep --"
	@semgrep \
	    --config=p/python \
	    --config=p/security-audit \
	    --config=p/owasp-top-ten \
	    --config=p/cwe-top-25 \
	    --config=p/insecure-transport \
	    --config=p/command-injection \
	    --config=p/xss \
	    --config=p/secrets \
	    --config=p/gitleaks \
	    --error --severity=ERROR --severity=WARNING \
	    --json --output=/tmp/semgrep-local.json arena/ > /dev/null 2>&1 || true
	@$(PYTHON) scripts/security_gate.py semgrep /tmp/semgrep-local.json

# pip-audit: 0 CVEs in runtime + full-extras deps.
security-pip-audit:
	@echo "-- pip-audit --"
	@$(PYTHON) scripts/extract_runtime_reqs.py > /tmp/runtime-reqs.txt
	@pip-audit --requirement /tmp/runtime-reqs.txt --format json \
	    --output /tmp/pip-audit-local.json > /dev/null 2>&1 || true
	@$(PYTHON) scripts/security_gate.py pip-audit /tmp/pip-audit-local.json

# Install the three security tools. Split so a contributor who only
# wants to run the scan doesn't drag in all test dependencies.
install-security-tools:
	$(PIP) install --upgrade \
	    "bandit>=1.7" \
	    "semgrep>=1.170" \
	    "pip-audit>=2.7"

clean:
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -f /tmp/bandit-local.json /tmp/semgrep-local.json /tmp/pip-audit-local.json /tmp/runtime-reqs.txt
