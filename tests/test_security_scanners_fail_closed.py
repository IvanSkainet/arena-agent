"""T40 workflow wiring: scanners cannot turn execution/report failure green."""
from __future__ import annotations

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
WORKFLOW = REPO / ".github" / "workflows" / "security-scan.yml"
MAKEFILE = REPO / "Makefile"
yaml = pytest.importorskip("yaml")


def _workflow() -> dict:
    value = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _job_text(name: str) -> str:
    job = _workflow()["jobs"][name]
    return "\n".join(
        str(step.get("run", "")) + "\n" + str(step)
        for step in job.get("steps", [])
    )


def test_security_workflow_has_manual_acceptance_trigger() -> None:
    workflow = _workflow()
    triggers = workflow.get("on") or workflow.get(True) or {}
    assert "workflow_dispatch" in triggers


def test_advisory_scanner_jobs_have_no_continue_on_error() -> None:
    jobs = _workflow()["jobs"]
    for name in ("trufflehog", "osv-scanner", "sbom-and-grype", "socket-firewall", "devskim"):
        for step in jobs[name]["steps"]:
            assert step.get("continue-on-error") is not True, (name, step.get("name"))


def test_command_scanners_capture_only_documented_policy_exits() -> None:
    for name in ("bandit", "semgrep", "pip-audit"):
        text = _job_text(name)
        assert "scanner_rc=$?" in text
        assert "scanner_contract_gate.py" in text
        assert "--allowed-exits 0,1" in text
        assert "|| true" not in text

    makefile = MAKEFILE.read_text(encoding="utf-8")
    for target in ("security-bandit", "security-semgrep", "security-pip-audit"):
        section = makefile.split(f"{target}:", 1)[1].split("\n\n", 1)[0]
        assert "scanner_rc=$$?" in section
        assert "scanner_contract_gate.py" in section
        assert "--allowed-exits 0,1" in section
        assert "|| true" not in section


def test_osv_report_and_zero_findings_policy_are_explicit() -> None:
    text = _job_text("osv-scanner")
    assert "--format=json" in text
    assert "--output-file=osv-results.json" in text
    assert "--format osv --block finding" in text
    assert "if-no-files-found" in text and "error" in text


def test_syft_and_grype_reports_are_validated_with_critical_threshold() -> None:
    text = _job_text("sbom-and-grype")
    assert "--format cyclonedx" in text
    assert "output-format" in text and "json" in text
    assert "output-file" in text and "grype.json" in text
    assert "--format grype --block critical" in text
    assert "fail-build" in text and "False" in text
    assert "sbom.cyclonedx.json" in text and "grype.json" in text


def test_socket_firewall_execution_is_blocking() -> None:
    text = _job_text("socket-firewall")
    assert "command -v sfw" in text
    assert "test -s runtime-reqs.txt" in text
    assert "sfw pip install" in text


def test_devskim_sarif_policy_and_artifact_are_explicit() -> None:
    text = _job_text("devskim")
    assert "--format sarif --block error" in text
    assert "devskim-results.sarif" in text
    assert "if-no-files-found" in text and "error" in text
    assert "scripts/mutation_cache.json" in text
    assert "integrations/book_of_eternity_compatibility.json" in text
    assert "exclude-rules" not in text


def test_public_tunnel_diagnostic_uses_shared_strict_tls_policy() -> None:
    source = (REPO / "scripts" / "check_bridge.py").read_text(encoding="utf-8")
    assert "build_ssl_context(p_url)" in source
    assert "CERT_NONE" not in source
    assert "check_hostname = False" not in source


def test_trufflehog_verified_secret_policy_is_blocking() -> None:
    text = _job_text("trufflehog")
    assert "--only-verified" in text
    assert "continue-on-error" not in text
