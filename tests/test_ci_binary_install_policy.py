"""Keep scanner and resolver installs wheel-only with named legacy exceptions."""
from pathlib import Path
from unittest import TestCase

import yaml

ROOT = Path(__file__).resolve().parents[1]


class BinaryInstallPolicyTests(TestCase):
    def test_scanner_resolver_and_mutation_install_policy(self):
        expected = {
            "guarddog.yml": {"ci/guarddog/requirements.txt": None},
            "relock-dependabot.yml": {"requirements-relock.lock": None},
            "mutation-sweep.yml": {
                "requirements-ci.lock": None,
                "requirements-mutation.lock": "glob2,mutmut",
            },
        }
        for filename, locks in expected.items():
            workflow = yaml.safe_load((ROOT / ".github/workflows" / filename).read_text())
            lines = [line.strip() for job in workflow["jobs"].values()
                     for step in job.get("steps", [])
                     for line in step.get("run", "").splitlines()
                     if line.strip().startswith("python -m pip install ")]
            for lock, source_allowlist in locks.items():
                matches = [line for line in lines if line.endswith("-r " + lock)]
                with self.subTest(workflow=filename, lock=lock):
                    self.assertEqual(len(matches), 1)
                    command = matches[0]
                    self.assertIn("--require-hashes", command)
                    self.assertIn("--only-binary :all:", command)
                    if source_allowlist is None:
                        self.assertNotIn("--no-binary", command)
                    else:
                        self.assertIn("--no-binary " + source_allowlist + " ", command)
                        self.assertEqual(command.count("--no-binary"), 1)
