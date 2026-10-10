import json
from pathlib import Path
import tempfile
import unittest

from vision_rsi.input_provenance import manifest, audit, audit_manifest
from vision_rsi.media import package_sample
from vision_rsi.runner import digest


class InputProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.contract = {'inputs': {'photo': {'type': 'image', 'required': True}}}

    def sample(self, name, content, sample_id):
        (self.root / name).write_bytes(content)
        sample = {'sample_id': sample_id, 'inputs': {'photo': {'type': 'image', 'uri': name}}}
        return {'sample': sample, 'media': package_sample(self.contract, sample, self.root)}

    def save(self, name, rows):
        record = {'status': 'development_execution_completed', 'binding': {'bundle_id': 'a'*64},
                  'input_manifest': rows, 'outputs': [{} for _ in rows]}
        record['record_sha256'] = digest(record)
        path = self.root / name; path.write_text(json.dumps(record))
        return path

    def test_renamed_media_and_ids_still_overlap(self):
        a = manifest(self.contract, [self.sample('old.ppm', b'pixels', 'old')])
        b = manifest(self.contract, [self.sample('new.ppm', b'pixels', 'new')])
        result = audit([self.save('a.json', a)], self.save('b.json', b))
        self.assertEqual(result['status'], 'overlap_detected')
        self.assertEqual(result['overlaps']['sample_ids'], [])
        self.assertEqual(len(result['overlaps']['media_sha256']), 1)
        self.assertEqual(len(result['overlaps']['input_content_sha256']), 1)

    def test_distinct_content_does_not_approve_quality(self):
        a = manifest(self.contract, [self.sample('a', b'one', 'a')])
        b = manifest(self.contract, [self.sample('b', b'two', 'b')])
        result = audit([self.save('a.json', a)], self.save('b.json', b))
        self.assertEqual(result['status'], 'no_overlap_in_supplied_records')
        self.assertFalse(result['quality_verified'])
        self.assertFalse(result['complete_development_history_verified'])

    def test_legacy_uri_only_and_tampering_refused(self):
        case = self.sample('a', b'one', 'a')
        rows = manifest(self.contract, [case]); good = self.save('good.json', rows)
        uri_only = manifest(self.contract, [{'sample': case['sample']}])
        with self.assertRaisesRegex(ValueError, 'coverage'):
            audit([good], self.save('uri.json', uri_only))
        legacy = json.loads(good.read_text()); del legacy['input_manifest']; del legacy['record_sha256']
        legacy['record_sha256'] = digest(legacy)
        path = self.root / 'legacy.json'; path.write_text(json.dumps(legacy))
        with self.assertRaisesRegex(ValueError, 'provenance'): audit([good], path)
        changed = json.loads(good.read_text()); changed['input_manifest'][0]['sample_id'] = 'modified'
        path.write_text(json.dumps(changed))
        with self.assertRaisesRegex(ValueError, 'integrity'): audit([good], path)

    def test_text_content_and_joint_asset_overlap(self):
        contract = {'inputs': {'text': {'type': 'text', 'required': True}}}
        case = {'sample': {'sample_id': 'one', 'inputs': {'text': {'type': 'text', 'value': 'hello'}}}}
        a = manifest(contract, [case]); case['sample']['sample_id'] = 'two'
        b = manifest(contract, [case])
        self.assertEqual(a[0]['input_content_sha256'], b[0]['input_content_sha256'])
        self.assertTrue(a[0]['media_coverage_complete'])
        # A joint input can overlap one raw asset even when whole-input hashes differ.
        b[0]['input_content_sha256'] = 'b'*64
        a[0]['media_sha256'] = b[0]['media_sha256'] = ['c'*64]
        result = audit([self.save('a.json', a)], self.save('b.json', b))
        self.assertEqual(result['status'], 'overlap_detected')
        self.assertEqual(result['overlaps']['input_content_sha256'], [])

    def test_preflight_checks_other_candidates_on_same_contract(self):
        rows = manifest(self.contract, [self.sample('a', b'one', 'a')])
        path = self.save('development.json', rows)
        record = json.loads(path.read_text()); record['binding']['contract_sha256'] = 'c'*64
        del record['record_sha256']; record['record_sha256'] = digest(record)
        path.write_text(json.dumps(record))
        result = audit_manifest([path], 'b'*64, 'c'*64, rows)
        self.assertEqual(result['status'], 'overlap_detected')
        with self.assertRaisesRegex(ValueError, 'same task contract'):
            audit_manifest([path], 'b'*64, 'd'*64, rows)
