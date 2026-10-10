"""Configure a student's own local checkout without sharing credentials."""
import getpass
import json
import os
import shutil
import sys
from pathlib import Path
import httpx
from dotenv import dotenv_values,set_key
from .publishing import BASE


def initialize_defaults(root):
    root=Path(root);workflow=root/'workflow';workflow.mkdir(exist_ok=True)
    destination=workflow/'output-defaults.json'
    if not destination.exists():
        shutil.copy2(root/'templates'/'output-defaults.json',destination)


def verify_instagram(key,account_id):
    if not key or not account_id:raise ValueError('Set ZERNIO_API_KEY and ZERNIO_INSTAGRAM_ID in your private .env.')
    if any(c in key+account_id for c in '\r\n'):raise ValueError('Credentials must not contain line breaks.')
    try:
        response=httpx.get(BASE+'/accounts',headers={'Authorization':'Bearer '+key},params={'platform':'instagram','status':'connected'},timeout=30)
    except httpx.TransportError:
        raise ValueError('Could not reach Zernio. Check your network, then retry onboarding.') from None
    if response.status_code!=200:
        raise ValueError(f'Zernio account verification returned HTTP {response.status_code}. Check your key and account access.')
    try:accounts=response.json()['accounts']
    except (ValueError,KeyError,TypeError):raise ValueError('Zernio returned an unexpected account response.') from None
    account=next((a for a in accounts if isinstance(a,dict) and str(a.get('_id'))==account_id and a.get('platform')=='instagram'),None)
    if not account:raise ValueError('That Instagram account is not available to this Zernio key. Use its Zernio connected account ID, not an Instagram username or numeric Instagram user ID.')
    if account.get('isActive') is False:raise ValueError('Reconnect this Instagram account in Zernio before proceeding.')
    # Never return OAuth tokens or the complete provider response.
    return {'account_id':account_id,'platform':'instagram','username':account.get('username'),'verified':True}


def onboard(root,channel,connect,from_env=False):
    root=Path(root);env=root/'.env'
    current=dotenv_values(env) if env.exists() else {}
    if from_env:
        key=current.get('ZERNIO_API_KEY','');account_id=current.get('ZERNIO_INSTAGRAM_ID','')
    else:
        if not sys.stdin.isatty():raise ValueError('Hidden prompts require an interactive terminal. Enter credentials privately in .env and use --from-env.')
        key=getpass.getpass('Zernio API key (hidden; Enter keeps an existing local key): ').strip() or current.get('ZERNIO_API_KEY','')
        account_id=input('Zernio connected Instagram account ID: ').strip() or current.get('ZERNIO_INSTAGRAM_ID','')
    account=verify_instagram(key,account_id)
    # Resolve the channel before committing credentials; failed verification
    # never replaces a working local setup.
    connection=connect(channel)
    if not env.exists():shutil.copy2(root/'.env.example',env)
    for name,value in [('ZERNIO_API_KEY',key),('ZERNIO_INSTAGRAM_ID',account_id)]:set_key(str(env),name,value,quote_mode='always')
    if os.name!='nt':env.chmod(0o600)
    initialize_defaults(root)
    result={'youtube_channel_id':connection['channel_id'],'instagram':account,'credentials_saved_locally':True,
            'next_step':'Prepare cached local models once, then say YouTube analyze in Codex. No post was created.'}
    target=root/'workflow'/'onboarding.json';temporary=target.with_suffix('.tmp')
    temporary.write_text(json.dumps(result,indent=2),encoding='utf-8');temporary.replace(target)
    return result
