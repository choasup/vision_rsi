import base64
import copy
import hashlib
import unittest

from vision_rsi.video_runtime import compile_plan,validate_plan,timestamps,validate_result


class VideoRuntimeTests(unittest.TestCase):
    def test_candidate_decode_cache_preserves_frames_and_never_retries_unknown(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from vision_rsi.candidate_bundle import decoded_video
        import vision_rsi.video_runtime as runtime
        driver=hashlib.sha256(Path(runtime.__file__).read_bytes()).hexdigest()
        raw=b'P6\n1 1\n255\n\x01\x02\x03'
        frame={'index':0,'width':1,'height':1,'pts':0,'time_base':{'numerator':1,'denominator':4},'seconds':0,
               'format':'ppm_rgb24','sha256':hashlib.sha256(raw).hexdigest(),'content_base64':base64.b64encode(raw).decode()}
        asset={'sha256':'1'*64,'content_base64':'ZmFrZQ=='}
        result={'status':'video_decoded','input_sha256':asset['sha256'],'plan':self.plan,'frames':[frame],
                'decoded_bytes':len(raw),'duration_seconds':1,'inference_performed':False,'audio_processed':False,'driver_sha256':driver}
        with tempfile.TemporaryDirectory() as folder,patch('vision_rsi.remote.decode_video',return_value=result) as decoder:
            self.assertEqual(decoded_video(asset,self.plan,{},folder,driver),result)
            self.assertEqual(decoded_video(asset,self.plan,{},folder,driver),result)
            self.assertEqual(decoder.call_count,1)
            with self.assertRaisesRegex(ValueError,'driver changed'):decoded_video(asset,self.plan,{},folder,'0'*64)
            decoder.side_effect=RuntimeError('unknown outcome')
            changed=dict(asset,sha256='2'*64)
            with self.assertRaisesRegex(RuntimeError,'unknown'):decoded_video(changed,self.plan,{},folder,driver)
            with self.assertRaisesRegex(RuntimeError,'Uncertain video'):decoded_video(changed,self.plan,{},folder,driver)
            self.assertEqual(decoder.call_count,2)

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

    def test_natural_chinese_sampling_compiles_without_rewriting_contract(self):
        for sampling in ('每秒3帧','每秒 3 帧','3fps','3 FPS',' 3 fps '):
            processing={'sampling':sampling,'temporal':'保留原始时间戳和帧顺序','audio':'ignore'}
            original=copy.deepcopy(processing)
            result=compile_plan(processing)
            self.assertEqual(result['status'],'ready');self.assertEqual(result['plan']['fps'],3)
            self.assertEqual(processing,original)
        fractional=compile_plan({'sampling':'每秒0.5帧','temporal':'保留时间戳和顺序','audio':'ignore'})
        self.assertEqual(fractional['plan']['fps'],.5)

    def test_ambiguous_or_malformed_sampling_remains_blocked(self):
        base={'sampling':'每秒3帧','temporal':'保留原始时间戳和帧顺序','audio':'ignore'}
        for sampling in (None,True,[],{},3,'每2秒3帧','3 frames maybe','每秒零帧','每秒0帧','每秒31帧','每秒3帧或5帧'):
            self.assertEqual(compile_plan(dict(base,sampling=sampling))['status'],'blocked')
        for change in ({'audio':'保留音频'},{'temporal':'打乱顺序'},{'decoder':dict(self.plan,fps=2)}):
            self.assertEqual(compile_plan(dict(base,**change))['status'],'blocked')

    def test_time_grid_accepts_source_frames_without_minimum_interval_drift(self):
        plan=dict(self.plan,protocol='source_time_grid_v2',fps=3,max_frames=8)
        raw=b'P6\n1 1\n255\n'+b'\x01\x02\x03'
        frame={'width':1,'height':1,'time_base':{'numerator':1,'denominator':4},'format':'ppm_rgb24','sha256':hashlib.sha256(raw).hexdigest(),'content_base64':base64.b64encode(raw).decode()}
        frames=[dict(frame,index=i,pts=pts,seconds=pts/4) for i,pts in enumerate((0,2,3,4))]
        request={'plan':plan,'sha256':'1'*64}
        result={'status':'video_decoded','input_sha256':'1'*64,'plan':plan,'frames':frames,'decoded_bytes':len(raw)*4,'duration_seconds':1.5,'inference_performed':False,'audio_processed':False}
        self.assertTrue(validate_result(request,result))
        changed=copy.deepcopy(result);changed['frames'][1].update(pts=1,seconds=.25)
        with self.assertRaisesRegex(ValueError,'slot repeated'):validate_result(request,changed)
        changed=copy.deepcopy(result);changed['frames'][2].update(pts=2,seconds=.5)
        with self.assertRaisesRegex(ValueError,'order'):validate_result(request,changed)
        legacy=dict(plan,protocol='source_first_min_interval_v1')
        with self.assertRaisesRegex(ValueError,'interval'):validate_result(dict(request,plan=legacy),dict(result,plan=legacy))
        compiled=compile_plan({'sampling':'3 fps','temporal':'ordered','audio':'ignore'})
        self.assertEqual(compiled['plan']['protocol'],'source_time_grid_v2')
