import json
from pathlib import Path
import tempfile
import unittest
from tavi.parent_readiness import save_readiness

class Tests(unittest.TestCase):
    def test_report_never_authorizes_child_cloud_and_stays_private(self):
        for status,scope in [('not_sure','not_checked'),('not_enabled','not_checked'),('enabled','explicit_zdr'),('enabled','inherits_zdr'),('enabled','not_checked')]:
            with self.subTest(status=status,scope=scope),tempfile.TemporaryDirectory() as root:
                result=save_readiness({'status':status,'scope':scope},root=root)
                p=Path(root)/result['file'];record=json.loads(p.read_text())
                self.assertFalse(result['child_cloud_authorized']);self.assertFalse(record['child_cloud_authorized'])
                self.assertFalse(record['provider_or_account_verified'])
                self.assertEqual(record['reported_status'],status)
                self.assertEqual(p.stat().st_mode&0o777,0o600)
                self.assertFalse(list(Path(root).glob('.readiness-*')))
    def test_invalid_or_inconsistent_report_is_not_saved(self):
        with tempfile.TemporaryDirectory() as root:
            for body in [{},{'status':'approved','scope':'explicit_zdr'},{'status':'not_sure','scope':'explicit_zdr'}]:
                with self.assertRaises(ValueError):save_readiness(body,root=root)
            self.assertEqual(list(Path(root).iterdir()),[])
