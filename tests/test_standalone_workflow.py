import time
import json
import pytest
import reel


def test_requested_count_is_saved_without_reprocessing_a_completed_source(monkeypatch,tmp_path):
    monkeypatch.setattr(reel,'STATE',tmp_path)
    path=reel.job_path('testvideo01')
    reel.save(path,{'id':'testvideo01','status':'Needs approval','engine_version':reel.engine_version(),'video':'saved-preview.mp4'})
    def unexpected(*args,**kwargs):raise AssertionError('Completed source must not be downloaded or transcribed again.')
    monkeypatch.setattr(reel.youtube,'download',unexpected)
    monkeypatch.setattr(reel,'transcribe_local',unexpected)
    result=reel.analyze(url='https://youtu.be/testvideo01',clips=2)
    assert result['requested_clips']==2 and result['status']=='Needs approval'
    assert reel.read(path)['requested_clips']==2
    assert result['video']=='saved-preview.mp4'


@pytest.mark.parametrize('count',[0,-1,1.5,True])
def test_invalid_requested_count_fails_before_source_lookup(monkeypatch,count):
    monkeypatch.setattr(reel,'latest',lambda:pytest.fail('Must validate count first.'))
    with pytest.raises(ValueError,match='positive integer'):reel.analyze(clips=count)

def test_empty_channel_does_not_invent_upload(monkeypatch,tmp_path):
    monkeypatch.setattr(reel,'STATE',tmp_path)
    reel.save(tmp_path/'connection.json',{'channel_id':'UC'+'a'*22})
    class Response:
        content=b'<feed xmlns="http://www.w3.org/2005/Atom"/>'
        def raise_for_status(self):pass
    monkeypatch.setattr(reel.httpx,'get',lambda *a,**k:Response())
    with pytest.raises(ValueError,match='No released upload'):reel.latest()
    assert not (tmp_path/'jobs').exists()

def test_delayed_feed_uses_only_selected_channel_videos(monkeypatch,tmp_path):
    monkeypatch.setattr(reel,'STATE',tmp_path)
    channel='UC'+'a'*22
    reel.save(tmp_path/'connection.json',{'channel_id':channel})
    data={'contents':{'twoColumnBrowseResultsRenderer':{'tabs':[
        {'tabRenderer':{'selected':False,'content':{'videoRenderer':{'videoId':'unrelated01'}}}},
        {'tabRenderer':{'selected':True,'content':{'items':[
            {'videoRenderer':{'videoId':'scheduled01','upcomingEventData':{'startTime':'9999999999'}}},
            {'lockupViewModel':{'contentId':'NgVy8Yjtexs','contentType':'LOCKUP_CONTENT_TYPE_VIDEO'}},
            {'videoRenderer':{'videoId':'olderclip01'}}
        ]}}}
    ]}}}
    class Response:
        content=b'<feed xmlns="http://www.w3.org/2005/Atom"/>'
        text='var ytInitialData = '+json.dumps(data)+';'
        def raise_for_status(self):pass
    calls=[]
    def get(url,**kwargs):
        calls.append((url,kwargs))
        return Response()
    monkeypatch.setattr(reel.httpx,'get',get)
    assert reel.latest()==('NgVy8Yjtexs',channel)
    assert calls[1][0]==f'https://www.youtube.com/channel/{channel}/videos'
    assert all(kwargs['headers']['Cache-Control']=='no-cache' for _,kwargs in calls)

def test_approval_and_publication_retries_use_same_post(monkeypatch,tmp_path):
    monkeypatch.setattr(reel,'STATE',tmp_path)
    monkeypatch.setattr(reel.settings,'zernio_instagram_id','account-1')
    video=tmp_path/'reel.mp4';video.write_bytes(b'media-test-fixture')
    path=reel.job_path('testvideo01')
    reel.save(path,{'id':'testvideo01','status':'Needs approval','video':str(video),'render_sha256':reel.digest(video),'caption':'Story','checks':[{'status':'pass'}]})
    with pytest.raises(ValueError,match='confirmed'):reel.publish('testvideo01')
    calls=[];post_checks=0
    def request(method,path,**kwargs):
        nonlocal post_checks
        calls.append((method,path,kwargs.get('key')))
        if path=='/media/presign':return {'uploadUrl':'https://storage.example/upload','publicUrl':'https://media.example/reel.mp4'}
        if method=='POST':return {'postId':'saved-provider-post'}
        post_checks+=1
        platform={'platform':'instagram','accountId':'account-1','status':'pending'}
        if post_checks>=2:platform.update(status='published',platformPostId='instagram-post',platformPostUrl='https://instagram.com/reel/example')
        return {'post':{'platforms':[platform]}}
    class Response:
        def raise_for_status(self):pass
    monkeypatch.setattr(reel.publishing,'request',request)
    monkeypatch.setattr(reel.httpx,'put',lambda *a,**k:Response())
    assert reel.publish('testvideo01',True)['status']=='Publishing'
    assert reel.publish('testvideo01',True)['post_id']=='instagram-post'
    assert reel.publish('testvideo01',True)['post_id']=='instagram-post'
    assert sum(method=='POST' and path=='/posts' for method,path,_ in calls)==1
    assert sum(path=='/media/presign' for _,path,_ in calls)==1

def test_changed_render_cannot_use_old_approval(monkeypatch,tmp_path):
    monkeypatch.setattr(reel,'STATE',tmp_path)
    video=tmp_path/'reel.mp4';video.write_bytes(b'changed')
    reel.save(reel.job_path('testvideo01'),{'status':'Needs approval','video':str(video),'render_sha256':'old-hash','checks':[{'status':'pass'}]})
    with pytest.raises(ValueError,match='Video changed'):reel.publish('testvideo01',True)

def test_editing_code_change_invalidates_cached_preview(monkeypatch,tmp_path):
    monkeypatch.setattr(reel,'STATE',tmp_path)
    monkeypatch.setattr(reel,'engine_version',lambda:'new-engine')
    path=reel.job_path('testvideo01')
    reel.save(path,{'id':'testvideo01','status':'Needs approval','engine_version':'old-engine'})
    job=reel.analyze(url='https://youtu.be/testvideo01')
    assert job['status']=='Awaiting Codex update'
    assert reel.read(path)['status']=='Awaiting Codex update'

def test_engine_version_changes_with_code_but_not_job_state(monkeypatch,tmp_path):
    monkeypatch.setattr(reel,'ROOT',tmp_path)
    (tmp_path/'reel_engine').mkdir();(tmp_path/'reel.py').write_text('cli')
    engine=tmp_path/'reel_engine/render.py';engine.write_text('renderer-v1')
    first=reel.engine_version()
    (tmp_path/'job.json').write_text('progress update')
    assert reel.engine_version()==first
    engine.write_text('renderer-v2')
    assert reel.engine_version()!=first
