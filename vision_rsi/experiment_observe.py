"""Read-only inspection of a persisted planner request, including uncertain calls."""
import argparse
from contextlib import closing
import json
from pathlib import Path
import re
import sqlite3

from .runner import digest


def inspect_request(store, request_id, include_messages=False):
    if not isinstance(request_id, str) or not re.fullmatch('[A-Za-z0-9_-]{1,100}', request_id):
        raise ValueError('Invalid experiment request ID')
    database = (Path(store) / 'requests.sqlite3').resolve()
    if not database.is_file():
        raise ValueError('Experiment request ledger does not exist')
    with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True, timeout=10)) as db:
        row = db.execute('SELECT context,state,response FROM requests WHERE id=?', (request_id,)).fetchone()
    if row is None:
        raise ValueError('Unknown experiment request ID')
    context, state, raw_response = json.loads(row[0]), row[1], row[2]
    if not isinstance(context, dict) or state not in ('reserved', 'responded', 'not_dispatched'):
        raise ValueError('Invalid experiment request record')
    snapshot = context.get('request_snapshot')
    verified = False
    if 'request_snapshot' in context:
        if not isinstance(snapshot, dict) or digest(snapshot) != context.get('request_snapshot_sha256'):
            raise ValueError('Experiment request snapshot changed')
        verified = True
    response = json.loads(raw_response) if raw_response is not None else None
    if (state == 'responded') != (response is not None):
        raise ValueError('Experiment response/state mismatch')
    report = {'request_id': request_id, 'state': state, 'run_id': context.get('run_id'),
              'parent_plan_id': context.get('parent_plan_id'),
              'receipt_sha256': context.get('receipt_sha256'),
              'snapshot_available': snapshot is not None, 'snapshot_hash_verified': verified,
              'request_snapshot_sha256': context.get('request_snapshot_sha256'),
              'remaining_gpu_hours_snapshot': snapshot.get('remaining_gpu_hours_snapshot') if verified else None,
              'max_tokens': snapshot.get('max_tokens') if verified else None,
              'response_sha256': digest(response) if response is not None else None,
              'response_available': response is not None,
              'automatic_retry_allowed': False, 'read_only': True,
              'llm_called': False, 'remote_called': False, 'quality_verified': False,
              'scope': 'Local planner ledger inspection; hashes are not external authenticity or billing proof.'}
    if include_messages:
        report['request_snapshot'] = snapshot
        report['response'] = response
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(prog='vision-rsi experiment-request')
    parser.add_argument('--store', required=True, help='Campaign experiments directory containing requests.sqlite3')
    parser.add_argument('--request-id', required=True)
    parser.add_argument('--messages', action='store_true', help='Include saved planner messages and response')
    args = parser.parse_args(argv)
    try:
        print(json.dumps(inspect_request(args.store, args.request_id, args.messages), ensure_ascii=False, indent=2))
    except (ValueError, OSError, sqlite3.Error) as error:
        parser.exit(1, type(error).__name__ + ': ' + str(error) + '\n')
