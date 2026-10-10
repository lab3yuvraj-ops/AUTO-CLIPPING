import hashlib
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse, parse_qs
import httpx
from defusedxml import ElementTree


from .config import settings

from .errors import StageError,ActionRequired
from .style import approved_config


def video_id(url):
    parsed = urlparse(url)
    if parsed.scheme != 'https' or parsed.username or parsed.port:
        raise ValueError('Use a public https://youtube.com or https://youtu.be video URL.')
    host = (parsed.hostname or '').lower()
    if host == 'youtu.be':
        value = parsed.path.strip('/')
    elif host in ('youtube.com', 'www.youtube.com', 'm.youtube.com'):
        value = parse_qs(parsed.query).get('v', [''])[0] if parsed.path == '/watch' else parsed.path.split('/')[-1] if parsed.path.startswith(('/shorts/', '/live/')) else ''
    else:
        value = ''
    if not re.fullmatch(r'[A-Za-z0-9_-]{11}', value):
        raise ValueError('Enter a single YouTube video URL, not a channel or playlist.')
    return value


def ytdlp(args, timeout=180):
    if settings.youtube_cookie_file and not Path(settings.youtube_cookie_file).is_file():
        raise ActionRequired('The configured YouTube cookie file does not exist. Correct YOUTUBE_COOKIE_FILE, restart the worker, then retry this stage.')
    extra=['--cookies',settings.youtube_cookie_file] if settings.youtube_cookie_file else []
    result = subprocess.run([sys.executable, '-m', 'yt_dlp', '--ignore-config', '--compat-options','no-certifi','--js-runtimes','node', '--no-playlist', '--no-warnings', '--socket-timeout', '30', *extra, *args], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=timeout)
    if result.returncode:
        # Do not persist URLs/cookies or signed stream query strings from provider output.
        reason = 'YouTube download failed. The video may be unavailable, still processing, or YouTube may require a supported JS runtime / network verification. See operator setup.'
        if 'not a bot' in result.stderr:
            raise ActionRequired('YouTube requires verification for this worker. Automatic retries are stopped. Configure an authorized YouTube cookie file in YOUTUBE_COOKIE_FILE and restart the worker, or use a worker network that YouTube permits. Then retry the saved download stage. A YouTube Data API key cannot resolve this challenge.')
        if '429' in result.stderr:
            error=StageError('YouTube rate-limited this worker (HTTP 429). Waiting 30 minutes before a limited retry. Repeated rate limits require operator attention.',delay=1800)
            error.max_attempts=3
            raise error
        elif 'CERTIFICATE_VERIFY_FAILED' in result.stderr:
            raise ActionRequired('YouTube HTTPS certificate verification failed. Configure the worker trust store, restart it, and retry the saved stage.')
        raise StageError(reason, delay=300)
    return result.stdout


def download(job, root):
    url = f'https://www.youtube.com/watch?v={job.video_id}'
    info = json.loads(ytdlp(['--dump-single-json', '--skip-download', url]))
    if info.get('is_live') or info.get('live_status') in ('is_upcoming', 'is_live', 'post_live'):
        raise StageError('Waiting for the scheduled/live video to finish and become a processed public upload.', delay=1800)
    if info.get('availability') not in (None, 'public'):
        raise StageError('Video is not public. Make it public, then retry.', False)
    if not info.get('duration') or info['duration'] > settings.max_source_seconds:
        raise StageError(f'Video is missing a duration or exceeds the {settings.max_source_seconds // 60}-minute source limit.', False)
    if job.config.get('channel_id') and (job.config.get('from_monitor') or job.config.get('verify_channel')) and info.get('channel_id') != job.config['channel_id']:
        raise StageError('Notification channel does not match the video owner.', False)
    if job.config.get('from_monitor') and (info.get('release_timestamp') or info.get('timestamp') or time.time()) < job.config.get('monitor_since',0):
        raise StageError('This upload predates channel monitoring. A title/description update does not make it a new upload. Use manual input to process it.',False)
    height = max((f.get('height') or 0 for f in info.get('formats', []) if f.get('vcodec') != 'none'), default=0)
    if height < job.config.get('min_source_height', settings.min_source_height):
        waiting = time.time() - job.created < settings.quality_wait_hours * 3600
        raise StageError(f'Only {height}p is available; waiting for the configured source quality. Lower the quality floor explicitly if this is the original resolution.', waiting, 1800)
    root.mkdir(parents=True, exist_ok=True)
    ytdlp(['-f', 'bv*+ba/b', '--merge-output-format', 'mkv', '--remux-video', 'mkv', '--retries', '3', '--fragment-retries', '3', '--max-filesize', '12G', '-o', str(root / 'source.%(ext)s'), url], timeout=14400)
    path = root / 'source.mkv'
    if not path.exists():
        raise StageError('Download completed without the expected source file.')
    metadata = {k: info.get(k) for k in ['id','title','duration','channel_id','upload_date','width','height','fps']}
    metadata['best_available_height'] = height
    (root / 'source.json').write_text(json.dumps(metadata, ensure_ascii=False), encoding='utf-8')
    return {'source': str(path.resolve()), 'metadata': metadata}


def topic(channel):
    return f'https://www.youtube.com/feeds/videos.xml?channel_id={channel}'


def feed_ids(xml):
    root = ElementTree.fromstring(xml)
    return [(e.findtext('{http://www.youtube.com/xml/schemas/2015}videoId'), e.findtext('{http://www.youtube.com/xml/schemas/2015}channelId')) for e in root.findall('{http://www.w3.org/2005/Atom}entry')]


def feed_published(xml):
    from datetime import datetime
    root=ElementTree.fromstring(xml)
    result={}
    for e in root.findall('{http://www.w3.org/2005/Atom}entry'):
        stamp=e.findtext('{http://www.w3.org/2005/Atom}published')
        vid=e.findtext('{http://www.youtube.com/xml/schemas/2015}videoId')
        if stamp and vid:
            result[vid]=datetime.fromisoformat(stamp.replace('Z','+00:00')).timestamp()
    return result


