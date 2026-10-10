"""One source-to-output time map drives audio, video, captions and framing."""
import re
import subprocess


def silence_intervals(source):
    r = subprocess.run(['ffmpeg','-hide_banner','-nostats','-i',str(source),'-vn','-af','silencedetect=noise=-38dB:d=0.8','-f','null','-'], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=7200)
    if r.returncode:
        raise RuntimeError('Silence analysis failed.')
    starts = [float(x) for x in re.findall(r'silence_start: ([\d.]+)',r.stderr)]
    ends = [float(x) for x in re.findall(r'silence_end: ([\d.]+)',r.stderr)]
    return list(zip(starts,ends))


def build_edit(candidate, words, silences):
    start,end = candidate['start'],candidate['end']
    protected = candidate.get('preserve_pauses',[])
    removals = []
    selected = [w for w in words if start <= w['start'] and w['end'] <= end]
    # Only remove the middle of acoustically silent AND transcript-free pauses.
    for a,b in silences:
        a,b = max(a,start)+.18,min(b,end)-.22
        if b-a < .7 or any(a < y and b > x for x,y in protected):
            continue
        if any(a < w['end']+.12 and b > w['start']-.12 for w in selected):
            continue
        removals.append((a,b))
    for first,last in candidate.get('remove_word_ranges',[]):
        # False starts require user review and preserve word margins at neighboring speech.
        if not candidate['first_word'] < first <= last < candidate['last_word']:
            continue
        a,b = words[first]['start']-.08,words[last]['end']+.08
        if a <= words[first-1]['end']+.06 or b >= words[last+1]['start']-.06:
            continue
        if any(a < y and b > x for x,y in protected):
            continue
        removals.append((a,b))
    merged=[]
    for a,b in sorted(removals):
        if merged and a <= merged[-1][1]:
            merged[-1]=(merged[-1][0],max(b,merged[-1][1]))
        else:
            merged.append((a,b))
    segments=[]
    cursor=start
    output=0.0
    for a,b in [*merged,(end,end)]:
        if a > cursor:
            segments.append({'source_start':cursor,'source_end':a,'output_start':output,'output_end':output+a-cursor})
            output += a-cursor
        cursor=b
    mapped=[]
    for w in selected:
        for s in segments:
            if w['start'] >= s['source_start']-1e-6 and w['end'] <= s['source_end']+1e-6:
                mapped.append({**w,'source_start':w['start'],'source_end':w['end'],'start':s['output_start']+w['start']-s['source_start'],'end':s['output_start']+w['end']-s['source_start']})
                break
    return {'segments':segments,'words':mapped,'duration':output,'removed':merged,'false_starts_removed':bool(candidate.get('remove_word_ranges'))}


def to_source(t, segments):
    for s in segments:
        if s['output_start'] <= t <= s['output_end']:
            return s['source_start']+t-s['output_start']
    return segments[-1]['source_end']


def to_output(t, segments):
    for s in segments:
        if s['source_start'] <= t <= s['source_end']:
            return s['output_start']+t-s['source_start']
    return None
