from pathlib import Path
from PIL import ImageFont

FONTS = {'Creepster': 'Creepster-Regular.ttf', 'Bebas Neue': 'BebasNeue-Regular.ttf'}


def ass_time(t):
    ticks = max(0,round(t*100))
    return f'{ticks//360000}:{ticks//6000%60:02}:{ticks//100%60:02}.{ticks%100:02}'


def safe_text(text):
    return text.replace('\\','').replace('{','').replace('}','').replace('\n',' ')


def make_ass(words, path, font='Creepster', y=1420, positions=None):
    positions=positions or []
    if any(not 400<=p['y']<=1500 or not 0<=p['start']<p['end'] for p in positions):
        raise ValueError('Invalid caption placement interval.')
    font_path = Path(__file__).resolve().parent.parent / 'assets' / FONTS[font]
    metrics = ImageFont.truetype(str(font_path),72)
    phrases=[]
    chunk=[]
    for w in words:
        proposed=' '.join(v['roman'] for v in [*chunk,w]).upper()
        if len(w['roman'].split())>2:
            raise ValueError('A Roman caption group contains more than two words. Review its audio alignment before rendering.')
        if chunk and (len(proposed)>30 or len(proposed.split())>2 or w['start']-chunk[-1]['end']>.65 or w['speaker']!=chunk[-1]['speaker']):
            phrases.append(chunk)
            chunk=[]
        chunk.append(w)
    if chunk:
        phrases.append(chunk)
    header=f'''[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Main,{font},72,&H00FFFFFF,&H00FFFFFF,&H00000000,&H90000000,-1,0,0,0,100,100,1,0,1,6,3,5,100,180,350,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
'''
    events=[]
    manifest=[]
    for phrase in phrases:
        labels=[safe_text(w['roman']).upper() for w in phrase]
        lines=[[]]
        for i,label in enumerate(labels):
            if lines[-1] and metrics.getlength(' '.join(labels[j] for j in lines[-1]+[i]))>760:
                lines.append([])
            lines[-1].append(i)
        if len(lines)>2 or any(metrics.getlength(labels[i])>760 for i in range(len(labels))):
            raise ValueError('Caption group is too wide. Shorten the Roman text in the review editor.')
        boundaries=sorted(set([v for w in phrase for v in (w['start'],w['end'])]))
        boundaries=sorted(set(boundaries+[v for p in positions for v in (p['start'],p['end'])
                                          if boundaries[0]<v<boundaries[-1]]))
        for a,b in zip(boundaries,boundaries[1:]):
            if b-a<.005:
                continue
            active=[i for i,w in enumerate(phrase) if w['start'] <= (a+b)/2 < w['end']]
            # Overlap is held for review; never paint two groups red simultaneously.
            active=active[:1]
            text='\\N'.join(' '.join(('{\\c&H003333FF&}' if i in active else '{\\c&H00FFFFFF&}')+labels[i]+'{\\c&H00FFFFFF&}' for i in line) for line in lines)
            caption_y=next((p['y'] for p in positions if p['start']<=(a+b)/2<p['end']),y)
            events.append(f'Dialogue: 0,{ass_time(a)},{ass_time(b)},Main,,0,0,0,,{{\\pos(500,{caption_y})}}{text}')
            manifest.append({'start':a,'end':b,'active_ids':[phrase[i]['id'] for i in active],'display_text':' '.join(labels),'y':caption_y})
    path.write_text(header+'\n'.join(events)+'\n',encoding='utf-8-sig')
    return manifest
