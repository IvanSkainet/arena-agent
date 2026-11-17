"""T72: a clean pip-audit result must cover the requirements it audited."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import TestCase

from arena.security_audit_coverage import check_coverage

ROOT = Path(__file__).resolve().parents[1]


def _dependency(name="demo", version="2.1", **extra):
    return {"name": name, "version": version, "vulns": [], **extra}


class AuditCoverageTests(TestCase):
    def test_full_inventory_and_normalized_names(self):
        check_coverage([_dependency("Demo_Package"), _dependency("transitive")],
                       "# generated input\n\nDemo-Package[extra]>=2,<3\n")

    def test_empty_partial_stale_and_skipped_inventory_are_not_clean(self):
        cases = [
            [], [_dependency("other")], [_dependency(version="1")],
            [_dependency(skip_reason="unavailable")],
            [_dependency(version="not-a-version")], [_dependency(name="")],
            [_dependency(name="bad/name")],
            [_dependency(), _dependency("Demo")],
        ]
        for dependencies in cases:
            with self.subTest(dependencies=dependencies), self.assertRaises(ValueError):
                check_coverage(dependencies, "demo>=2")

    def test_requirements_are_intersected_not_overwritten(self):
        with self.assertRaises(ValueError):
            check_coverage([_dependency()], "demo>=2\ndemo<2")

    def test_unknown_or_empty_requirements_are_not_an_audit(self):
        for text in ("", "# only a comment", "-r other.txt", "--index-url https://pypi.org",
                     "demo @ https://example.test/demo.whl", "demo=>2"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                check_coverage([_dependency()], text)

    def test_markers_use_the_explicit_scanner_environment(self):
        text = 'demo>=2; sys_platform == "win32"'
        check_coverage([], text, {"sys_platform": "linux"})
        check_coverage([_dependency()], text, {"sys_platform": "win32"})
        with self.assertRaises(ValueError):
            check_coverage([], text, {"sys_platform": "win32"})

    def test_prerelease_versions_still_obey_requested_bounds(self):
        with self.assertRaises(ValueError):
            check_coverage([_dependency(version="3rc1")], "demo>=3")
        check_coverage([_dependency(version="3rc1")], "demo==3rc1")

    def _gate(self, directory, report, requirements="demo>=2", *, omit_input=False):
        report_path = directory / "audit.json"
        report_path.write_text(json.dumps(report), encoding="utf-8")
        requirements_path = directory / "requirements.txt"
        requirements_path.write_text(requirements, encoding="utf-8")
        args = [sys.executable, str(ROOT / "scripts" / "security_gate.py"),
                "pip-audit", str(report_path)]
        if not omit_input:
            args.extend(["--requirements", str(requirements_path)])
        return subprocess.run(args, cwd=ROOT, capture_output=True, text=True, timeout=15)

    def test_cli_empty_missing_coverage_and_cve_are_distinct_from_clean(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            clean = {"dependencies": [_dependency()]}
            result = self._gate(directory, clean)
            self.assertEqual(result.returncode, 0, result.stderr)
            for report in ({"dependencies": []}, {"dependencies": [_dependency("other")]},
                           {"dependencies": [_dependency(version="1")]},
                           {"dependencies": [_dependency(vulns=[None])]}, {}):
                with self.subTest(report=report):
                    result = self._gate(directory, report)
                    self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                    self.assertNotIn("OK:", result.stdout)
            result = self._gate(directory, clean, omit_input=True)
            self.assertEqual(result.returncode, 2)
            cve = {"id": "CVE-test", "fix_versions": ["2.2"]}
            result = self._gate(directory, {"dependencies": [_dependency(vulns=[cve])]})
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertIn("CVE-test", result.stdout)

    def test_cli_does_not_treat_unreadable_requirements_as_clean(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            report = directory / "audit.json"
            report.write_text(json.dumps({"dependencies": [_dependency()]}), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "security_gate.py"), "pip-audit",
                 str(report), "--requirements", str(directory / "absent")],
                cwd=ROOT, capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 2)
            self.assertIn("coverage", result.stderr)

    def test_ci_and_local_gate_receive_the_actual_scanner_input(self):
        workflow = (ROOT / ".github" / "workflows" / "security-scan.yml").read_text()
        makefile = (ROOT / "Makefile").read_text()
        self.assertIn("security_gate.py pip-audit pip-audit.json --requirements runtime-reqs.txt",
                      workflow)
        self.assertIn("security_gate.py pip-audit /tmp/pip-audit-local.json "
                      "--requirements /tmp/runtime-reqs.txt", makefile)
