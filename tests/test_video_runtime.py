import base64
import copy
import hashlib
import unittest

from vision_rsi.video_runtime import compile_plan,validate_plan,timestamps,validate_result


class VideoRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.plan={'protocol':'source_first_min_interval_v1','fps':2,'max_frames':4,'max_width':64,'max_height':48,'max_duration_seconds':2,'audio':'ignore'}

    def test_training_compilation_preserves_sampling_and_blocks_unsupported_semantics(self):
        processing={'sampling':'2 fps','temporal':'preserve timestamps and order','audio':'ignore'}
        compiled=compile_plan(processing)
        self.assertEqual(compiled['status'],'ready');self.assertEqual(compiled['plan']['fps'],2)
        self.assertNotIn('decoder',processing)
        processing['decoder']=dict(self.plan)
        copied=compile_plan(processing)
        processing['decoder']['max_frames']=1
        self.assertEqual(copied['plan']['max_frames'],4)
        processing.pop('decoder')
        for changed in ({'sampling':'key events only'},{'audio':'transcribe'},{'temporal':'unordered'},{'decoder':dict(self.plan,fps=1)}):
            self.assertEqual(compile_plan(dict(processing,**changed))['status'],'blocked')
        for changed in ({'fps':True},{'fps':float('nan')},{'max_frames':4.0},{'max_width':4096,'max_height':4096}):
            with self.assertRaises(ValueError):validate_plan(dict(self.plan,**changed))

    def test_exact_source_pts_and_missing_or_reversed_timestamps(self):
        log='[Parsed_showinfo_1 @ x] config in time_base: 1/10240, frame_rate: 4/1\n'
        log+='[Parsed_showinfo_1 @ x] n: 0 pts: 10240 pts_time:1\n'
        log+='[Parsed_showinfo_1 @ x] n: 1 pts: 15360 pts_time:1.5\n'
        rows=timestamps(log,2)
        self.assertEqual([r['seconds'] for r in rows],[1,1.5])
        self.assertEqual(rows[1]['pts'],15360)
        for malformed,count in ((log,3),(log.replace('15360','10240'),2),(log.replace('1/10240','0/10240'),2)):
            with self.assertRaises(ValueError):timestamps(malformed,count)

    def test_returned_frame_bytes_timing_and_identity_are_independently_checked(self):
        raw=b'P6\n1 1\n255\n'+b'\x01\x02\x03'
        frame={'index':0,'width':1,'height':1,'pts':0,'time_base':{'numerator':1,'denominator':4},'seconds':0,
               'format':'ppm_rgb24','sha256':hashlib.sha256(raw).hexdigest(),'content_base64':base64.b64encode(raw).decode()}
        request={'plan':self.plan,'sha256':'1'*64}
        result={'status':'video_decoded','input_sha256':'1'*64,'plan':self.plan,'frames':[frame],
                'decoded_bytes':len(raw),'duration_seconds':1,'inference_performed':False,'audio_processed':False}
        self.assertTrue(validate_result(request,result))
        for mutate in (lambda r:r.update(input_sha256='0'*64),lambda r:r.update(inference_performed=True),
                       lambda r:r['frames'][0].update(sha256='0'*64),lambda r:r['frames'][0].update(seconds=1),
                       lambda r:r['frames'][0].update(width=2),lambda r:r.update(decoded_bytes=0)):
            changed=copy.deepcopy(result);mutate(changed)
            with self.assertRaises(ValueError):validate_result(request,changed)
        changed=copy.deepcopy(result);changed['frames'].append(dict(frame,index=1,pts=1,seconds=.25))
        changed['decoded_bytes']*=2
        with self.assertRaisesRegex(ValueError,'interval'):validate_result(request,changed)
        for duration in (None,True,0,-1,float('nan'),float('inf'),3):
            with self.subTest(duration=duration),self.assertRaisesRegex(ValueError,'duration'):
                validate_result(request,dict(result,duration_seconds=duration))
        changed=copy.deepcopy(result);changed['frames'].append(dict(frame,index=1,pts=2,seconds=.5));changed['decoded_bytes']*=2
        self.assertTrue(validate_result(request,changed))
        with self.assertRaisesRegex(ValueError,'span'):validate_result(request,dict(changed,duration_seconds=.1))
        offset=copy.deepcopy(changed)
        for row in offset['frames']:
            row['pts']+=10**30;row['seconds']=float(row['pts']/4)
        # Rounded float seconds collapse at this offset; exact PTS still span .5s.
        with self.assertRaisesRegex(ValueError,'span'):validate_result(request,dict(offset,duration_seconds=.1))
        other=b'P6\n2 1\n255\n'+b'\x01\x02\x03'*2
        changed['frames'][1].update(width=2,sha256=hashlib.sha256(other).hexdigest(),content_base64=base64.b64encode(other).decode())
        changed['decoded_bytes']=len(raw)+len(other)
        with self.assertRaisesRegex(ValueError,'dimensions changed'):validate_result(request,changed)
