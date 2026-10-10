import json
import cv2
import pytest
from reel_engine.outro import resolve_outro,append_outro
from reel_engine.render import run,probe


def test_cta_preserves_original_ending_once_without_a_hold(tmp_path):
    body=tmp_path/'body.mp4';cta=tmp_path/'cta.mp4';output=tmp_path/'reel.mp4'
    encoding=['-c:v','libx264','-preset','fast','-crf','18','-pix_fmt','yuv420p']
    run(['ffmpeg','-v','error','-y','-f','lavfi','-i','color=c=green:s=1080x1920:r=30:d=1',
         '-f','lavfi','-i','sine=frequency=700:sample_rate=48000:duration=1',
         *encoding,'-c:a','aac','-b:a','192k','-ac','2',str(body)])
    run(['ffmpeg','-v','error','-y','-f','lavfi','-i','color=c=red:s=1080x1920:r=30:d=5',
         '-vf',"drawbox=x=0:y=0:w=iw:h=ih:color=blue:t=fill:enable='gte(t,4)'",*encoding,str(cta)])
    defaults=tmp_path/'defaults.json';defaults.write_text(json.dumps({'outro':{'path':str(cta),'duration':4}}))
    config=resolve_outro({},defaults)
    report=append_outro(body,output,config)
    assert report['total_duration']==pytest.approx(5,abs=.1)
    assert report['cta_start']==1
    assert report['hold_seconds']==0 and report['audio_repetitions']==0
    cap=cv2.VideoCapture(str(output))
    for t in [1.2,4.8]:
        cap.set(cv2.CAP_PROP_POS_MSEC,t*1000);ok,frame=cap.read();assert ok
        assert int(frame[500,500,2])>200 and int(frame[500,500,0])<30
    cap.release()
    def frame_hashes(path):
        data=run(['ffmpeg','-v','error','-i',str(path),'-map','0:v:0','-frames:v','30','-f','framemd5','-']).stdout
        return [line.split(',')[-1].strip() for line in data.splitlines() if line and not line.startswith('#')]
    # MP4 concatenation may insert H.264 parameter sets in the first packet;
    # decoded pixels, rather than container packet bytes, prove no generation loss.
    assert frame_hashes(output)==frame_hashes(body)
    assert all(c['status']=='pass' for c in report['checks'])
    import numpy as np
    # Once the original ends, its audio must not repeat over the silent CTA.
    import subprocess
    pcm=subprocess.check_output(['ffmpeg','-v','error','-ss','1.15','-i',str(output),'-t','0.5','-vn','-ar','16000','-ac','1','-f','s16le','-'])
    assert np.sqrt(np.mean(np.frombuffer(pcm,dtype='<i2').astype(float)**2))<1
    with pytest.raises(ValueError,match='shorter'):resolve_outro({'outro':{'path':str(cta),'duration':6}},defaults)
    with pytest.raises(ValueError,match='holds are disabled'):resolve_outro({'ending_hold_seconds':2},defaults)
