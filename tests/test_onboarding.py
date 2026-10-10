import json
import pytest
from dotenv import dotenv_values
from reel_engine import onboarding


def scaffold(root):
    (root/'templates').mkdir();(root/'templates'/'output-defaults.json').write_text(json.dumps({'outro':{'path':'assets/cta/watch-full-video.mp4','duration':4}}))
    (root/'.env.example').write_text('ZERNIO_API_KEY=\nZERNIO_INSTAGRAM_ID=\nHF_TOKEN=\n')


def test_onboarding_saves_only_own_local_credentials_and_redacts_provider_tokens(monkeypatch,tmp_path):
    scaffold(tmp_path);(tmp_path/'.env').write_text('ZERNIO_API_KEY=test-private-key\nZERNIO_INSTAGRAM_ID=account-1\nHF_TOKEN=test-model-token\n')
    calls=[]
    class Response:
        status_code=200
        def json(self):return {'accounts':[{'_id':'account-1','platform':'instagram','username':'student','isActive':True,'accessToken':'never-return-this'}]}
    def get(url,**kwargs):calls.append((url,kwargs));return Response()
    monkeypatch.setattr(onboarding.httpx,'get',get)
    result=onboarding.onboard(tmp_path,'UC'+'x'*22,lambda value:{'channel_id':value},True)
    assert result['instagram']['verified']
    serialized=json.dumps(result)+(tmp_path/'workflow'/'onboarding.json').read_text()
    assert not any(value in serialized for value in ['test-private-key','test-model-token','never-return-this'])
    assert dotenv_values(tmp_path/'.env')['HF_TOKEN']=='test-model-token'
    assert calls[0][1]['params']=={'platform':'instagram','status':'connected'}
    assert json.loads((tmp_path/'workflow'/'output-defaults.json').read_text())['outro']['duration']==4
    (tmp_path/'workflow'/'output-defaults.json').write_text('{"custom":true}')
    onboarding.initialize_defaults(tmp_path)
    assert json.loads((tmp_path/'workflow'/'output-defaults.json').read_text())=={'custom':True}


def test_invalid_provider_key_does_not_change_existing_setup(monkeypatch,tmp_path):
    scaffold(tmp_path);env=tmp_path/'.env';env.write_text('ZERNIO_API_KEY=wrong-key\nZERNIO_INSTAGRAM_ID=wrong-account\n');before=env.read_bytes()
    class Response:status_code=401
    monkeypatch.setattr(onboarding.httpx,'get',lambda *a,**k:Response())
    with pytest.raises(ValueError,match='HTTP 401'):onboarding.onboard(tmp_path,'some-channel',lambda value:pytest.fail('Must not connect after rejected key.'),True)
    assert env.read_bytes()==before and not (tmp_path/'workflow').exists()


def test_non_instagram_or_inactive_account_is_rejected(monkeypatch):
    class Response:
        status_code=200
        def json(self):return {'accounts':[{'_id':'account-1','platform':'youtube'}]}
    monkeypatch.setattr(onboarding.httpx,'get',lambda *a,**k:Response())
    with pytest.raises(ValueError,match='not available'):onboarding.verify_instagram('test-key','account-1')


def test_noninteractive_onboarding_never_falls_back_to_echoing_secrets(monkeypatch,tmp_path):
    scaffold(tmp_path)
    monkeypatch.setattr(onboarding.sys.stdin,'isatty',lambda:False)
    with pytest.raises(ValueError,match='interactive terminal'):onboarding.onboard(tmp_path,'some-channel',lambda _:None)
