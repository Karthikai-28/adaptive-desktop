#!/usr/bin/env python3
"""Read-only Link health: no pairing changes, provider calls or credentials."""
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'services/adaptive-link'))
import control
import ai_usage
try:
    status = control.status()
    print(json.dumps({'daemon': 'responding', 'paired': bool(status.get('phone')), 'cloud': status.get('cloud', 'unknown') }))
except control.NotRunning:
    print(json.dumps({'daemon': 'unreachable'}))
    sys.exit(1)
snapshot = ai_usage.snapshot()
print(json.dumps({'usage_reader_ok': snapshot.get('ok', False), 'providers': {
    name: {'windows': len(snapshot.get(name, {}).get('windows', [])),
           'current_windows': sum(not w.get('expired', False) for w in snapshot.get(name, {}).get('windows', [])),
           'stale': snapshot.get(name, {}).get('stale', True),
           'has_error': bool(snapshot.get(name, {}).get('error'))}
    for name in ai_usage.PROVIDERS}}))
