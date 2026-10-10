"""Bounded remote CPU video decoding; no model or quality claim.

The controller owns this driver. FFmpeg only sees one input and a private
output directory inside a no-network namespace, never sender URI paths.
"""
import base64
from fractions import Fraction
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import signal
import subprocess
import tempfile


def validate_plan(plan):
    fields={'protocol','fps','max_frames','max_width','max_height','max_duration_seconds','audio'}
    if not isinstance(plan,dict) or set(plan)!=fields or plan['protocol']!='source_first_min_interval_v1' or plan['audio']!='ignore':
        raise ValueError('Explicit source-frame sampling plan with audio=ignore required')
    for name,upper in [('fps',30),('max_frames',128),('max_width',4096),('max_height',4096),('max_duration_seconds',300)]:
        value=plan[name]
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not 0<value<=upper:
            raise ValueError('Invalid video plan '+name)
        if name in ('max_frames','max_width','max_height') and not isinstance(value,int):raise ValueError('Video dimensions/frame limit must be integers')
    if plan['max_frames']*plan['max_width']*plan['max_height']*3>64*1024*1024:
        raise ValueError('Video plan decoded RGB budget exceeds 64 MiB')
    return dict(plan)


def compile_plan(processing):
    """Compile supported task semantics during harness build, never at Test."""
    if not isinstance(processing,dict):return {'status':'blocked','reason':'Video processing must be an object'}
    sampling=processing.get('sampling','')
    match=re.fullmatch(r'([0-9]+(?:\.[0-9]+)?)\s+fps',sampling)
    if not match or processing.get('audio')!='ignore' or processing.get('temporal') not in ('ordered','preserve timestamps and order'):
        return {'status':'blocked','reason':'Decoder requires explicit N fps, ordered source timestamps and audio=ignore'}
    plan=processing.get('decoder') or {'protocol':'source_first_min_interval_v1','fps':float(match[1]),
          'max_frames':64,'max_width':640,'max_height':480,'max_duration_seconds':30,'audio':'ignore'}
    try:
        plan=validate_plan(plan)
        if plan['fps']!=float(match[1]):raise ValueError('Decoder fps differs from task sampling requirement')
    except ValueError as error:return {'status':'blocked','reason':str(error)}
    return {'status':'ready','plan':plan,'sampling_semantics':'First source frame, then first source frame at least 1/fps seconds after previous selected frame; original PTS retained.',
            'limits_semantics':'Reject exceeded limits; never truncate or resize implicitly.'}


def validate_result(request,result):
    plan=validate_plan(request['plan'])
    if not isinstance(result,dict):raise ValueError('Video response must be an object')
    if result.get('status')!='video_decoded' or result.get('input_sha256')!=request['sha256'] or result.get('plan')!=plan:
        raise ValueError('Video response input/plan identity differs')
    if result.get('inference_performed') is not False or result.get('audio_processed') is not False:raise ValueError('Unexpected video execution claim')
    frames=result.get('frames')
    if not isinstance(frames,list) or not 1<=len(frames)<=plan['max_frames']:raise ValueError('Invalid returned video frame count')
    total=0;previous=None;time_base=None
    for index,frame in enumerate(frames):
        if not isinstance(frame,dict) or not isinstance(frame.get('time_base'),dict):raise ValueError('Returned video frame must have a time base object')
        if frame.get('index')!=index or isinstance(frame.get('index'),bool) or frame.get('format')!='ppm_rgb24':raise ValueError('Invalid returned video frame sequence')
        width=frame.get('width');height=frame.get('height');pts=frame.get('pts');base=frame.get('time_base',{})
        if any(isinstance(v,bool) or not isinstance(v,int) for v in (width,height,pts,base.get('numerator'),base.get('denominator'))):raise ValueError('Invalid returned video dimensions/timestamps')
        if not 0<width<=plan['max_width'] or not 0<height<=plan['max_height'] or base['numerator']<=0 or base['denominator']<=0:raise ValueError('Returned video dimensions/time base exceed bounds')
        stamp=Fraction(pts*base['numerator'],base['denominator'])
        if frame.get('seconds')!=float(stamp) or isinstance(frame.get('seconds'),bool):raise ValueError('Returned source timestamp differs')
        if previous is not None and (base!=time_base or float(stamp-previous)+1e-12<1/plan['fps']):raise ValueError('Returned video sampling interval differs')
        previous=stamp;time_base=base
        encoded=frame.get('content_base64');header=f'P6\n{width} {height}\n255\n'.encode();size=len(header)+width*height*3
        if not isinstance(encoded,str) or len(encoded)!=4*((size+2)//3):raise ValueError('Returned video content size differs')
        raw=base64.b64decode(encoded,validate=True)
        if len(raw)!=size or not raw.startswith(header) or hashlib.sha256(raw).hexdigest()!=frame.get('sha256'):raise ValueError('Returned video RGB content hash differs')
        total+=len(raw)
        if total>64*1024*1024:raise ValueError('Returned decoded video exceeds 64 MiB')
    if result.get('decoded_bytes')!=total or isinstance(result.get('decoded_bytes'),bool):raise ValueError('Returned decoded video total differs')
    if frames[-1]['seconds']-frames[0]['seconds']>plan['max_duration_seconds']:raise ValueError('Returned video duration exceeds plan')
    return True


def timestamps(log,count):
    bases=re.findall(r'config in time_base:\s*(\d+)/(\d+)',log)
    if len(bases)!=1:raise ValueError('Missing or ambiguous source time base')
    num,den=map(int,bases[0])
    if num<=0 or den<=0:raise ValueError('Invalid source time base')
    rows=re.findall(r'\[Parsed_showinfo_\d+[^\]]*\]\s+n:\s*(\d+)\s+pts:\s*(-?\d+)\s+pts_time:',log)
    if len(rows)<count:raise ValueError('Missing source frame timestamps')
    result=[]
    for index,(n,pts) in enumerate(rows[:count]):
        if int(n)!=index:raise ValueError('Source frame sequence differs')
        pts=int(pts)
        if result and pts<=result[-1]['pts']:raise ValueError('Non-increasing source timestamps')
        result.append({'pts':pts,'time_base':{'numerator':num,'denominator':den},'seconds':float(Fraction(pts*num,den))})
    return result


def _limits():
    import resource
    for key,value in ((resource.RLIMIT_CPU,10),(resource.RLIMIT_AS,1024*1024*1024),
                      (resource.RLIMIT_FSIZE,64*1024*1024),(resource.RLIMIT_NOFILE,64),(resource.RLIMIT_NPROC,32)):
        resource.setrlimit(key,(value,value))


def _command(argv,source,output,timeout):
    prefix=['bwrap','--unshare-all','--die-with-parent','--new-session','--cap-drop','ALL',
            '--uid','65534','--gid','65534','--clearenv','--setenv','LANG','C.UTF-8',
            '--ro-bind','/usr/bin/ffmpeg','/usr/bin/ffmpeg','--ro-bind','/usr/bin/ffprobe','/usr/bin/ffprobe',
            '--ro-bind','/usr/lib/x86_64-linux-gnu','/usr/lib/x86_64-linux-gnu',
            '--symlink','usr/lib','/lib','--dir','/lib64',
            '--symlink','/usr/lib/x86_64-linux-gnu/ld-linux-x86-64.so.2','/lib64/ld-linux-x86-64.so.2',
            '--ro-bind',str(source),'/work','--bind',str(output),'/out','--dir','/tmp','--chdir','/work']
    # Ubuntu BLAS/LAPACK SONAME links cross /etc/alternatives. Bind only
    # these resolved libraries at those link targets, never host /etc.
    for name in ('libblas.so.3','liblapack.so.3'):
        library=Path('/usr/lib/x86_64-linux-gnu')/name
        if library.is_symlink():
            target=os.readlink(library)
            resolved=library.resolve(strict=True)
            if target.startswith('/etc/alternatives/') and resolved.is_relative_to('/usr/lib/x86_64-linux-gnu'):
                prefix+=['--ro-bind',str(resolved),target]
    prefix+=['--remount-ro','/']
    # /out is the sole writable bind; root remount does not remount submounts.
    with tempfile.TemporaryFile() as stdout,tempfile.TemporaryFile() as stderr:
        child=subprocess.Popen(prefix+argv,stdin=subprocess.DEVNULL,stdout=stdout,stderr=stderr,
                               start_new_session=True,preexec_fn=_limits)
        try:child.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(child.pid,signal.SIGKILL);child.wait()
            raise TimeoutError('Video decoder wall limit reached')
        stdout.seek(0);stderr.seek(0);raw=stdout.read(1024*1024+1);errors=stderr.read(1024*1024+1)
        if len(raw)>1024*1024 or len(errors)>1024*1024:raise ValueError('Video tool diagnostic limit exceeded')
        if child.returncode:raise ValueError('Isolated video tool failed: '+errors.decode(errors='replace')[-2000:])
        return raw,errors.decode(errors='replace')


def run(request):
    plan=validate_plan(request['plan'])
    workspace=PurePosixPath(request['workspace'])
    if not workspace.is_absolute() or '..' in workspace.parts or str(workspace)=='/':raise ValueError('Dedicated video workspace required')
    encoded=request['content_base64']
    if not isinstance(encoded,str) or len(encoded)>4*((64*1024*1024+2)//3):raise ValueError('Video input exceeds 64 MiB')
    raw=base64.b64decode(encoded,validate=True)
    if not 0<len(raw)<=64*1024*1024 or hashlib.sha256(raw).hexdigest()!=request['sha256']:raise ValueError('Video content hash/size differs')
    root=Path(workspace)/'video-checks';root.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='decode-',dir=root) as folder:
        source=Path(folder)/'source';source.mkdir(mode=0o755)
        output=Path(folder)/'output';output.mkdir(mode=0o777);output.chmod(0o777)
        video=source/'input.video';video.write_bytes(raw);video.chmod(0o444)
        version,_=_command(['/usr/bin/ffmpeg','-version'],source,output,5)
        probe,_=_command(['/usr/bin/ffprobe','-v','error','-protocol_whitelist','file,pipe','-select_streams','v:0',
                          '-show_entries','stream=width,height:format=duration','-of','json','/work/input.video'],source,output,5)
        metadata=json.loads(probe);streams=metadata.get('streams',[])
        if len(streams)!=1:raise ValueError('Exactly one selected video stream required')
        width=streams[0].get('width');height=streams[0].get('height')
        if not isinstance(width,int) or not isinstance(height,int) or not 0<width<=plan['max_width'] or not 0<height<=plan['max_height']:
            raise ValueError('Video resolution exceeds frozen plan; no implicit resize')
        duration=float(metadata.get('format',{}).get('duration','nan'))
        if not math.isfinite(duration) or not 0<duration<=plan['max_duration_seconds']:raise ValueError('Video duration exceeds frozen plan or is unknown')
        interval=1/plan['fps']
        filter_text=f'select=isnan(prev_selected_t)+gte(t-prev_selected_t\\,{interval:.17g}),showinfo'
        _,log=_command(['/usr/bin/ffmpeg','-nostdin','-hide_banner','-loglevel','info','-protocol_whitelist','file,pipe',
                        '-hwaccel','none','-threads','1','-copyts','-i','/work/input.video','-map','0:v:0','-an','-sn','-dn',
                        '-filter_threads','1','-vf',filter_text,'-vsync','0','-frames:v',str(plan['max_frames']+1),
                        '-threads','1','-c:v','ppm','-pix_fmt','rgb24','-f','image2','/out/frame-%06d.ppm'],source,output,15)
        paths=sorted(output.glob('frame-*.ppm'))
        if not paths or len(paths)>plan['max_frames']:raise ValueError('Sampled frame count exceeds frozen plan or is empty; no truncation accepted')
        times=timestamps(log,len(paths));total=0;frames=[]
        if times[-1]['seconds']-times[0]['seconds']>plan['max_duration_seconds']:raise ValueError('Source timestamps exceed frozen duration')
        for index,(path,stamp) in enumerate(zip(paths,times)):
            if path.name!=f'frame-{index+1:06d}.ppm':raise ValueError('Decoded frame sequence differs')
            with path.open('rb') as stream:content=stream.read(width*height*3+1025)
            header=f'P6\n{width} {height}\n255\n'.encode()
            if not content.startswith(header) or len(content)!=len(header)+width*height*3:raise ValueError('Decoded RGB frame shape differs')
            total+=len(content)
            if total>64*1024*1024:raise ValueError('Decoded video content exceeds 64 MiB')
            frames.append(dict(stamp,index=index,width=width,height=height,sha256=hashlib.sha256(content).hexdigest(),
                               format='ppm_rgb24',content_base64=base64.b64encode(content).decode()))
        return {'status':'video_decoded','input_sha256':request['sha256'],'plan':plan,'frames':frames,
                'duration_seconds':duration,'decoded_bytes':total,'audio_processed':False,'inference_performed':False,
                'ffmpeg_version':version.decode(errors='replace').splitlines()[0],
                'isolation':{'network':False,'gpu':False,'uid':65534,'cpu_seconds_per_tool':10,'wall_seconds_probe':5,'wall_seconds_decode':15}}


if __name__=='__main__':
    import sys
    print(json.dumps(run(json.load(sys.stdin)),allow_nan=False))
