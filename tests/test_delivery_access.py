"""Published deliveries must inherit access like ordinary workspace directories."""
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from final_assembly.core import build, verify_loaded
from final_assembly.manifest import digest, load_manifest
from final_assembly.paths import ROOT, workspace


OBSERVED_ACCESS = {}
SE_DACL_PROTECTED = 0x1000


def _windows_descriptor_control(path):
    """Read real NTFS security descriptor control with Windows' built-in API."""
    import ctypes
    from ctypes import wintypes

    security = ctypes.WinDLL('advapi32', use_last_error=True)
    get_file_security = security.GetFileSecurityW
    get_file_security.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_void_p,
        wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
    ]
    get_file_security.restype = wintypes.BOOL
    get_control = security.GetSecurityDescriptorControl
    get_control.argtypes = [
        ctypes.c_void_p, ctypes.POINTER(wintypes.WORD), ctypes.POINTER(wintypes.DWORD),
    ]
    get_control.restype = wintypes.BOOL
    required = wintypes.DWORD()
    # DACL_SECURITY_INFORMATION. No ACLs, ownership, or permissions are changed.
    if not get_file_security(str(path), 0x4, None, 0, ctypes.byref(required)):
        error = ctypes.get_last_error()
        if error != 122:  # ERROR_INSUFFICIENT_BUFFER is expected for this probe.
            raise ctypes.WinError(error)
    if not required.value:
        raise RuntimeError('Windows did not return a security descriptor size')
    descriptor = ctypes.create_string_buffer(required.value)
    if not get_file_security(str(path), 0x4, descriptor, len(descriptor), ctypes.byref(required)):
        raise ctypes.WinError(ctypes.get_last_error())
    control, revision = wintypes.WORD(), wintypes.DWORD()
    if not get_control(descriptor, ctypes.byref(control), ctypes.byref(revision)):
        raise ctypes.WinError(ctypes.get_last_error())
    return control.value


class DeliveryAccessTests(unittest.TestCase):
    def test_published_delivery_inherits_access_like_normal_sibling(self):
        parent = ROOT / '.runtime' / 'delivery-access-tests'
        parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=parent) as temp, workspace(temp):
            root = Path(temp)
            normal = root / 'normal-sibling'
            normal.mkdir()
            raw = b'# Delivery access\n\nApproved material remains readable.\n'
            (root / 'approved.md').write_bytes(raw)
            manifest = {'schema_version': 1, 'title': 'Offline access fixture', 'blocks': [
                {'id': 'approved', 'section': 'Delivery', 'order': 0, 'approved': True,
                 'source': {'path': 'approved.md', 'origin': 'offline test approval'}, 'sha256': digest(raw)}]}
            (root / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')

            result = build('manifest.json', 'delivery')
            self.assertTrue(result['passed'])
            delivery = root / 'delivery'
            actual = delivery / 'final.docx'
            self.assertTrue(actual.is_file())
            self.assertTrue(verify_loaded(load_manifest('manifest.json'), actual)['passed'])
            with ZipFile(actual) as archive:
                document = ET.fromstring(archive.read('word/document.xml'))
            word = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
            paragraphs = document.findall('.//' + word + 'sdtContent/' + word + 'p')
            self.assertEqual(
                [''.join(node.text or '' for node in p.iter(word + 't')) for p in paragraphs],
                ['Delivery access', 'Approved material remains readable.'],
            )

            if os.name == 'nt':
                normal_control = _windows_descriptor_control(normal)
                delivery_control = _windows_descriptor_control(delivery)
                normal_protected = bool(normal_control & SE_DACL_PROTECTED)
                delivery_protected = bool(delivery_control & SE_DACL_PROTECTED)
                OBSERVED_ACCESS.update({
                    'platform': 'windows', 'normal_descriptor_control': normal_control,
                    'delivery_descriptor_control': delivery_control,
                    'normal_dacl_protected': normal_protected,
                    'delivery_dacl_protected': delivery_protected,
                })
                self.assertFalse(normal_protected, 'The ordinary sibling should inherit its parent DACL')
                self.assertEqual(
                    delivery_protected, normal_protected,
                    'Published delivery retained a protected staging DACL instead of normal inheritance',
                )
            else:
                normal_mode = stat.S_IMODE(normal.stat().st_mode)
                delivery_mode = stat.S_IMODE(delivery.stat().st_mode)
                OBSERVED_ACCESS.update({
                    'platform': os.name, 'normal_directory_mode': oct(normal_mode),
                    'delivery_directory_mode': oct(delivery_mode),
                })
                self.assertEqual(delivery_mode, normal_mode)


if __name__ == '__main__':
    unittest.main()
