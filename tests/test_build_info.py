import tempfile
import unittest
import os
import shutil
import subprocess
import base64
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

    @unittest.skipUnless(os.name=='nt' and shutil.which('powershell'),'Windows PowerShell launcher test')
    def test_windows_launcher_matches_python_and_marks_legacy_reuse(self):
        script=(Path(__file__).resolve().parents[1]/'scripts/start_atlas.ps1').read_text(encoding='utf-8')
        helper=script.split('# Runtime build helpers BEGIN')[1].split('# Runtime build helpers END')[0]
        helper=helper[helper.index('function '):]
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'backend').mkdir();(root/'frontend').mkdir()
            (root/'backend/a_b.py').write_text('one',encoding='utf-8');(root/'backend/a-z.py').write_text('two',encoding='utf-8')
            (root/'frontend/app.js').write_text('public',encoding='utf-8');(root/'config').mkdir()
            (root/'config/corporate_api_contract.json').write_text('PRIVATE',encoding='utf-8')
            path=str(root).replace("'","''")
            code=helper+f"\n$b=Get-AtlasRuntimeBuild '{path}'\nWrite-Output $b\nGet-AtlasLaunchUrl 'http://127.0.0.1:8765/' @{{}} $b\nGet-AtlasLaunchUrl 'http://127.0.0.1:8765/' @{{build_id=$b}} $b\n"
            result=subprocess.run(['powershell','-NoProfile','-NonInteractive','-EncodedCommand',base64.b64encode(code.encode('utf-16-le')).decode()],capture_output=True,timeout=15)
            self.assertEqual(result.returncode,0,result.stderr.decode(errors='replace'))
            output=result.stdout.decode().strip().splitlines()
            self.assertEqual(output,[runtime_build(root),'http://127.0.0.1:8765/?update_required=1','http://127.0.0.1:8765/'])
