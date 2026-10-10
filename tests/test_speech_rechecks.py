from types import SimpleNamespace
import numpy as np
import soundfile
import pytest
from reel_engine import local_transcription as speech


def test_batch_checks_load_one_model_and_invalidate_when_audio_changes(monkeypatch,tmp_path):
    soundfile.write(tmp_path/'local-audio.wav',np.zeros(16000,dtype=np.float32),16000)
    loads=[];requests=[]
    class Model:
        def transcribe(self,audio,**kwargs):
            requests.append(audio.copy())
            word=SimpleNamespace(start=.1,end=.2,word='test',probability=.9)
            return iter([SimpleNamespace(words=[word])]),None
    def load():loads.append(True);return Model()
    monkeypatch.setattr(speech,'load_whisper',load)
    first=speech.recheck_local(tmp_path,[(0,.5),(.5,1)])
    assert len(loads)==1 and len(requests)==2
    assert first['rechecks'][1]['words'][0]['start']==pytest.approx(.6)
    assert all(c['cache_reused'] for c in speech.recheck_local(tmp_path,[(0,.5),(.5,1)])['rechecks'])
    assert len(requests)==2
    soundfile.write(tmp_path/'local-audio.wav',np.ones(16000,dtype=np.float32)*.2,16000)
    speech.recheck_local(tmp_path,[(0,.5)])
    assert len(requests)==3
    with pytest.raises(ValueError,match='outside'):speech.recheck_local(tmp_path,[(0,2)])
