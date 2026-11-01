#!/usr/bin/env python3
"""Verify limit snapshots using synthetic records only."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('quota_snapshot', Path(__file__).resolve().parents[1] / 'shell/adaptive-shell@local/quotaSnapshot.py')
quota = importlib.util.module_from_spec(spec)
spec.loader.exec_module(quota)


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    # ---- Claude: Claude Code's cached plan usage; nothing else from the file comes out
    def claude_config(self, cached):
        path = self.root / 'claude.json'
        path.write_text(json.dumps({'oauthAccount': {'emailAddress': 'someone@example.com'},
                                    'cachedUsageUtilization': cached}))
        return path

    def test_claude_windows(self):
        path = self.claude_config({'fetchedAtMs': 1791763200000, 'accountUuid': 'x', 'utilization': {
            'five_hour': {'utilization': 17, 'resets_at': '2026-10-12T06:29:59.95+00:00'},
            'seven_day': {'utilization': 31.5, 'resets_at': '2026-10-16T13:59:59+00:00'},
            'seven_day_opus': None}})
        data = quota.claude_snapshot(path, now=1791763260)
        self.assertEqual([(w['label'], w['used']) for w in data['windows']], [('5h', 17), ('Weekly', 31.5)])
        self.assertFalse(data['stale'])
        self.assertNotIn('example.com', json.dumps(data))
        self.assertNotIn('accountUuid', json.dumps(data))

    def test_claude_missing(self):
        self.assertTrue(quota.claude_snapshot(self.root / 'nope.json')['error'])
        self.assertEqual(quota.claude_snapshot(self.claude_config(None))['windows'], [])

    def test_claude_old_reading_is_stale(self):
        path = self.claude_config({'fetchedAtMs': 1791763200000, 'utilization': {
            'five_hour': {'utilization': 50, 'resets_at': '2026-10-12T06:29:59+00:00'}}})
        self.assertTrue(quota.claude_snapshot(path, now=1791763200 + 7200)['stale'])

    def test_claude_missing_5h_is_filled_from_office(self):
        path = self.claude_config({'fetchedAtMs': 1791763200000, 'utilization': {
            'seven_day': {'utilization': 31.5, 'resets_at': '2026-10-16T13:59:59+00:00'}}})
        office = {'ts': 1791763260, 'rows': [
            {'family': 'claude', 'window': '5h', 'percent': 75,
             'resets': '2026-10-12T06:29:59Z'},
            {'family': 'claude', 'window': 'week', 'percent': 10,
             'resets': '2026-10-16T20:18:26Z'}]}
        data = quota.claude_snapshot(path, now=1791763260, office=office)
        self.assertEqual([(w['label'], w['used']) for w in data['windows']],
                         [('5h', 25), ('Weekly', 31.5)])

    def test_claude_office_fills_all_windows_without_local_cache(self):
        office = {'ts': 1791763260, 'rows': [
            {'family': 'claude', 'window': '5h', 'remaining': '100%',
             'resets': '2026-10-12T06:29:59Z'}]}
        data = quota.claude_snapshot(self.root / 'nope.json', now=1791763260, office=office)
        self.assertEqual([(w['label'], w['used']) for w in data['windows']], [('5h', 0)])

    # ---- Gemini: agy's /usage as the Agent Office serves it (remaining -> used)
    def test_gemini_used(self):
        data = quota.gemini_snapshot({'ts': 1791763200, 'error': '', 'rows': [
            {'family': 'gemini', 'window': 'week', 'remaining': '15%', 'percent': 15,
             'resets': '2026-10-15T20:18:26Z'},
            {'family': 'gemini', 'window': '5h', 'remaining': '0%', 'percent': 0,
             'resets': '2026-10-12T02:43:41Z'},
            {'family': 'claude', 'window': 'week', 'remaining': '2%', 'percent': 2,
             'resets': '2026-10-16T20:18:26Z'},
            {'family': 'gemini', 'window': '5h', 'remaining': 'disabled', 'percent': None,
             'resets': ''}]}, now=1791763300)
        self.assertEqual([(w['label'], w['used']) for w in data['windows']], [('5h', 100), ('Weekly', 85)])

    def test_gemini_office_down_or_empty(self):
        self.assertIn('not running', quota.gemini_snapshot(None)['error'])
        self.assertTrue(quota.gemini_snapshot({'ts': 0, 'rows': []})['error'])


if __name__ == '__main__':
    unittest.main()
