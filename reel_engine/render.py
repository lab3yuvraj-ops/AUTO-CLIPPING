import json
import hashlib
import inspect
import time
import math
import re
import subprocess
from pathlib import Path
import cv2
import numpy as np
from .captions import make_ass
from .timeline import to_source
from .tracking import crop_centers, fill_missing_centers
from .visual_focus import active_target, focus_frame, focus_geometry, camera_frame, validate_targets, TargetMotionTracker
from .camera import ease_camera


def run(args, timeout=7200, cwd=None):
    r=subprocess.run(args,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=timeout,cwd=cwd)
    if r.returncode:
        raise RuntimeError('Media processing failed: '+r.stderr[-2000:])
    return r


def probe(path):
    return json.loads(run(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(path)]).stdout)


def file_hash(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()


def edit_source(source,edit,path):
    """Reuse only a verified, identical lossless source-to-output edit."""
    path=Path(path);cache=path.with_suffix('.cache.json')
    signature=hashlib.sha256(json.dumps({'version':1,'implementation':hashlib.sha256(inspect.getsource(_edit_source_uncached).encode()).hexdigest(),'source':file_hash(source),
        'segments':edit['segments'],'codec':'ffv1-level3-pcm24','fps':30},sort_keys=True).encode()).hexdigest()
    if cache.exists() and path.exists():
        saved=json.loads(cache.read_text())
        if saved.get('signature')==signature and saved.get('sha256')==file_hash(path):return True
    _edit_source_uncached(source,edit,path)
    cache.write_text(json.dumps({'signature':signature,'sha256':file_hash(path)}))
    return False


def _edit_source_uncached(source,edit,path):
    # Accurate input seeking avoids decoding the entire lead-in for a single
    # continuous passage. FFmpeg discards pre-roll while transcoding.
    if len(edit['segments']) == 1:
        segment = edit['segments'][0]
        duration = segment['source_end'] - segment['source_start']
        run(['ffmpeg','-v','error','-y','-ss',str(segment['source_start']),
             '-i',str(source),'-t',str(duration),'-map','0:v:0','-map','0:a:0',
             '-vf','fps=30:start_time=0',
             '-af',f'afade=t=in:d=0.005,afade=t=out:st={max(0,duration-.005)}:d=0.005',
             '-c:v','ffv1','-level','3','-c:a','pcm_s24le',str(path)])
        return
    parts=[]; labels=[]
    for i,s in enumerate(edit['segments']):
        a,b=s['source_start'],s['source_end']; duration=b-a
        parts.append(f'[0:v]trim=start={a}:end={b},setpts=PTS-STARTPTS[v{i}];[0:a]atrim=start={a}:end={b},asetpts=PTS-STARTPTS,afade=t=in:d=0.005,afade=t=out:st={max(0,duration-.005)}:d=0.005[a{i}]')
        labels.append(f'[v{i}][a{i}]')
    graph=';'.join(parts)+';'+''.join(labels)+f'concat=n={len(labels)}:v=1:a=1[v][a]'
    graph_path=path.parent/'edit-filter.txt'; graph_path.write_text(graph,encoding='utf-8')
    run(['ffmpeg','-v','error','-y','-i',str(source),'-filter_complex_script',str(graph_path),'-map','[v]','-map','[a]','-c:v','ffv1','-level','3','-c:a','pcm_s24le',str(path)])


def compose(frame,center,ow=1080,oh=1920):
    h,w=frame.shape[:2]
    crop_w=round(h*9/16)
    if center is not None and crop_w<=w:
        x=int(np.clip(center*w-crop_w/2,0,w-crop_w))
        return cv2.resize(frame[:,x:x+crop_w],(ow,oh),interpolation=cv2.INTER_LANCZOS4)
    # Full-scene fallback: fit every character over a blurred copy.
    scale=max(ow/w,oh/h)
    bg=cv2.resize(frame,(math.ceil(w*scale),math.ceil(h*scale)))
    yy=(bg.shape[0]-oh)//2; xx=(bg.shape[1]-ow)//2
    bg=bg[yy:yy+oh,xx:xx+ow]
    bg=cv2.resize(cv2.GaussianBlur(cv2.resize(bg,(108,192)),(31,31),0),(ow,oh))
    bg=(bg*.42).astype(np.uint8)
    scale=min(ow/w,oh/h)
    fg=cv2.resize(frame,(round(w*scale),round(h*scale)),interpolation=cv2.INTER_LANCZOS4)
    yy=(oh-fg.shape[0])//2; xx=(ow-fg.shape[1])//2
    bg[yy:yy+fg.shape[0],xx:xx+fg.shape[1]]=fg
    return bg


def plan_camera(cap,tracking,centers,times,fps):
    """Reviewed anchors need dimensions, not a second video decode pass."""
    targets=tracking.get('visual_targets',[])
    tracker=TargetMotionTracker();geometry=[]
    anchored=all(not active_target(targets,t) or active_target(targets,t).get('box_keyframes') for t in times)
    dimensions=np.empty((int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),0),dtype=np.uint8)
    for i,t in enumerate(times):
        if anchored:frame=dimensions
        else:
            ok,frame=cap.read()
            if not ok:raise RuntimeError('Missing frame while planning camera easing.')
        target=tracker.update(frame,active_target(targets,t),t)
        geometry.append(focus_geometry(frame,centers[i],target,source_time=t))
    path=ease_camera(geometry,times,tracking.get('camera_cuts',[]),fps,tracking.get('camera_easing_seconds',.8))
    if not anchored:cap.set(cv2.CAP_PROP_POS_FRAMES,0)
    return path,tracker,anchored


def render_clip(source, edit, tracking, path, config):
    started=time.perf_counter();timings={}
    root=path.parent; root.mkdir(parents=True,exist_ok=True)
    edited=root/'edited.mkv'
    reused=edit_source(source,edit,edited)
    timings['lossless_edit_seconds']=time.perf_counter()-started
    ass=root/'captions.ass'
    events=make_ass(edit['words'],ass,config.get('font','Creepster'),config.get('caption_y',1420),positions=edit.get('caption_positions'))
    (root/'caption-events.json').write_text(json.dumps(events),encoding='utf-8')
    cap=cv2.VideoCapture(str(edited)); source_fps=cap.get(cv2.CAP_PROP_FPS)
    # Render a deterministic 30 fps output without altering audio duration.
    fps=30; count=math.floor(edit['duration']*fps)
    times=[to_source(i/fps,edit['segments']) for i in range(count)]
    targets=validate_targets(tracking.get('visual_targets',[]),edit['segments'][0]['source_start'],edit['segments'][-1]['source_end'])
    centers=crop_centers(tracking, [{**w,'start':w.get('source_start',w['start']),'end':w.get('source_end',w['end'])} for w in edit['words']], times)
    fit=tracking.get('mode')=='fit'
    uncertain_frames=sum(c is None for c in centers)
    if fit:
        centers=[None]*count
    else:
        # Default output fills the canvas. One uncertain turn must not force
        # the entire clip into a letterboxed blurred composition.
        centers=fill_missing_centers(centers,tracking,times)
    fonts=(Path(__file__).resolve().parent.parent/'assets').as_posix().replace(':','\\:')
    temp=root/'render.tmp.mp4'
    encoder=config.get('encoder','libx264')
    if encoder=='libx264':encoding=['-c:v','libx264','-preset','fast','-crf','18']
    elif encoder=='h264_nvenc':encoding=['-c:v','h264_nvenc','-preset','p7','-tune','hq','-rc','vbr','-cq','16','-b:v','0','-multipass','fullres']
    else:raise ValueError('Unsupported video encoder.')
    command=['ffmpeg','-v','error','-y','-f','rawvideo','-pix_fmt','bgr24','-s','1080x1920','-r',str(fps),'-i','pipe:0','-i',str(edited.resolve()),'-map','0:v:0','-map','1:a:0','-vf',f"ass=captions.ass:fontsdir='{fonts}'",*encoding,'-pix_fmt','yuv420p','-c:a','aac','-b:a','192k','-ar','48000','-ac','2','-t',str(count/fps),'-movflags','+faststart',str(temp.resolve())]
    stderr_path=root/'render.log'
    focus_motion=TargetMotionTracker()
    camera_path=None
    planning_started=time.perf_counter();anchored=False
    if tracking.get('camera_smoothing') and not fit:
        # Plan geometry first, then ease it with lookahead. Pixels are always
        # sampled from the current frame, so audio and captions never retime.
        camera_path,focus_motion,anchored=plan_camera(cap,tracking,centers,times,fps)
        (root/'camera-path.json').write_text(json.dumps({'version':1,'fps':fps,'times':times,'geometry':camera_path}),encoding='utf-8')
    timings['camera_planning_seconds']=time.perf_counter()-planning_started
    encoding_started=time.perf_counter()
    with stderr_path.open('wb') as err:
        process=subprocess.Popen(command,stdin=subprocess.PIPE,stderr=err,cwd=root)
        current=-1; frame=None
        try:
            for i in range(count):
                target=int(i*source_fps/fps)
                while current<target:
                    ok,frame=cap.read(); current+=1
                    if not ok:
                        raise RuntimeError('Unexpected end of edited video; render not accepted.')
                if camera_path is not None:
                    composed=camera_frame(frame,camera_path[i])
                else:
                    target=active_target(targets,times[i]) if not fit else None
                    target=focus_motion.update(frame,target,times[i])
                    composed=focus_frame(frame,centers[i],target,source_time=times[i])
                process.stdin.write(composed.tobytes())
            process.stdin.close()
            if process.wait(timeout=600):
                raise RuntimeError('Caption/render encoding failed. Inspect this clip render.log.')
        except BaseException:
            process.kill(); process.wait(); raise
        finally:
            cap.release()
    temp.replace(path)
    timings['compose_encode_seconds']=time.perf_counter()-encoding_started
    timings['total_render_seconds']=time.perf_counter()-started
    return {'caption_events':events,'render_frames':count,'fps':fps,
            'timings':timings,'lossless_edit_reused':reused,'anchor_only_planning':anchored,'encoder':encoder,
            'full_source_height':bool(camera_path) and all(abs(g[1]-.5)<1e-9 and abs(g[2]-1)<1e-9 for g in camera_path),
            'fallback_frames':sum(c is None for c in centers),
            'uncertain_framing_frames':uncertain_frames,'composition':'fit' if fit else 'fill',
            'visual_target_frames':sum(active_target(targets,t) is not None for t in times) if not fit else 0,
            'focus_motion_failed_frames':focus_motion.failed_frames,'focus_motion_tracked_frames':focus_motion.tracked_frames,
            'focus_identity_anchored_frames':focus_motion.anchored_frames,'focus_reacquired_frames':focus_motion.reacquired_frames,
            'camera_easing_seconds':tracking.get('camera_easing_seconds',.8) if camera_path is not None else 0}


def validate_render(path,edit,maximum,tracking,events,minimum=0,render_info=None):
    data=probe(path); streams=data['streams']
    v=next((s for s in streams if s['codec_type']=='video'),{})
    a=next((s for s in streams if s['codec_type']=='audio'),{})
    duration=float(data['format']['duration'])
    checks=[]
    def check(name,passed,detail,review=False):
        checks.append({'name':name,'status':'pass' if passed else ('review' if review else 'fail'),'detail':detail})
    check('Reel encoding',v.get('width')==1080 and v.get('height')==1920 and v.get('codec_name')=='h264' and a.get('codec_name')=='aac','1080 × 1920, H.264 / AAC')
    if tracking.get('crop_policy')=='full_source_height_horizontal_only':
        check('Full-height crop',bool(render_info and render_info.get('full_source_height')),'Every planned frame keeps the entire source height; horizontal movement only.')
    check('Duration',minimum<=duration<=maximum and duration>0, f'{duration:.3f}s / required {minimum}–{maximum}s')
    delta=abs(float(v.get('duration',0))-float(a.get('duration',0)))
    check('A/V stream duration',bool(a) and delta<=.1,f'Stream difference {delta:.3f}s; semantic lip sync still needs review.')
    valid=all(0<=w['start']<w['end']<=duration+.04 for w in edit['words'])
    check('Caption timeline',valid,'All word intervals are mapped through the edit decision list.')
    correct=all(len(e['active_ids'])<=1 and all(any(w['id']==wid and w['start']<=e['start']+.011 and w['end']>=e['end']-.011 for w in edit['words']) for wid in e['active_ids']) for e in events)
    check('Spoken-word highlight',correct,'White text resets at every boundary; red is restricted to a spoken source-word group.')
    r=run(['ffmpeg','-hide_banner','-nostats','-i',str(path),'-vf','blackdetect=d=0.15:pix_th=0.04,freezedetect=n=-55dB:d=2','-af','volumedetect','-f','null','-'])
    check('Black frames','black_start:' not in r.stderr,'Black segments require review; intentional darkness can be approved.',True)
    check('Frozen sections','freeze_start:' not in r.stderr,'Static animated scenes may be intentional; review any detected freeze.',True)
    m=re.search(r'mean_volume: ([-\w.]+) dB',r.stderr)
    check('Audio present',bool(m) and m.group(1)!='-inf' and float(m.group(1))>-65,'Decoded audio must contain measurable signal.')
    check('Framing',not tracking.get('unresolved',True),'Review speaker assignments, scene changes, faces, and action preservation.',True)
    if tracking.get('focus_plan_version'):
        check('Story focus',tracking.get('confirmed',False) and not any(t.get('confidence',0)<.75 for t in tracking.get('visual_targets',[])),
              'Review each full-screen object, text and reveal target, reading pan, headroom and face clearance. Sampled vision is not proof of continuous tracking.',True)
    if render_info and render_info.get('visual_target_frames'):
        failed=render_info.get('focus_motion_failed_frames',0)
        check('Target motion',failed==0,f'{failed} target frames held their previous box because visual motion evidence was insufficient. Review moving targets.',True)
    # Computer checks cannot prove complete sentences, transcription accuracy or aesthetic quality.
    check('Editorial review',False,'Watch opening/ending, speech accuracy, Roman Hindi, lip sync, caption placement, and any false-start cuts.',True)
    return checks
