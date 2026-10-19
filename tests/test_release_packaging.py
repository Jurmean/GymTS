"""Regressions for distribution pollution and credential-pattern checks."""

import importlib.util
from pathlib import Path
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_release.py"
SPEC = importlib.util.spec_from_file_location("gymts_release_check", SCRIPT)
release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release)


class ReleasePackagingTests(unittest.TestCase):
    def test_source_and_distribution_metadata_are_allowed(self):
        for name in ("gymts/contracts/types.py", "gymts/py.typed", "gymts-0.3.0/README.md",
                     "gymts-0.3.0/gymts.egg-info/PKG-INFO", "gymts-0.3.0.dist-info/METADATA"):
            with self.subTest(name=name):
                release.check_member(name, b"ordinary source")

    def test_local_outputs_caches_and_credentials_are_rejected(self):
        for name in ("output/experiments/result.json", "gymts/__pycache__/test.pyc", ".env",
                     "gymts/.env.production", "gymts/credentials.json", "gymts/id_rsa",
                     "gymts/service-account-prod.json", "gymts/key.pem", "gymts/run.sqlite3",
                     "gymts/run.sqlite3-wal", "gymts/build/temp.c",
                     ".gymts-ppt-build/render.png", "gymts/.aws/credentials"):
            with self.subTest(name=name), self.assertRaises(release.ReleaseError):
                release.check_member(name)

    def test_absolute_and_traversal_member_paths_are_rejected(self):
        for name in ("/tmp/example.py", "../example.py", "gymts/../../example.py", "gymts\\example.py",
                     "C:/example.py", "C:example.py"):
            with self.subTest(name=name), self.assertRaises(release.ReleaseError):
                release.check_member(name)

    def test_secret_values_are_not_echoed_in_errors(self):
        token = b"sk-" + b"x" * 40
        with self.assertRaises(release.ReleaseError) as captured:
            release.check_member("gymts/config.py", token)
        self.assertNotIn(token.decode(), str(captured.exception))
        self.assertIn("gymts/config.py", str(captured.exception))

    def test_placeholder_environment_variable_is_allowed(self):
        release.check_member("examples/candidate.json", b'{"api_key_env": "CHATTS_API_KEY"}')


if __name__ == "__main__":
    unittest.main()
