import importlib.util
import json
import math
import os
import hashlib
import time
import httpx
import subprocess
from functools import lru_cache
from pathlib import Path
from .config import settings
from .errors import StageError

_DLL_HANDLES=[]

@lru_cache(maxsize=2)
def load_whisper(allow_download=False):
    os.environ['HF_HUB_OFFLINE']='0' if allow_download else '1'
    if settings.local_device=='cuda':
        import torch
        if not torch.cuda.is_available():raise StageError('GPU speech runtime is unavailable; use the saved CPU environment.',False)
        if os.name=='nt':
            libs=Path(torch.__file__).parent/'lib'
            _DLL_HANDLES.append(os.add_dll_directory(str(libs)))
            os.environ['PATH']=str(libs)+os.pathsep+os.environ.get('PATH','')
    from faster_whisper import WhisperModel
    return WhisperModel(settings.whisper_model,device=settings.local_device,compute_type=settings.local_compute_type,
        download_root=str(settings.local_model_dir/'whisper'),local_files_only=not allow_download)


def recheck_local(root,ranges):
    """Check uncertain passages with one model load; leave full transcript intact."""
    import soundfile
    root=Path(root);audio=root/'local-audio.wav'
    samples,rate=soundfile.read(str(audio),dtype='float32')
    if rate!=16000 or samples.ndim!=1:raise ValueError('Recheck requires the extracted mono 16kHz audio.')
    if any(not 0<=a<b<=len(samples)/rate for a,b in ranges):raise ValueError('Recheck range is outside the audio.')
    out=root/'rechecks';out.mkdir(exist_ok=True);results=[];model=None
    fingerprint=hashlib.sha256(audio.read_bytes()).hexdigest()
    for a,b in ranges:
        signature=hashlib.sha256(json.dumps([fingerprint,a,b,settings.whisper_model,settings.local_device,settings.local_compute_type]).encode()).hexdigest()
        path=out/(signature+'.json')
        if path.exists():results.append(json.loads(path.read_text(encoding='utf-8')) | {'cache_reused':True});continue
        if model is None:model=load_whisper()
        started=time.perf_counter()
        segments,_=model.transcribe(samples[round(a*rate):round(b*rate)],language='hi',task='transcribe',word_timestamps=True,vad_filter=False,beam_size=5,condition_on_previous_text=False)
        words=[{'start':float(w.start+a),'end':float(w.end+a),'text':w.word.strip(),'confidence':float(w.probability)} for s in segments for w in s.words or [] if w.word.strip()]
        result={'range':[a,b],'words':words,'seconds':time.perf_counter()-started,'model':settings.whisper_model,'device':settings.local_device,'cache_reused':False}
        temporary=path.with_suffix('.tmp');temporary.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');temporary.replace(path);results.append(result)
    return {'rechecks':results,'note':'Alternate ASR evidence; results do not silently replace approved wording.'}


def readiness():
    missing=[name for name in ('faster_whisper','pyannote.audio','torch','soundfile') if not module_available(name)]
    return {'ready':not missing and (bool(settings.hf_token) or Path(settings.diarization_model).exists()),'missing_packages':missing,'model_access_configured':bool(settings.hf_token) or Path(settings.diarization_model).exists(),'provider':'local','device':settings.local_device,'whisper_model':settings.whisper_model}


def module_available(name):
    try:
        return importlib.util.find_spec(name) is not None
    except (ModuleNotFoundError,ValueError):
        return False


@lru_cache(maxsize=2)
def load_models(allow_download=False):
    status=readiness()
    if status['missing_packages']:
        raise StageError('Install requirements-local.txt in the worker environment. Missing local speech packages: '+', '.join(status['missing_packages']),False)
    if not status['model_access_configured']:
        raise StageError('Set HF_TOKEN after accepting pyannote Community-1 model terms, or configure DIARIZATION_MODEL to an approved downloaded local model directory.',False)
    if allow_download and settings.diarization_model=='pyannote/speaker-diarization-community-1':
        try:
            with httpx.Client(timeout=30) as client:
                response=client.head('https://huggingface.co/pyannote/speaker-diarization-community-1/resolve/main/config.yaml',headers={'Authorization':'Bearer '+settings.hf_token})
            if response.status_code in (401,403):
                raise StageError(f'Hugging Face refused speaker-model access (HTTP {response.status_code}). Accept Community-1 access conditions on your Hugging Face account and ensure HF_TOKEN has read access to the approved gated repository.',False)
            if response.status_code>=400:
                raise StageError(f'Speaker-model access check returned HTTP {response.status_code}. Try model preparation again after resolving provider access.',False)
        except httpx.TransportError as error:
            raise StageError('Could not verify speaker-model download access. Check HTTPS trust and network connectivity.',False) from error
    os.environ['PYANNOTE_METRICS_ENABLED']='false'
    if settings.hf_token:
        os.environ['HF_TOKEN']=settings.hf_token
    os.environ['HF_HUB_OFFLINE']='0' if allow_download else '1'
    os.environ['HF_HUB_DISABLE_XET']='1'
    os.environ['HF_HUB_DOWNLOAD_TIMEOUT']='120'
    os.environ['HF_HUB_ETAG_TIMEOUT']='30'
    from huggingface_hub import constants
    constants.HF_HUB_OFFLINE=not allow_download
    constants.HF_HUB_DISABLE_XET=True
    from faster_whisper import WhisperModel
    from pyannote.audio import Pipeline
    import torch
    if settings.local_device=='cuda' and not torch.cuda.is_available():
        raise StageError('LOCAL_DEVICE=cuda requires a supported NVIDIA GPU and matching CUDA runtime. Use cpu/int8 otherwise.',False)
    settings.local_model_dir.mkdir(parents=True,exist_ok=True)
    try:
        whisper=load_whisper(allow_download)
        pipeline=Pipeline.from_pretrained(settings.diarization_model,token=settings.hf_token or None,cache_dir=str(settings.local_model_dir/'pyannote'))
        pipeline.to(torch.device(settings.local_device))
    except Exception as error:
        raise StageError('Local speech models could not load. Run reel.py prepare-models --download after accepting model terms and setting HF_TOKEN. Later runs use cached models offline. Check disk space and CPU/CUDA compatibility.',False) from error
    return whisper,pipeline


def assign_words(words,turns):
    output=[]
    for word in words:
        start,end=float(word['start']),float(word['end'])
        if not math.isfinite(start) or not math.isfinite(end) or end<=start:
            continue
        scores={}
        for turn in turns:
            overlap=max(0,min(end,turn['end'])-max(start,turn['start']))
            if overlap:
                scores[turn['speaker']]=scores.get(turn['speaker'],0)+overlap
        ranked=sorted(scores.items(),key=lambda item:item[1],reverse=True)
        best=ranked[0] if ranked else ('UNKNOWN',0)
        uncertain=best[1]/(end-start)<.5 or (len(ranked)>1 and ranked[1][1]>.25*(end-start))
        output.append({**word,'id':len(output),'speaker':best[0] if not uncertain else 'UNKNOWN','speaker_uncertain':uncertain,'overlapping_speech':len(ranked)>1,'speaker_coverage':min(1,best[1]/(end-start))})
    return output


def transcribe_local(source,root):
    started=time.perf_counter();timings={}
    transcript=root/'transcript.json'
    if transcript.exists():
        return {'transcript':str(transcript.resolve()),'transcription_timings':{'checkpoint_reused':True,'seconds_this_run':time.perf_counter()-started}}
    whisper,pipeline=load_models()
    timings['model_load_seconds']=time.perf_counter()-started
    stage_started=time.perf_counter()
    audio=root/'local-audio.wav'
    if not audio.exists():
        result=subprocess.run(['ffmpeg','-v','error','-y','-i',str(source),'-vn','-ar','16000','-ac','1','-c:a','pcm_s16le',str(audio)],capture_output=True,timeout=7200)
        if result.returncode:
            raise StageError('Could not extract source audio for local transcription.',False)
    timings['audio_extract_seconds']=time.perf_counter()-stage_started
    stage_started=time.perf_counter();asr_path=root/'local-asr.json'
    if asr_path.exists():
        asr=json.loads(asr_path.read_text(encoding='utf-8'))
    else:
        segments,info=whisper.transcribe(str(audio),language='hi',task='transcribe',word_timestamps=True,vad_filter=True,beam_size=5,condition_on_previous_text=True)
        words=[]
        for segment in segments:
            for word in segment.words or []:
                if word.word.strip():
                    words.append({'start':word.start,'end':word.end,'text':word.word.strip(),'confidence':word.probability})
        asr={'words':words,'language':info.language}
        asr_path.write_text(json.dumps(asr,ensure_ascii=False),encoding='utf-8')
    timings['asr_seconds']=time.perf_counter()-stage_started
    if not asr['words']:
        raise StageError('Local transcription detected no speech. Verify the source audio.',False)
    stage_started=time.perf_counter();diar_path=root/'speaker-turns.json'
    if diar_path.exists():
        turns=json.loads(diar_path.read_text(encoding='utf-8'))
    else:
        import soundfile
        import torch
        samples,sample_rate=soundfile.read(str(audio),dtype='float32',always_2d=True)
        result=pipeline({'waveform':torch.from_numpy(samples.T.copy()),'sample_rate':sample_rate})
        annotation=getattr(result,'speaker_diarization',result)
        turns=[{'start':turn.start,'end':turn.end,'speaker':speaker} for turn,_,speaker in annotation.itertracks(yield_label=True)]
        diar_path.write_text(json.dumps(turns),encoding='utf-8')
    timings['diarization_seconds']=time.perf_counter()-stage_started
    timings['seconds_this_run']=time.perf_counter()-started
    words=assign_words(asr['words'],turns)
    data={'words':words,'text':' '.join(word['text'] for word in words),'language':asr['language'],'provider':'local','models':{'transcription':settings.whisper_model,'diarization':settings.diarization_model},'speaker_turns':turns,'uncertain_words':sum(word['speaker_uncertain'] for word in words)}
    data['timings']=timings;data['device']=settings.local_device
    transcript.write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8')
    return {'transcript':str(transcript.resolve()),'transcription_timings':timings}
