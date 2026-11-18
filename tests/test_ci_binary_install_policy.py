"""Keep scanner and resolver installs wheel-only with named legacy exceptions."""
from pathlib import Path
from unittest import TestCase

import yaml

ROOT = Path(__file__).resolve().parents[1]


def _pip_install_lines(filename):
    workflow = yaml.safe_load((ROOT / ".github/workflows" / filename).read_text())
    commands = []
    for job in workflow["jobs"].values():
        for step in job.get("steps", []):
            commands.extend(line.strip() for line in step.get("run", "").splitlines()
                            if line.strip().startswith("python -m pip install "))
    return commands


class BinaryInstallPolicyTests(TestCase):
    def _assert_policy(self, command, source_allowlist):
        normalized = command.replace("--only-binary=:all:", "--only-binary :all:")
        self.assertIn("--require-hashes", normalized)
        self.assertIn("--only-binary :all:", normalized)
        if source_allowlist is None:
            self.assertNotIn("--no-binary", normalized)
        else:
            self.assertIn("--no-binary " + source_allowlist + " ", normalized)
            self.assertEqual(normalized.count("--no-binary"), 1)

    def _assert_lock_policy(self, filename, lock, source_allowlist, expected_count):
        matches = [line for line in _pip_install_lines(filename) if line.endswith("-r " + lock)]
        self.assertEqual(len(matches), expected_count)
        for command in matches:
            self._assert_policy(command, source_allowlist)

    def test_scanner_resolver_and_mutation_install_policy(self):
        expected = [
            ("guarddog.yml", "ci/guarddog/requirements.txt", None, 1),
            ("relock-dependabot.yml", "requirements-relock.lock", None, 1),
            ("mutation-sweep.yml", "requirements-ci.txt", None, 1),
            ("mutation-sweep.yml", "requirements-mutation.lock", "glob2,mutmut", 1),
            ("security-scan.yml", "requirements-security.lock", None, 3),
        ]
        for filename, lock, source_allowlist, count in expected:
            with self.subTest(workflow=filename, lock=lock):
                self._assert_lock_policy(filename, lock, source_allowlist, count)
