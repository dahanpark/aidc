"""Startup avoids repeated full reads without weakening write validation."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from backend.server import AtlasApplication
from backend.repository import JsonRepository
from backend import pipeline

ROOT = Path(__file__).resolve().parents[1]


class StartupTests(unittest.TestCase):
    def test_existing_application_initializes_with_one_full_checksum_read(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = JsonRepository(temp)
            pipeline.bootstrap(repo, ROOT)
            aid = next(iter(repo.snapshot()['datasets']['articles']))
            repo.transact(lambda ds: ds.setdefault('bookmarks', {}).update({aid: {
                'id': aid, 'article_id': aid, 'note': 'preserve startup bookmark'}}))
            # First migration writes a new generation, which is also verified.
            prepared = AtlasApplication(ROOT, temp)
            prepared.stop.set()
            original = JsonRepository._read
            with patch.object(JsonRepository, '_read', autospec=True, side_effect=original) as reads:
                app = AtlasApplication(ROOT, temp)
                self.assertEqual(reads.call_count, 1)
                data = app.view_snapshot()['datasets']
                self.assertEqual(data['bookmarks'][aid]['note'], 'preserve startup bookmark')
                self.assertEqual(reads.call_count, 1)
                self.assertIsNone(app.repo.initial_snapshot)
                app.stop.set()
            # A subsequent ordinary transaction still performs a strict read.
            with patch.object(JsonRepository, '_read', autospec=True, side_effect=original) as reads:
                app.repo.transact(lambda ds: None)
                self.assertEqual(reads.call_count, 1)
