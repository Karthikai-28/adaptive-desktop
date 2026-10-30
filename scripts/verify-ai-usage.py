#!/usr/bin/env python3
"""Provider projection and concurrent first requests, using only disposable usage fixtures."""
import concurrent.futures
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'services/adaptive-link'))
import ai_usage

class UsageChecks(unittest.TestCase):
    def test_concurrent_first_requests(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'reader.py'
            source.write_text('import time\ntime.sleep(.1)\ndef snapshot():\n return {"codex":{"windows":[{"label":"5h","used":25}]}}\n')
            with patch.object(ai_usage, 'SNAPSHOT', source), patch.object(ai_usage, '_reader', None):
                with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
                    results = list(pool.map(lambda _: ai_usage.snapshot(), range(16)))
                self.assertTrue(all(r['ok'] for r in results))
                self.assertTrue(all(r['codex']['windows'][0]['used'] == 25 for r in results))
    def test_failed_import_can_be_retried(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'reader.py'
            source.write_text('raise RuntimeError("temporarily unavailable")\n')
            with patch.object(ai_usage, 'SNAPSHOT', source), patch.object(ai_usage, '_reader', None):
                self.assertFalse(ai_usage.snapshot()['ok'])
                source.write_text('def snapshot():\n return {}\n')
                self.assertTrue(ai_usage.snapshot()['ok'])
    def test_projection_never_exposes_paths_or_bad_numbers(self):
        data = ai_usage.clean_snapshot({'_watch': {'path': '/private'}, 'codex': {'windows': [
            {'label': '5h', 'used': float('nan')}, {'label': 'Weekly', 'used': 140, 'resetsAt': float('inf')}]}})
        self.assertNotIn('_watch', data)
        self.assertEqual(data['codex']['windows'], [{'label': 'Weekly', 'used': 100, 'resetsAt': 0, 'expired': False}])

if __name__ == '__main__': unittest.main()
