"""Append the user's CTA without recompressing the encoded story."""
import json
import math
from pathlib import Path
from .render import file_hash,probe,run


def resolve_outro(spec,defaults_path):
    defaults_path=Path(defaults_path)
    defaults=json.loads(defaults_path.read_text(encoding='utf-8')) if defaults_path.exists() else {}
    config=spec.get('outro',defaults.get('outro'))
    if not config:return None
    path=Path(config['path'])
    if not path.is_absolute():path=defaults_path.parent.parent/path
    duration=float(config.get('duration',4));hold=float(spec.get('ending_hold_seconds',0))
    if not math.isfinite(duration) or not 0<duration<=10:
        raise ValueError('CTA duration must be 0–10 seconds.')
    if hold!=0:raise ValueError('Ending holds are disabled. Preserve the original laughter once and append the CTA directly.')
    metadata=probe(path)
    video=next(s for s in metadata['streams'] if s['codec_type']=='video')
    if (video['width'],video['height'])!=(1080,1920):raise ValueError('Supply a 1080 × 1920 CTA so its layout is preserved.')
    if duration>float(metadata['format']['duration']):raise ValueError('CTA is shorter than its requested cut.')
    return {'path':str(path.resolve()),'duration':duration,'hold_seconds':0,'sha256':file_hash(path)}


def append_outro(body,path,config):
    body=Path(body);path=Path(path);root=path.parent
    encoding=['-c:v','libx264','-preset','fast','-crf','18','-pix_fmt','yuv420p','-c:a','aac','-b:a','192k','-ar','48000','-ac','2','-movflags','+faststart']
    pieces=[body.resolve()]
    if config.get('hold_seconds',0)!=0:raise ValueError('Do not extend or repeat the original ending.')
    hold=0
    cta=root/'cta-four-seconds.mp4';metadata=probe(config['path'])
    has_audio=any(s['codec_type']=='audio' for s in metadata['streams'])
    args=['ffmpeg','-v','error','-y','-i',config['path']]
    if not has_audio:args+=['-f','lavfi','-i','anullsrc=r=48000:cl=stereo']
    args+=['-map','0:v:0','-map','0:a:0' if has_audio else '1:a:0','-vf','fps=30,setsar=1','-t',str(config['duration']),*encoding,str(cta)]
    run(args);pieces.append(cta.resolve())
    listing=root/'outro-concat.txt'
    listing.write_text(''.join("file '"+str(p).replace('\\','/').replace("'","'\\''")+"'\n" for p in pieces),encoding='utf-8')
    temp=path.with_name('outro-final.tmp.mp4')
    run(['ffmpeg','-v','error','-y','-f','concat','-safe','0','-i',str(listing),'-map','0:v:0','-map','0:a:0','-c','copy','-movflags','+faststart',str(temp)])
    metadata=probe(temp);streams=metadata['streams'];v=next(s for s in streams if s['codec_type']=='video');a=next(s for s in streams if s['codec_type']=='audio')
    story_duration=float(probe(body)['format']['duration']);expected=story_duration+hold+config['duration'];actual=float(metadata['format']['duration'])
    checks=[{'name':'Story plus CTA duration','status':'pass' if abs(actual-expected)<.1 else 'fail','detail':f'{story_duration:.3f}s original story ending, no hold or repetition + {config["duration"]:.3f}s CTA = {actual:.3f}s export.'},
            {'name':'Final encoding and stream duration','status':'pass' if v['width']==1080 and v['height']==1920 and v['codec_name']=='h264' and a['codec_name']=='aac' and abs(float(v.get('duration',0))-float(a.get('duration',0)))<.1 else 'fail','detail':'1080 × 1920 H.264/AAC; original story audio/video copied without recompression. CTA black background is intentional.'}]
    if any(c['status']=='fail' for c in checks):raise RuntimeError('CTA assembly failed technical validation; inspect saved parts.')
    temp.replace(path)
    return {'story_duration':story_duration,'hold_seconds':0,'audio_repetitions':0,'cta_duration':config['duration'],'total_duration':actual,'cta_start':story_duration,'cta_sha256':config['sha256'],'checks':checks}
