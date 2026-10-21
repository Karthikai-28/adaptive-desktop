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

    def record(self, name='one', stamp='2026-10-12T00:00:00Z', used=25, limit='codex'):
        data = {'timestamp': stamp, 'payload': {'type': 'token_count', 'rate_limits': {
            'limit_id': limit, 'primary': {'used_percent': used, 'window_minutes': 300, 'resets_at': 2000000000},
            'secondary': {'used_percent': 40, 'window_minutes': 10080, 'resets_at': 2100000000}}}}
        (self.root / f'rollout-{name}.jsonl').write_text(json.dumps(data) + '\n{"unfinished"')

    def test_missing(self):
        self.assertEqual(quota.codex_snapshot(self.root)['windows'], [])

    def test_windows_and_partial_line(self):
        self.record()
        sources = []
        data = quota.codex_snapshot(self.root, now=1791763200, source_out=sources)
        self.assertEqual([w['used'] for w in data['windows']], [25, 40])
        self.assertEqual([w['label'] for w in data['windows']], ['5h', 'Weekly'])
        self.assertFalse(data['stale'])
        self.assertEqual(sources, [self.root / 'rollout-one.jsonl'])

    def test_stale_and_expired_do_not_assume_refill(self):
        self.record(used=100)
        data = quota.codex_snapshot(self.root, now=2050000000)
        self.assertTrue(data['stale'])
        self.assertTrue(data['windows'][0]['expired'])
        self.assertEqual(data['windows'][0]['used'], 100)
        self.assertFalse(data['windows'][1]['expired'])

    def test_newest_timestamp_not_file_order(self):
        self.record('newer', '2026-10-12T01:00:00Z', 80)
        self.record('older', used=20)
        self.assertEqual(quota.codex_snapshot(self.root)['windows'][0]['used'], 80)

    def test_separate_limit_bucket(self):
        self.record(limit='other-product')
        self.assertEqual(quota.codex_snapshot(self.root)['windows'], [])

    def test_invalid_percentage(self):
        self.record(used=-1)
        self.assertEqual(len(quota.codex_snapshot(self.root)['windows']), 1)

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

    # ---- Gemini: agy's /usage as the Agent Office serves it (remaining -> used)
    def test_gemini_used(self):
        data = quota.gemini_snapshot({'ts': 1791763200, 'error': '', 'rows': [
            {'family': 'gemini', 'window': 'week', 'remaining': '15%', 'percent': 15,
             'resets': '2026-10-15T20:18:26Z'},
            {'family': 'gemini', 'window': '5h', 'remaining': '0%', 'percent': 0,
             'resets': '2026-10-12T02:43:41Z'},
            {'family': 'claude-gpt', 'window': 'week', 'remaining': '2%', 'percent': 2,
             'resets': '2026-10-16T20:18:26Z'},
            {'family': 'gemini', 'window': '5h', 'remaining': 'disabled', 'percent': None,
             'resets': ''}]}, now=1791763300)
        self.assertEqual([(w['label'], w['used']) for w in data['windows']], [('5h', 100), ('Weekly', 85)])

    def test_gemini_office_down_or_empty(self):
        self.assertIn('not running', quota.gemini_snapshot(None)['error'])
        self.assertTrue(quota.gemini_snapshot({'ts': 0, 'rows': []})['error'])


if __name__ == '__main__':
    unittest.main()
