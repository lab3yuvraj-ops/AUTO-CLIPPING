"""Inspect source context, exact camera geometry and caption wording before encoding."""
import json
import math
import textwrap
import time
from pathlib import Path
import cv2
from PIL import Image, ImageDraw, ImageFont
from .render import edit_source,plan_camera,camera_frame
from .tracking import crop_centers,fill_missing_centers
from .timeline import to_source,to_output
from .captions import make_ass,FONTS


def make_review(source,edit,tracking,root):
    started=time.perf_counter();root=Path(root);out=root/'review';out.mkdir(exist_ok=True)
    reused=edit_source(source,edit,root/'edited.mkv')
    cap=cv2.VideoCapture(str(root/'edited.mkv'));fps=30
    count=math.floor(edit['duration']*fps)
    times=[to_source(i/fps,edit['segments']) for i in range(count)]
    words=[{**w,'start':w['source_start'],'end':w['source_end']} for w in edit['words']]
    centers=fill_missing_centers(crop_centers(tracking,words,times),tracking,times)
    camera,_,anchored=plan_camera(cap,tracking,centers,times,fps)
    events=make_ass(edit['words'],out/'captions.ass','Creepster',1420)
    points={.3,edit['duration']-.3}
    for target in tracking.get('visual_targets',[]):
        for stamp in [target['start']+.2,(target['start']+target['end'])/2,target['end']-.2]:
            mapped=to_output(stamp,edit['segments'])
            if mapped is not None:points.add(mapped)
    points=sorted({round(t*fps)/fps for t in points if 0<=t<count/fps})
    font=ImageFont.truetype(str(Path(__file__).resolve().parents[1]/'assets'/FONTS['Creepster']),14)
    pages=[];samples=[]
    for page_start in range(0,len(points),8):
        sheet=Image.new('RGB',(1440,4*424),(22,26,24));draw=ImageDraw.Draw(sheet)
        for tile,t in enumerate(points[page_start:page_start+8]):
            n=min(count-1,round(t*fps));cap.set(cv2.CAP_PROP_POS_FRAMES,n);ok,frame=cap.read()
            if not ok:raise RuntimeError('Missing review frame.')
            geo=camera[n];crop=camera_frame(frame,geo)
            x=(tile%2)*720;y=(tile//2)*424
            draw.text((x+8,y+6),f'Output {t:.2f}s | source {times[n]:.2f}s',fill='white')
            full=Image.fromarray(cv2.cvtColor(frame,cv2.COLOR_BGR2RGB)).resize((420,236))
            portrait=Image.fromarray(cv2.cvtColor(crop,cv2.COLOR_BGR2RGB)).resize((216,384))
            sheet.paste(full,(x+8,y+32));sheet.paste(portrait,(x+448,y+32))
            cx,cy,ch=geo;cw=ch*frame.shape[0]/frame.shape[1]*9/16
            draw.rectangle((x+8+(cx-cw/2)*420,y+32+(cy-ch/2)*236,
                x+8+(cx+cw/2)*420,y+32+(cy+ch/2)*236),outline='yellow',width=2)
            event=next((e for e in events if e['start']<=t<e['end']),None)
            if event:
                labels=event['display_text'].split();active={w['roman'].upper() for w in edit['words'] if w['id'] in event['active_ids']}
                widths=[draw.textlength(label+' ',font=font) for label in labels]
                px=x+448+500/1080*216-sum(widths)/2;py=y+32+1420/1920*384-7
                for label,width in zip(labels,widths):
                    draw.text((px+1,py+1),label,font=font,fill='black',stroke_width=2,stroke_fill='black')
                    draw.text((px,py),label,font=font,fill=(255,51,51) if label in active else 'white',stroke_width=1,stroke_fill='black');px+=width
            nearby=' '.join(w['roman'] for w in edit['words'] if t-1<=w['end'] and w['start']<=t+2)
            for line_i,line in enumerate(textwrap.wrap(nearby,62)[:5]):draw.text((x+8,y+284+line_i*18),line,fill='white')
            samples.append({'output':t,'source':times[n],'camera':geo,'roman_context':nearby})
        destination=out/f'page-{page_start//8+1:02}.jpg';sheet.save(destination,quality=94);pages.append(str(destination.resolve()))
    cap.release()
    report={'pages':pages,'samples':samples,'seconds':time.perf_counter()-started,'lossless_edit_reused':reused,
            'anchor_only_planning':anchored,'note':'Caption thumbnails approximate ASS styling; final encoding still burns the original ASS. No publication approval or validated final video is created by review.'}
    (out/'review.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    return {k:v for k,v in report.items() if k!='samples'} | {'sample_count':len(samples)}
