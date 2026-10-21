"""How much of each AI plan's usage limits is used, from records already on this machine.

Never opens account credentials and never calls a remote API. Each provider comes out in one shape:

  {"ts": <when the provider recorded it>, "stale": bool, "error": "",
   "windows": [{"label": "5h" | "Weekly" | ..., "used": 0-100, "resetsAt": <unix>, "expired": bool}]}

  codex   the rate_limits Codex writes into its session rollouts (~/.codex/sessions)
  claude  Claude Code's cached usage, completed with Claude + GPT rows from Agent Office
  gemini  agy's /usage, as the Agent Office serves it on its loopback port

A window whose reset time has passed is marked expired: the record says nothing about it since, so
the display says so instead of guessing it refilled.
"""
import datetime as dt
import json
import math
import re
from pathlib import Path
import sys
import time
import urllib.request

OFFICE_USAGE = 'http://127.0.0.1:8790/api/usage'
STALE_S = {'codex': 900, 'claude': 3600, 'gemini': 900}


def _empty(error=''):
    return {'ts': 0, 'stale': True, 'error': error, 'windows': []}


def _num(v):
    return isinstance(v, (float, int)) and not isinstance(v, bool) and math.isfinite(v)


def _window(label, used, reset, now):
    if not _num(used) or not _num(reset) or not 0 <= used <= 100:
        return None
    return {'label': label, 'used': round(float(used), 1), 'resetsAt': reset, 'expired': reset <= now}


def _iso(s):
    text = str(s).replace('Z', '+00:00')
    # Python 3.10 only parses 3 or 6 fractional digits; providers send any number
    text = re.sub(r'\.(\d+)', lambda m: '.' + (m.group(1) + '000000')[:6], text, count=1)
    try:
        return dt.datetime.fromisoformat(text).timestamp()
    except ValueError:
        return None


def codex_snapshot(root, now=None, source_out=None):
    now = time.time() if now is None else now
    latest = None
    # Bounded tails keep polling cheap and avoid loading conversation histories.
    try:
        files = sorted(root.glob('**/rollout-*.jsonl'), key=lambda p: p.stat().st_mtime, reverse=True)[:20]
    except OSError:
        files = []
    for path in files:
        try:
            with path.open('rb') as stream:
                stream.seek(max(0, path.stat().st_size - 524288))
                lines = stream.read().splitlines()
            for line in reversed(lines):
                if b'"rate_limits"' not in line:
                    continue
                try:
                    record = json.loads(line)
                    payload = record.get('payload', {})
                    limits = payload.get('rate_limits')
                    if payload.get('type') != 'token_count' or not isinstance(limits, dict):
                        continue
                    if limits.get('limit_id') not in (None, 'codex'):
                        continue
                    stamp = _iso(record['timestamp'])
                    if stamp is not None and (latest is None or stamp > latest[0]):
                        latest = (stamp, limits, path)
                    break
                except (ValueError, KeyError, TypeError, AttributeError):
                    continue
        except OSError:
            continue
    if latest is None:
        return _empty('No Codex session has recorded its limits yet')
    stamp, limits, source = latest
    if source_out is not None:
        source_out.append(source)
    result = {'ts': stamp, 'stale': now - stamp > STALE_S['codex'], 'error': '', 'windows': []}
    for key in ('primary', 'secondary'):
        window = limits.get(key)
        if not isinstance(window, dict):
            continue
        minutes = window.get('window_minutes')
        if not _num(minutes) or minutes <= 0:
            continue
        name = 'Weekly' if minutes == 10080 else f'{minutes / 60:g}h'
        w = _window(name, window.get('used_percent'), window.get('resets_at'), now)
        if w:
            result['windows'].append(w)
    return result


CLAUDE_WINDOWS = (('five_hour', '5h'), ('seven_day', 'Weekly'),
                  ('seven_day_opus', 'Weekly Opus'), ('seven_day_sonnet', 'Weekly Sonnet'))


def _office_family_snapshot(data, family, stale_key, now, unavailable):
    if not isinstance(data, dict) or not isinstance(data.get('rows'), list):
        return _empty(unavailable)
    stamp = data.get('ts') if _num(data.get('ts')) else 0
    result = {'ts': stamp, 'stale': not stamp or now - stamp > STALE_S[stale_key],
              'error': '', 'windows': []}
    for row in data['rows']:
        if row.get('family', 'gemini') != family:
            continue
        try:
            left = row.get('percent')
            if not _num(left):
                left = float(str(row.get('remaining', '')).rstrip('%'))
        except (ValueError, AttributeError):
            continue
        label = 'Weekly' if row.get('window') == 'week' else str(row.get('window', ''))
        w = _window(label, 100 - left, _iso(row.get('resets')), now)
        if w:
            result['windows'].append(w)
    result['windows'].sort(key=lambda w: w['label'].startswith('Weekly'))
    if not result['windows']:
        result['error'] = 'Waiting for the first usage report'
    return result


def _merge_windows(primary, fallback):
    """Keep provider-specific rows, filling missing windows from the shared usage source."""
    if not fallback['windows']:
        return primary
    if not primary['windows']:
        return fallback
    windows = {w['label']: w for w in fallback['windows']}
    windows.update({w['label']: w for w in primary['windows']})
    stamps = [p['ts'] for p in (primary, fallback) if p['ts']]
    return {'ts': min(stamps) if stamps else 0,
            'stale': primary['stale'] or fallback['stale'],
            'error': '',
            'windows': sorted(windows.values(), key=lambda w: w['label'].startswith('Weekly'))}


def claude_snapshot(config, now=None, office=None):
    """Read only cachedUsageUtilization, then fill absent windows from Agent Office."""
    now = time.time() if now is None else now
    try:
        cached = json.loads(config.read_text()).get('cachedUsageUtilization')
    except (OSError, ValueError, AttributeError):
        local = _empty('Claude Code settings not found')
        return _merge_windows(local, _office_family_snapshot(
            office, 'claude-gpt', 'claude', now, 'The Agent Office is not running'))
    if not isinstance(cached, dict) or not isinstance(cached.get('utilization'), dict):
        local = _empty('Claude Code has not fetched plan usage yet')
        return _merge_windows(local, _office_family_snapshot(
            office, 'claude-gpt', 'claude', now, 'The Agent Office is not running'))
    stamp = cached.get('fetchedAtMs')
    stamp = stamp / 1000 if _num(stamp) else 0
    result = {'ts': stamp, 'stale': now - stamp > STALE_S['claude'], 'error': '', 'windows': []}
    for key, label in CLAUDE_WINDOWS:
        window = cached['utilization'].get(key)
        if isinstance(window, dict):
            w = _window(label, window.get('utilization'), _iso(window.get('resets_at')), now)
            if w:
                result['windows'].append(w)
    office_result = _office_family_snapshot(
        office, 'claude-gpt', 'claude', now, 'The Agent Office is not running')
    return _merge_windows(result, office_result)


def gemini_snapshot(data, now=None):
    now = time.time() if now is None else now
    return _office_family_snapshot(
        data, 'gemini', 'gemini', now, 'The Agent Office is not running')


def snapshot(refresh=False):
    try:
        # Bypass proxy settings: this is strictly a loopback service.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        request = urllib.request.Request(OFFICE_USAGE + ('/refresh' if refresh else ''),
                                         method='POST' if refresh else 'GET',
                                         headers={'X-Office': '1'} if refresh else {})
        with opener.open(request, timeout=65 if refresh else 3) as response:
            office = json.loads(response.read(65536))
    except (OSError, ValueError):
        office = None
    home = Path.home()
    codex_sources = []
    codex = codex_snapshot(home / '.codex' / 'sessions', source_out=codex_sources)
    claude_config = home / '.claude.json'
    watch = {'claude': str(claude_config)}
    if codex_sources:
        watch['codex'] = str(codex_sources[0])
        # A newly started Codex session creates a sibling rollout. Watching the
        # directory lets the shell discover it without waiting for a timer.
        watch['codexDirectory'] = str(codex_sources[0].parent)
    return {'codex': codex,
            'claude': claude_snapshot(claude_config, office=office),
            'gemini': gemini_snapshot(office),
            '_watch': watch}


if __name__ == '__main__':
    print(json.dumps(snapshot('--refresh' in sys.argv[1:])))
