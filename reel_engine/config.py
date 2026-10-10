from pathlib import Path
import os
from pydantic_settings import BaseSettings,SettingsConfigDict

ROOT=Path(__file__).resolve().parents[1]
class Settings(BaseSettings):
    model_config=SettingsConfigDict(env_file=ROOT/'.env',extra='ignore')
    whisper_model:str='small'
    local_device:str='cpu'
    local_compute_type:str='int8'
    hf_token:str=''
    diarization_model:str='pyannote/speaker-diarization-community-1'
    local_model_dir:Path=ROOT/'data/models'
    youtube_cookie_file:str=''
    youtube_api_key:str=''
    min_source_height:int=1080
    quality_wait_hours:int=24
    max_source_seconds:int=7200
    zernio_api_key:str=''
    zernio_instagram_id:str=''

settings=Settings()
trust=ROOT/'.venv/ca.pem'
if trust.exists():os.environ.setdefault('SSL_CERT_FILE',str(trust))
