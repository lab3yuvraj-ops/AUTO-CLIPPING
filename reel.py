"""Local Codex-operated Reel workflow. No web server or text/vision API."""
import argparse,hashlib,json,math,os,re,shutil,sys,time
from pathlib import Path
from types import SimpleNamespace
import httpx
from reel_engine.config import settings,ROOT
from reel_engine import youtube,publishing
from reel_engine.local_transcription import transcribe_local
from reel_engine.render import render_clip,validate_render,probe
from reel_engine.timeline import build_edit,silence_intervals
from reel_engine.visual_focus import validate_targets

STATE=ROOT/'workflow'
def read(path):return json.loads(path.read_text(encoding='utf-8'))
def save(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_suffix('.tmp');temporary.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8');temporary.replace(path)
def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()
def engine_version():
    """Invalidate cached previews when the local editing implementation changes."""
    h=hashlib.sha256()
    rules=[ROOT/'AGENTS.md'] if (ROOT/'AGENTS.md').is_file() else []
    for path in sorted([ROOT/'reel.py',*(ROOT/'reel_engine').glob('*.py'),*rules]):
        h.update(path.name.encode());h.update(path.read_bytes())
    return h.hexdigest()
def job_path(ident):
    if not re.fullmatch(r'[A-Za-z0-9_-]{11,64}',ident):raise ValueError('Invalid job ID.')
    return STATE/'jobs'/ident/'job.json'
def connect(channel):
    if re.fullmatch(r'UC[A-Za-z0-9_-]{22}',channel):ident=channel
    else:
        if not re.fullmatch(r'https://(?:www\.)?youtube\.com/(?:@[A-Za-z0-9_.-]+|channel/UC[A-Za-z0-9_-]{22})/?',channel):raise ValueError('Use a YouTube channel ID or channel URL.')
        r=httpx.get(channel,timeout=30,follow_redirects=True);r.raise_for_status()
        ids=re.findall(r'"(?:channelId|externalId)":"(UC[A-Za-z0-9_-]{22})"',r.text)
        if not ids:raise ValueError('Could not resolve this channel. Supply its UC channel ID.')
        ident=ids[0]
    save(STATE/'connection.json',{'channel_id':ident,'channel_url':channel})
    return {'channel_id':ident}
def latest():
    if not (STATE/'connection.json').exists():raise ValueError('No YouTube channel is connected. Say onboarding in Codex to configure your own channel first.')
    channel=read(STATE/'connection.json')['channel_id']
    r=httpx.get(youtube.topic(channel),headers={'Cache-Control':'no-cache'},timeout=30);r.raise_for_status()
    stamps=youtube.feed_published(r.content)
    videos=[v for v,c in youtube.feed_ids(r.content) if c==channel and 0<stamps.get(v,0)<=time.time()]
    if not videos:
        # RSS can lag a newly released upload. Read the channel's selected
        # Videos tab, not unrelated recommendations or arbitrary page IDs.
        response=httpx.get(f'https://www.youtube.com/channel/{channel}/videos',headers={'Cache-Control':'no-cache'},timeout=30,follow_redirects=True);response.raise_for_status()
        text=getattr(response,'text','');match=re.search(r'(?:var\s+)?ytInitialData\s*=\s*',text)
        data=json.JSONDecoder().raw_decode(text[match.end():])[0] if match else {}
        tabs=data.get('contents',{}).get('twoColumnBrowseResultsRenderer',{}).get('tabs',[])
        candidates=[]
        def visit(node):
            if isinstance(node,dict):
                renderer=node.get('videoRenderer',{})
                vid=renderer.get('videoId')
                if re.fullmatch(r'[A-Za-z0-9_-]{11}',vid or '') and not renderer.get('upcomingEventData'):candidates.append(vid)
                modern=node.get('lockupViewModel',{})
                vid=modern.get('contentId')
                if re.fullmatch(r'[A-Za-z0-9_-]{11}',vid or '') and modern.get('contentType')=='LOCKUP_CONTENT_TYPE_VIDEO':candidates.append(vid)
                for value in node.values():visit(value)
            elif isinstance(node,list):
                for value in node:visit(value)
        for tab in tabs:
            renderer=tab.get('tabRenderer',{})
            if renderer.get('selected'):visit(renderer.get('content',{}))
        if candidates:return candidates[0],channel
        raise ValueError('No released upload found in the connected channel’s feed or Videos tab.')
    return max(videos,key=lambda v:stamps[v]),channel
def analyze(url=None,file=None,clips=None):
    if clips is not None and (not isinstance(clips,int) or isinstance(clips,bool) or clips<1):raise ValueError('Requested clip count must be a positive integer.')
    channel=None
    if file:
        source=Path(file).resolve();ident=digest(source)
    elif url:ident=youtube.video_id(url)
    else:ident,channel=latest()
    path=job_path(ident);root=path.parent
    job=read(path) if path.exists() else {'id':ident,'created':time.time(),'status':'Detected','config':{'min_source_height':settings.min_source_height,'channel_id':channel,'verify_channel':bool(channel),'auto_publish':False}}
    if clips is not None:
        job['requested_clips']=clips;save(path,job)
    if job.get('status')=='Published':return job
    if job.get('status')=='Needs approval':
        if job.get('engine_version') and job['engine_version']!=engine_version():
            job['status']='Awaiting Codex update';job['error']='Editing implementation changed. Review and render the saved edit with the current version.';save(path,job)
        return job
    try:
        if not job.get('source'):
            root.mkdir(parents=True,exist_ok=True);job['status']='Downloading';save(path,job)
            if file:
                destination=root/'source.mp4';shutil.copy2(source,destination);job['source']=str(destination)
            else:
                attempts=job.get('download_attempts',0)
                if attempts>=3:raise ValueError('Download retry limit reached. Resolve the saved error, then reset download_attempts explicitly.')
                job['download_attempts']=attempts+1;save(path,job)
                result=youtube.download(SimpleNamespace(video_id=ident,config=job['config'],created=job['created']),root)
                job.update(result)
            job['source_sha256']=digest(Path(job['source']));save(path,job)
        job['status']='Transcribing';save(path,job)
        job.update(transcribe_local(job['source'],root))
        job['status']='Awaiting Codex edit';job.pop('error',None);save(path,job)
    except Exception as exc:
        job['error']=str(exc);save(path,job);raise
    return job
def prepare_edit(job,spec,root):
    plan=spec['candidate'];words=spec['words'];tracking=spec['tracking']
    duration=float(probe(job['source'])['format']['duration'])
    if not 0<=plan['start']<plan['end']<=duration or not 30<=plan['end']-plan['start']<=60:raise ValueError('Select a complete source passage of 30–60 seconds within the video.')
    if not words or len({w['id'] for w in words})!=len(words) or any(not w.get('roman') or not math.isfinite(w['start']) or not math.isfinite(w['end']) or not plan['start']<=w['start']<w['end']<=plan['end'] for w in words):raise ValueError('Supply unique Roman word IDs with valid source timing inside the passage.')
    tracking={**tracking,'mode':'auto','composition':'fill','crop_policy':'full_source_height_horizontal_only','camera_smoothing':True,'camera_easing_seconds':1.2}
    tracking['visual_targets']=validate_targets(tracking.get('visual_targets',[]),plan['start'],plan['end'])
    silence=root/'silences.json'
    if not silence.exists():save(silence,silence_intervals(job['source']))
    edit=build_edit(plan,words,read(silence));edit['caption_positions']=[]
    if not 30<=edit['duration']<=60:raise ValueError('Edited duration must remain 30–60 seconds.')
    return edit,tracking

def review(ident,edit_path):
    from reel_engine.review import make_review
    path=job_path(ident);job=read(path);spec=read(Path(edit_path))
    edit,tracking=prepare_edit(job,spec,path.parent)
    return make_review(job['source'],edit,tracking,path.parent)

def render(ident,edit_path):
    path=job_path(ident);job=read(path);root=path.parent;spec=read(Path(edit_path))
    plan=spec['candidate'];edit,tracking=prepare_edit(job,spec,root)
    version=engine_version()
    from reel_engine.outro import resolve_outro,append_outro
    outro=resolve_outro(spec,STATE/'output-defaults.json')
    signature=hashlib.sha256(json.dumps({'source':job['source_sha256'],'edit':edit,'tracking':tracking,'outro':outro,'engine_version':version,'font':'Creepster','caption_y':1420},sort_keys=True).encode()).hexdigest()
    if job.get('render_signature')==signature and Path(job.get('video','')).is_file() and digest(Path(job['video']))==job.get('render_sha256'):return job
    if job.get('publishing'):raise ValueError('A publication exists for this render. Reconcile it before changing the video.')
    job['status']='Rendering';save(path,job)
    video=root/'reel.mp4'
    body=root/'story.mp4' if outro else video
    info=render_clip(job['source'],edit,tracking,body,{'font':'Creepster','caption_y':1420})
    validation_started=time.perf_counter()
    checks=validate_render(body,edit,60,tracking,info['caption_events'],minimum=30,render_info=info)
    info['timings']['validation_seconds']=time.perf_counter()-validation_started
    if outro:
        started=time.perf_counter();info['outro']=append_outro(body,video,outro)
        info['timings']['outro_seconds']=time.perf_counter()-started
        checks+=info['outro']['checks']
    save(root/'edit.json',{'candidate':plan,'edit':edit,'tracking':tracking,'render_info':info})
    job.update(status='Validation failed' if any(c['status']=='fail' for c in checks) else 'Needs approval',video=str(video),render_sha256=digest(video),render_signature=signature,engine_version=version,checks=checks,caption=spec.get('caption',''))
    job.pop('approval',None);save(path,job);return job
def publish(ident,confirmed=False):
    path=job_path(ident);job=read(path)
    if job.get('post_id'):return job
    if not confirmed:raise ValueError('Use --confirmed only after the user says “good to go” for this exact render.')
    if job.get('status') not in ('Needs approval','Publishing') or any(c['status']=='fail' for c in job.get('checks',[])) or not job.get('checks'):raise ValueError('Render and resolve failed checks before publishing.')
    if digest(Path(job['video']))!=job['render_sha256']:raise ValueError('Video changed after validation. Render and review again.')
    if not settings.zernio_instagram_id:raise ValueError('Set ZERNIO_INSTAGRAM_ID to the connected Zernio Instagram account ID.')
    record=job.get('publishing')
    if record and record['account_id']!=settings.zernio_instagram_id:raise ValueError('Account changed; reconcile the existing publication.')
    job['approval']={'command':'good to go','at':time.time(),'render_sha256':job['render_sha256']};save(path,job)
    if not record:
        signed=publishing.request('POST','/media/presign',payload={'filename':'reel.mp4','contentType':'video/mp4','size':Path(job['video']).stat().st_size})
        if not signed['uploadUrl'].startswith('https://') or not signed['publicUrl'].startswith('https://'):raise ValueError('Invalid upload URL.')
        with Path(job['video']).open('rb') as f:
            response=httpx.put(signed['uploadUrl'],content=f,headers={'Content-Type':'video/mp4'},timeout=600);response.raise_for_status()
        payload={'content':job['caption'],'mediaItems':[{'type':'video','url':signed['publicUrl']}],'platforms':[{'platform':'instagram','accountId':settings.zernio_instagram_id,'platformSpecificData':{'shareToFeed':True}}],'publishNow':True}
        record={'account_id':settings.zernio_instagram_id,'started':time.time(),'payload':payload,'key':'codex-reel-'+job['render_sha256']}
        job.update(publishing=record,status='Publishing');save(path,job)
    if not record.get('provider_post_id'):
        if time.time()-record['started']>23*3600:raise ValueError('Safe retry window expired. Reconcile the original Zernio post; do not resubmit.')
        result=publishing.request('POST','/posts',payload=record['payload'],key=record['key'])
        post_id=result.get('post',{}).get('_id') or result.get('postId')
        if not post_id:raise ValueError('Provider returned no post ID; saved idempotency key retained.')
        record['provider_post_id']=str(post_id);save(path,job)
    result=publishing.request('GET','/posts/'+record['provider_post_id']);post=result.get('post',{})
    target=next((p for p in post.get('platforms',[]) if p.get('platform')=='instagram' and str(p.get('accountId',{}).get('_id') if isinstance(p.get('accountId'),dict) else p.get('accountId'))==record['account_id']),None)
    if not target:raise ValueError('Instagram target not confirmed in provider response.')
    if target.get('status')=='published' and target.get('platformPostId'):
        job.update(status='Published',post_id=str(target['platformPostId']),permalink=target.get('platformPostUrl'));save(path,job)
    elif target.get('status') in ('failed','cancelled'):raise ValueError('Publication failed. Correct or retry the existing post in Zernio; do not create a new one.')
    return job
def main():
    if hasattr(sys.stdout,"reconfigure"):sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr,"reconfigure"):sys.stderr.reconfigure(encoding="utf-8")
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='command',required=True)
    p=sub.add_parser('connect');p.add_argument('channel')
    p=sub.add_parser('onboarding');p.add_argument('--channel',required=True);p.add_argument('--from-env',action='store_true',help='Read credentials privately from .env instead of terminal prompts.')
    p=sub.add_parser('prepare-models');p.add_argument('--download',action='store_true',help='Authorize one-time local model downloads; later runs use cached models offline.')
    p=sub.add_parser('analyze');group=p.add_mutually_exclusive_group();group.add_argument('--url');group.add_argument('--file');p.add_argument('--clips',type=int,help='Requested clip count; Codex reports fewer when the source lacks strong complete moments.')
    p=sub.add_parser('render');p.add_argument('job');p.add_argument('--edit',required=True)
    p=sub.add_parser('review');p.add_argument('job');p.add_argument('--edit',required=True)
    p=sub.add_parser('recheck');p.add_argument('job');p.add_argument('--range',action='append',required=True,help='Source seconds START:END; repeat for multiple passages.')
    p=sub.add_parser('publish');p.add_argument('job');p.add_argument('--confirmed',action='store_true')
    p=sub.add_parser('status');p.add_argument('job')
    args=parser.parse_args();STATE.mkdir(exist_ok=True)
    import msvcrt
    with (STATE/'.lock').open('a+b') as lock:
        lock.seek(0);lock.write(b'0');lock.flush();lock.seek(0)
        try:msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
        except OSError:raise SystemExit('Another local workflow command is running.')
        try:
            if args.command=='connect':result=connect(args.channel)
            elif args.command=='onboarding':
                from reel_engine.onboarding import onboard
                result=onboard(ROOT,args.channel,connect,args.from_env)
            elif args.command=='prepare-models':
                from reel_engine.local_transcription import load_models
                load_models(allow_download=args.download)
                result={'local_models_ready':True,'provider':'local','device':settings.local_device,'whisper_model':settings.whisper_model}
            elif args.command=='analyze':result=analyze(args.url,args.file,args.clips)
            elif args.command=='render':result=render(args.job,args.edit)
            elif args.command=='review':result=review(args.job,args.edit)
            elif args.command=='recheck':
                from reel_engine.local_transcription import recheck_local
                ranges=[tuple(map(float,value.split(':'))) for value in args.range]
                if any(len(pair)!=2 for pair in ranges):raise ValueError('Use START:END for each recheck range.')
                result=recheck_local(job_path(args.job).parent,ranges)
            elif args.command=='publish':result=publish(args.job,args.confirmed)
            else:result=read(job_path(args.job))
            # Do not expose signed upload URLs or provider payloads in chat.
            print(json.dumps({k:v for k,v in result.items() if k not in ('publishing','config')},ensure_ascii=False,indent=2))
        except httpx.HTTPError:raise SystemExit('Network or upload request failed. Retry the saved stage; signed URLs are not printed.') from None
        except Exception as exc:raise SystemExit(str(exc)) from None
        finally:lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1)
if __name__=='__main__':main()
