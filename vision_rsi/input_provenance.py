"""Content overlap audit for supplied execution records, not quality approval."""
import hashlib
import re

from .runner import digest
from .event_eval import read_document


def manifest(contract, cases):
    rows = []
    for case in cases:
        sample = case['sample']
        from .contracts import validate_sample
        validate_sample(contract, sample)
        packet = case.get('media')
        if packet is not None:
            from .media import verify_sample_request
            verify_sample_request(contract, packet)
            if packet['sample'] != sample:
                raise ValueError('Media sample differs')
        fields = {}; media = []; complete = True
        for name, value in sample['inputs'].items():
            kind = value['type']
            if kind == 'text':
                fields[name] = {'type': kind, 'sha256': hashlib.sha256(value['value'].encode()).hexdigest()}
                continue
            assets = [a['sha256'] for a in packet['assets'] if a['field'] == name] if packet else []
            if not assets:
                complete = False
            fields[name] = {'type': kind, 'assets': assets}
            if kind == 'video':
                fields[name]['processing'] = contract['inputs'][name]['processing']
            media.extend(assets)
        rows.append({'sample_id': sample['sample_id'], 'input_content_sha256': digest(fields),
                     'media_sha256': media, 'media_coverage_complete': complete})
    return rows


def _read(path):
    _, record = read_document(path, 8 * 1024 * 1024)
    if not isinstance(record, dict) or record.get('record_sha256') != digest({k: v for k, v in record.items() if k != 'record_sha256'}):
        raise ValueError('Execution record integrity differs')
    if record.get('status') != 'development_execution_completed' or not isinstance(record.get('binding'), dict):
        raise ValueError('Require completed, bound execution')
    rows = record.get('input_manifest')
    outputs = record.get('outputs')
    if not isinstance(rows, list) or not 1 <= len(rows) <= 16 or not isinstance(outputs, list) or len(rows) != len(outputs):
        raise ValueError('Missing or incomplete input provenance; legacy records do not prove separation')
    for row in rows:
        if not isinstance(row, dict) or row.get('media_coverage_complete') is not True:
            raise ValueError('Actual media content coverage required')
        if not isinstance(row.get('sample_id'), str) or not row['sample_id']:
            raise ValueError('Invalid sample identity')
        hashes = row.get('media_sha256')
        if not isinstance(hashes, list) or any(not isinstance(h, str) or not re.fullmatch('[0-9a-f]{64}', h) for h in hashes + [row.get('input_content_sha256')]):
            raise ValueError('Invalid content fingerprint')
    return record, rows


def audit(development_paths, acceptance_path):
    if not development_paths or len(development_paths) > 128:
        raise ValueError('Require 1..128 development execution records')
    acceptance, heldout = _read(acceptance_path)
    records = [_read(path) for path in development_paths]
    if any(record['binding'].get('bundle_id') != acceptance['binding'].get('bundle_id') for record, _ in records):
        raise ValueError('Audit requires the same frozen bundle')
    if not isinstance(acceptance['binding'].get('bundle_id'), str) or not re.fullmatch('[0-9a-f]{64}', acceptance['binding']['bundle_id']):
        raise ValueError('Missing frozen bundle identity')
    development = [row for _, rows in records for row in rows]
    ids = {r['sample_id'] for r in development}
    contents = {r['input_content_sha256'] for r in development}
    media = {h for r in development for h in r['media_sha256']}
    overlaps = {'sample_ids': sorted(ids & {r['sample_id'] for r in heldout}),
                'input_content_sha256': sorted(contents & {r['input_content_sha256'] for r in heldout}),
                'media_sha256': sorted(media & {h for r in heldout for h in r['media_sha256']})}
    return {'status': 'overlap_detected' if any(overlaps.values()) else 'no_overlap_in_supplied_records',
            'overlaps': overlaps, 'development_records': len(records),
            'record_sha256': [r['record_sha256'] for r, _ in records] + [acceptance['record_sha256']],
            'scope': 'supplied_records_only', 'complete_development_history_verified': False,
            'quality_verified': False, 'production_accepted': False}


def main(argv=None):
    import argparse
    import json
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--development', action='append', required=True, help='Execution JSON; repeat for each record')
    parser.add_argument('--acceptance', required=True, help='Proposed held-out execution JSON')
    args = parser.parse_args(argv)
    try:
        print(json.dumps(audit(args.development, args.acceptance), ensure_ascii=False, indent=2))
    except (ValueError, TypeError, KeyError, OSError) as error:
        parser.exit(1, str(error) + '\n')
