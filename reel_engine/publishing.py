import time
import httpx
from .config import settings
from .errors import StageError,PublishUncertain
BASE="https://zernio.com/api/v1"

def request(method,path,*,payload=None,params=None,key=None):
    if not settings.zernio_api_key:
        raise StageError('Set ZERNIO_API_KEY in the private .env to publish to Instagram.',False)
    headers={'Authorization':'Bearer '+settings.zernio_api_key}
    if key:
        headers['Idempotency-Key']=key
    try:
        with httpx.Client(timeout=180) as client:
            response=client.request(method,BASE+path,headers=headers,json=payload,params=params)
    except httpx.TransportError as error:
        raise StageError('Zernio network request failed. Saved publishing requests retry with the original idempotency key.',True,60) from error
    if not response.is_success:
        try:
            data=response.json()
        except ValueError:
            data={}
        if response.status_code==409 and data.get('existingPostId'):
            return {'postId':str(data['existingPostId'])}
        if response.status_code==409 and data.get('details',{}).get('existingProfileId'):
            return {'profile':{'_id':data['details']['existingProfileId']}}
        retry=response.status_code in (429,500,502,503,504) or data.get('code')=='idempotency_conflict'
        detail='Check the Zernio key.' if response.status_code==401 else 'Reconnect Instagram or check Zernio permissions/plan.' if response.status_code in (402,403) else 'Check media limits and account configuration.'
        raise StageError(f'Zernio returned HTTP {response.status_code}. {detail}',retry,120)
    return response.json()


