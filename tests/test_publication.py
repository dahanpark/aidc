"""Publication boundary checks: never exempt whole test files from secret scans."""
import importlib.util
import json
from pathlib import Path
import unittest
import tempfile
import subprocess
import hashlib

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("atlas_publication", ROOT / "scripts/publish_github.py")
PUBLICATION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PUBLICATION)


class PublicationTests(unittest.TestCase):
    def test_generated_digest_matches_git_blob_with_windows_line_endings(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            subprocess.run(['git','init',str(root)],check=True,capture_output=True)
            target=root/'README.md'
            PUBLICATION.write_generated(target,'한글\r\nsecond\rthird\n')
            raw=target.read_bytes()
            self.assertEqual(raw,'한글\nsecond\nthird\n'.encode('utf-8'))
            subprocess.run(['git','-c','core.autocrlf=true','add','README.md'],cwd=root,check=True,capture_output=True)
            blob=subprocess.check_output(['git','show',':README.md'],cwd=root)
            self.assertEqual(hashlib.sha256(blob).hexdigest(),hashlib.sha256(raw).hexdigest())

    def test_token_like_values_are_rejected_even_in_tests(self):
        for name in ["backend/app.py", "tests/test_pipeline.py"]:
            with self.subTest(name=name), self.assertRaises(RuntimeError):
                PUBLICATION.scan(name, ("ghp_" + "x" * 40).encode())

    def test_only_exact_known_reserved_domain_fixture_is_exempt(self):
        dummy = ("https://" + "user:" + "secret@example.com/").encode()
        PUBLICATION.scan("tests/test_pipeline.py", dummy)
        with self.assertRaises(RuntimeError):
            PUBLICATION.scan("backend/app.py", dummy)
        with self.assertRaises(RuntimeError):
            PUBLICATION.scan("tests/test_pipeline.py", dummy + ("sk-" + "x" * 48).encode())

    def test_other_credential_urls_are_rejected(self):
        with self.assertRaises(RuntimeError):
            PUBLICATION.scan("tests/test_pipeline.py", ("https://" + "other:" + "value@example.com/").encode())

    def test_policy_excludes_operational_and_historical_records(self):
        policy = json.loads((ROOT / "config/publication.json").read_text(encoding="utf-8"))
        self.assertEqual(policy["repository"], "dahanpark/aidc")
        self.assertEqual(policy["visibility"], "public")
        for name in ["store", "runtime", "backups", "exports", "output", "submission", "data/provenance", ".git"]:
            self.assertIn(name, policy["excluded_roots"])
            self.assertNotIn(name, policy["include_directories"])
        self.assertNotIn(".zip", policy["allowed_extensions"])
        self.assertNotIn(".lnk", policy["allowed_extensions"])
        self.assertIn(".geojson", policy["allowed_extensions"])
        for name in ["frontend/assets/maps/world.geojson", "frontend/assets/maps/korea.geojson"]:
            self.assertIn(name, policy["include_files"])


if __name__ == "__main__":
    unittest.main()
