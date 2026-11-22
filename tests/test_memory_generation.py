import json
from pathlib import Path
import shutil
import tempfile
import unittest
from tavi.memory_generation import native_directory,validate_worker_realm


class GenerationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)/'one';self.root.mkdir()
    def test_reopen_retains_identity_but_same_named_stores_do_not_share_banks(self):
        first=native_directory(self.root);self.assertEqual(first,native_directory(self.root))
        other=Path(self.tmp.name)/'two';other.mkdir();second=native_directory(other)
        self.assertNotEqual(first.name,second.name);self.assertEqual(first.parent.name,second.parent.name)
    def test_copied_manifest_cannot_silently_reuse_original_native_banks(self):
        native_directory(self.root);other=Path(self.tmp.name)/'copy';shutil.copytree(self.root,other)
        with self.assertRaises(ValueError):native_directory(other)
    def test_partial_or_modified_manifest_blocks_without_generating_another_identity(self):
        native_directory(self.root);file=self.root/'native-generation.json';original=file.read_bytes()
        for bad in [b'{',json.dumps({'version':1,'root':str(self.root.resolve()),'generation':'../foreign'}).encode()]:
            file.write_bytes(bad)
            with self.assertRaises(ValueError):native_directory(self.root)
            self.assertEqual(file.read_bytes(),bad)
        file.write_bytes(original)
    def test_legacy_native_data_is_preserved_and_requires_explicit_migration(self):
        d=self.root/'native';d.mkdir();file=d/'source-ledger.sqlite3';file.write_bytes(b'existing')
        with self.assertRaises(ValueError):native_directory(self.root)
        self.assertEqual(file.read_bytes(),b'existing');self.assertFalse((self.root/'native-generation.json').exists())
    def test_symlink_or_broad_manifest_permissions_cannot_select_a_generation(self):
        native_directory(self.root);file=self.root/'native-generation.json';file.chmod(0o644)
        with self.assertRaises(ValueError):native_directory(self.root)
        file.chmod(0o600);copy=self.root/'copy.json';shutil.copy2(file,copy);file.unlink();file.symlink_to(copy)
        with self.assertRaises(ValueError):native_directory(self.root)
    def test_fixture_generation_cannot_be_opened_as_real_household_sources(self):
        directory=native_directory(self.root,source_realm='fixture');before=(self.root/'native-generation.json').read_bytes()
        validate_worker_realm(directory,'fixture')
        with self.assertRaises(ValueError):validate_worker_realm(directory,'household')
        self.assertEqual(before,(self.root/'native-generation.json').read_bytes())
    def test_household_generation_cannot_be_reused_by_experiment_worker(self):
        directory=native_directory(self.root);validate_worker_realm(directory,'household')
        with self.assertRaises(ValueError):validate_worker_realm(directory,'fixture')
    def test_legacy_unlabelled_generation_is_fixture_only_without_rewriting(self):
        directory=native_directory(self.root,source_realm='fixture');file=self.root/'native-generation.json'
        body=json.loads(file.read_text());body.pop('source_realm');file.write_text(json.dumps(body));before=file.read_bytes()
        validate_worker_realm(directory,'fixture')
        with self.assertRaises(ValueError):validate_worker_realm(directory,'household')
        self.assertEqual(file.read_bytes(),before)
    def test_source_wording_is_selected_by_trusted_worker_mode_not_source_text(self):
        from experiments.memory.worker import Worker
        w=Worker.__new__(Worker);self.assertTrue(w.source_context().startswith('Fictional household'))
        w.source_realm='household';self.assertTrue(w.source_context().startswith('Household conversations.'))
        self.assertNotIn('Fictional',w.source_context());w.source_realm='untrusted override'
        with self.assertRaises(ValueError):w.source_context()


if __name__=='__main__':unittest.main()
