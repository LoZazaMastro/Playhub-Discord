import importlib.util
import io
from pathlib import Path
import tarfile
import tempfile
import unittest
import zipfile

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('secret_check',ROOT/'scripts/check-secrets.py')
scanner=importlib.util.module_from_spec(spec);spec.loader.exec_module(scanner)

class SecretPayloadTests(unittest.TestCase):
    def test_archive_member_names_never_echo_matched_values(self):
        marker=b'AI'+b'za'+b'x'*35
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for kind in ('zip','tar.gz'):
                with self.subTest(kind=kind):
                    path=root/('payload.'+kind)
                    member=marker.decode()+'.js'
                    if kind=='zip':
                        with zipfile.ZipFile(path,'w') as archive:
                            archive.writestr(member,marker)
                    else:
                        with tarfile.open(path,'w:gz') as archive:
                            item=tarfile.TarInfo(member);item.size=len(marker)
                            archive.addfile(item,io.BytesIO(marker))
                    with self.assertRaises(ValueError) as failure:
                        scanner.check(root,[path])
                    self.assertNotIn(marker.decode(),str(failure.exception))
                    self.assertIn('embedded Google API credential',str(failure.exception))

    def test_plain_javascript_and_archive_findings_never_include_matched_value(self):
        marker=b'AI'+b'za'+b'x'*35
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            direct=root/'renderer.js';direct.write_bytes(b'key="'+marker+b'"')
            source=root/'source.tar.gz'
            with tarfile.open(source,'w:gz') as archive:
                item=tarfile.TarInfo('src/translate.ts');item.size=len(marker)
                archive.addfile(item,io.BytesIO(marker))
            runtime=root/'runtime.zip'
            with zipfile.ZipFile(runtime,'w') as archive:archive.writestr('resources/app.asar',marker)
            for path in (direct,source,runtime):
                findings=scanner.scan_file(path)
                self.assertEqual(len(findings),1)
                self.assertNotIn(marker.decode(),str(findings))

    def test_current_bundled_vencord_and_corresponding_source_contain_no_key(self):
        for path in (ROOT/'runtime/vencord/vencordDesktopRenderer.js',ROOT/'runtime/sources/Vencord-source.tar.gz'):
            self.assertEqual(scanner.scan_file(path),[])
