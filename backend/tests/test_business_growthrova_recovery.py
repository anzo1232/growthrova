"""Offline operator recovery boundary; never opens a configured runtime."""
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from business_asset_catalog import initialise_originals
from business_marketing_offline import OfflineMarketingDocuments, OfflineDocumentAccessError
from business_growthrova_paid_delivery import PaidDelivery
from business_growthrova_recovery import diagnostics, snapshot, prepare_restore


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        # Exercise the real reserve on the workspace volume; /tmp can be a
        # smaller memory filesystem that correctly refuses every real snapshot.
        self.tmp = tempfile.TemporaryDirectory(prefix='.recovery-check-', dir=Path(__file__).resolve().parents[1])
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.origin = 'https://isolated.example'
        self.path = self.root / 'source.sqlite3'
        self.repo = OfflineMarketingDocuments(str(self.path), lambda: ({'id': 'owner'}, None),
                                             lambda org, user: ({'id': org}, None), project_origin=self.origin)
        os.chmod(self.path, 0o600)
        PaidDelivery(self.repo)
        self.writer = sqlite3.connect(self.path)
        self.addCleanup(self.writer.close)
        self.writer.execute('PRAGMA journal_mode=WAL')
        self.writer.execute('PRAGMA wal_autocheckpoint=0')
        initialise_originals(self.writer)
        self.writer.execute('INSERT INTO marketing_drafts VALUES(?,?,?,?,?)',
                            ('doc', 7, '{"private":"customer wording"}', 1, 2))
        self.writer.execute('INSERT INTO offline_document_owners VALUES(?,?,?)', ('doc', 'owner', 'business'))
        self.writer.execute('INSERT INTO business_asset_originals VALUES(?,?,?,?,?)',
                            ('business', 'doc', 'asset', 'owner', b'original\x00bytes'))
        self.writer.execute('INSERT INTO growthrova_paid_jobs VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                            ('job', 'doc', 'meta', 'owner', 'business', '{}', 'live', 'uncertain', 1, 'claim', 99, '{"hold":true}'))
        self.writer.commit()

    def test_wal_roundtrip_preserves_data_and_never_activates(self):
        before = list(self.writer.iterdump())
        bundle = self.root / 'backup'
        manifest = snapshot(self.path, bundle, self.origin)
        self.assertEqual(list(self.writer.iterdump()), before)
        self.assertTrue(Path(str(self.path) + '-wal').exists())
        candidate = self.root / 'candidate.sqlite3'
        result = prepare_restore(bundle, candidate, self.origin)
        self.assertFalse(result['activated'])
        with closing(sqlite3.connect(candidate)) as con:
            self.assertEqual(list(con.iterdump()), before)
        # Existing repository accepts the prepared candidate without adoption or
        # migration; grants/jobs remain records, never execution authority.
        OfflineMarketingDocuments(str(candidate), self.repo.current_user, self.repo.load_org, project_origin=self.origin)
        self.assertEqual(manifest['tableRows']['growthrova_paid_jobs'], 1)
        report = json.dumps(diagnostics(candidate, self.origin))
        self.assertNotIn('customer wording', report)
        self.assertNotIn('"owner"', report)
        for file in (candidate, bundle / 'repository.sqlite3', bundle / 'manifest.json'):
            self.assertEqual(file.stat().st_mode & 0o777, 0o600)
        self.assertEqual(bundle.stat().st_mode & 0o777, 0o700)
        with self.assertRaises(ValueError):
            prepare_restore(bundle, candidate, self.origin)
        with self.assertRaises(ValueError):
            snapshot(self.path, bundle, self.origin)

    def test_identity_schema_and_incomplete_ownership_refuse(self):
        with self.assertRaises(ValueError):
            snapshot(self.path, self.root / 'wrong', 'https://another.example')
        self.assertFalse((self.root / 'wrong').exists())
        self.writer.execute('CREATE TABLE foreign_data(secret TEXT)')
        self.writer.commit()
        with self.assertRaises(ValueError):
            diagnostics(self.path, self.origin)
        with self.assertRaises(OfflineDocumentAccessError):
            OfflineMarketingDocuments(str(self.path), self.repo.current_user, self.repo.load_org, project_origin=self.origin)
        self.writer.execute('DROP TABLE foreign_data')
        self.writer.execute('DELETE FROM offline_document_owners')
        self.writer.commit()
        with self.assertRaises(ValueError):
            diagnostics(self.path, self.origin)

    def test_tampered_bundle_and_external_journal_refuse(self):
        bundle = self.root / 'backup'
        snapshot(self.path, bundle, self.origin)
        source = bundle / 'repository.sqlite3'
        wal = Path(str(source) + '-wal')
        wal.write_bytes(b'not included in checksum')
        with self.assertRaises(ValueError):
            prepare_restore(bundle, self.root / 'candidate', self.origin)
        wal.unlink()
        with source.open('ab') as stream:
            stream.write(b'tampered')
        with self.assertRaises(ValueError):
            prepare_restore(bundle, self.root / 'candidate', self.origin)
        self.assertFalse((self.root / 'candidate').exists())

    def test_private_paths_and_disk_guard(self):
        link = self.root / 'link'
        link.symlink_to(self.path)
        with self.assertRaises(ValueError):
            diagnostics(link, self.origin)
        os.chmod(self.path, 0o644)
        with self.assertRaises(ValueError):
            diagnostics(self.path, self.origin)
        os.chmod(self.path, 0o600)
        with patch('business_growthrova_recovery.shutil.disk_usage') as usage:
            usage.return_value.free = 12 * 1024 ** 3
            with self.assertRaises(ValueError):
                snapshot(self.path, self.root / 'no-space', self.origin)
        self.assertFalse((self.root / 'no-space').exists())


if __name__ == '__main__':
    unittest.main()
