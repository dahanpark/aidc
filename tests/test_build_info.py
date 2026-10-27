import tempfile
import unittest
from pathlib import Path
from backend.build_info import runtime_build


class BuildInfoTests(unittest.TestCase):
    def test_changed_runtime_and_private_data_are_distinguished(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'backend').mkdir();(root/'config').mkdir()
            runtime=root/'backend/sample.py';runtime.write_text('one',encoding='utf-8')
            first=runtime_build(root)
            (root/'config/corporate_api_contract.json').write_text('PRIVATE',encoding='utf-8')
            (root/'store').mkdir();(root/'store/secret.json').write_text('PRIVATE',encoding='utf-8')
            self.assertEqual(first,runtime_build(root))
            runtime.write_text('two',encoding='utf-8');self.assertNotEqual(first,runtime_build(root))

    def test_fingerprint_is_deterministic_and_has_no_paths_or_content(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'frontend').mkdir();(root/'frontend/app.js').write_text('public',encoding='utf-8')
            value=runtime_build(root);self.assertEqual(value,runtime_build(root));self.assertRegex(value,r'^[0-9a-f]{20}$')
