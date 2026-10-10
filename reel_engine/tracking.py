"""Animated-character boxes from vision, motion tracking, and cautious lip evidence.

Audio labels are NEVER interpreted as left/right. Ambiguity falls back and holds.
"""
import json
import hashlib
import bisect
import math
import cv2
import numpy as np



def jpg(frame):
    h,w=frame.shape[:2]
    if w>960:
        frame=cv2.resize(frame,(960,round(h*960/w)))
    return cv2.imencode('.jpg',frame,[cv2.IMWRITE_JPEG_QUALITY,85])[1].tobytes()


def frame_at(source,t):
    cap=cv2.VideoCapture(str(source))
    cap.set(cv2.CAP_PROP_POS_MSEC,t*1000)
    ok,frame=cap.read()
    cap.release()
    if not ok:
        raise RuntimeError('Could not decode video frame.')
    return frame


def roi(gray,box):
    h,w=gray.shape
    x,y,bw,bh=box
    return gray[max(0,int(y*h)):min(h,int((y+bh)*h)),max(0,int(x*w)):min(w,int((x+bw)*w))]


def follow(previous, current, characters):
    h,w=current.shape
    out=[]
    for c in characters:
        def hold():
            out.append({**c,'tracking_lost':True,'lost_frames':c.get('lost_frames',0)+1,
                        'mouth_motion':0,'face_motion':0})
        mask=np.zeros_like(previous)
        x,y,bw,bh=c['face']
        cv2.rectangle(mask,(int(x*w),int(y*h)),(min(w-1,int((x+bw)*w)),min(h-1,int((y+bh)*h))),255,-1)
        points=cv2.goodFeaturesToTrack(previous,maxCorners=45,qualityLevel=.02,minDistance=5,mask=mask)
        if points is None or len(points)<5:
            hold()
            continue
        nxt,status,_=cv2.calcOpticalFlowPyrLK(previous,current,points,None)
        if nxt is None or status.sum()<5:
            hold()
            continue
        shift=(nxt-points)[status.reshape(-1)==1].reshape(-1,2)
        dx,dy=np.median(shift,axis=0)/[w,h]
        if abs(dx)>.12 or abs(dy)>.12:
            hold()
            continue
        moved={**c,'tracking_lost':False,'lost_frames':0}
        for key in ['face','mouth']:
            a,b,ww,hh=c[key]
            moved[key]=[float(np.clip(a+dx,0,1-ww)),float(np.clip(b+dy,0,1-hh)),ww,hh]
        old=roi(previous,c['mouth']); new=roi(current,moved['mouth'])
        if old.size and new.size:
            # Compare aligned mouth textures, reducing evidence from whole-body movement.
            old=cv2.resize(old,(48,24)); new=cv2.resize(new,(48,24))
            moved['mouth_motion']=float(np.mean(cv2.absdiff(old,new))/255)
        else:
            moved['mouth_motion']=0
        old_face=roi(previous,c['face']);new_face=roi(current,moved['face'])
        moved['face_motion']=float(np.mean(cv2.absdiff(cv2.resize(old_face,(48,48)),cv2.resize(new_face,(48,48))))/255) if old_face.size and new_face.size else 0
        out.append(moved)
    return out


def associate(samples, words):
    assignments={}; evidence={}
    for scene in sorted(set(s['scene'] for s in samples)):
        block=[s for s in samples if s['scene']==scene]
        speakers=set(w['speaker'] for w in words if block[0]['t']<=w['end'] and w['start']<=block[-1]['t'])
        for speaker in speakers:
            if speaker=='UNKNOWN':
                assignments[f'{scene}:{speaker}']=None
                evidence[f'{scene}:{speaker}']={'confidence':'uncertain audio speaker'}
                continue
            scores={}; counts={}
            for s in block:
                active=set(w['speaker'] for w in words if w['start']<=s['t']<=w['end'])
                if active!={speaker}:
                    continue
                for c in s['characters']:
                    if c.get('tracking_lost'):continue
                    # Moving bodies and a camera pan are not lip-sync evidence.
                    scores.setdefault(c['id'],[]).append(max(0,c.get('mouth_motion',0)-c.get('face_motion',0)))
            ranked=sorted([(float(np.mean(v)),k,len(v)) for k,v in scores.items()],reverse=True)
            key=f'{scene}:{speaker}'
            if ranked:
                top,ident,n=ranked[0]
                other=ranked[1][0] if len(ranked)>1 else 0
                confident=n>=4 and top>.015 and top>max(.01,other)*1.7
                assignments[key]=ident if confident else None
                evidence[key]={'winner':ident,'motion':top,'runner_up':other,'samples':n,'confidence':'supported' if confident else 'uncertain'}
            else:
                assignments[key]=None
                evidence[key]={'confidence':'off-screen or insufficient evidence'}
    return assignments,evidence


def crop_centers(tracking, words, times):
    keyframes=tracking.get('crop_keyframes',[])
    if keyframes:
        if any(not isinstance(k.get('t'),(int,float)) or not math.isfinite(k['t'])
               or not isinstance(k.get('center'),(int,float)) or not math.isfinite(k['center'])
               or not 0<=k['center']<=1 for k in keyframes):
            raise ValueError('Invalid portrait crop keyframe.')
        keyframes=sorted(keyframes,key=lambda k:k['t'])
        stamps=[k['t'] for k in keyframes]
        output=[]
        for t in times:
            i=max(0,bisect.bisect_right(stamps,t)-1)
            a=keyframes[i]
            if i+1==len(keyframes) or keyframes[i+1].get('cut',True):
                output.append(float(a['center']))
                continue
            b=keyframes[i+1]
            u=float(np.clip((t-a['t'])/max(.000001,b['t']-a['t']),0,1))
            u=u*u*(3-2*u)
            output.append(float(a['center']+(b['center']-a['center'])*u))
        return output
    samples=tracking.get('samples',[])
    output=[]; previous_x=.5; previous_scene=-1; current_character=None; changed_at=-99
    sample_i=0
    for t in times:
        while sample_i+1<len(samples) and samples[sample_i+1]['t']<=t:
            sample_i+=1
        sample=samples[sample_i] if samples else {'characters':[],'scene':0}
        active=set(w['speaker'] for w in words if w['start']<=t<=w['end'])
        ident=tracking.get('assignments',{}).get(f"{sample['scene']}:{next(iter(active))}") if len(active)==1 else None
        if sample['scene']!=previous_scene:
            current_character=ident; previous_scene=sample['scene']; changed_at=t
        if ident and ident!=current_character:
            # Debounce short interjections: only a turn lasting >= 0.4s triggers a switch.
            speaker=next(iter(active))
            future=any(w['speaker']==speaker and w['start']<=t+.5 and w['end']>=t+.4 for w in words)
            if future:
                current_character=ident; changed_at=t
        target=next((c for c in sample['characters'] if c['id']==current_character),None)
        if len(active)>1 or (active and not ident) or target is None:
            output.append(None); continue
        x=target['face'][0]+target['face'][2]/2
        # 5 fps input, smooth center updates; rendering interpolates these samples.
        previous_x=x if sample.get('cut') else .55*previous_x+.45*x
        output.append(float(previous_x))
    return output


def fill_missing_centers(centers,tracking,times):
    """Uncertain spans hold a stable crop; quality review remains independent.

    A scene change resets the held position to its visible ensemble center.
    Never sweep across a new scene from an unrelated character position.
    """
    samples=tracking.get('samples',[])
    index=0;scene=None;held=.5;output=[]
    for center,t in zip(centers,times):
        while index+1<len(samples) and samples[index+1]['t']<=t:
            index+=1
        sample=samples[index] if samples else {'scene':0,'characters':[]}
        if sample['scene']!=scene:
            scene=sample['scene']
            faces=[c['face'][0]+c['face'][2]/2 for c in sample['characters']]
            held=float(np.median(faces)) if faces else .5
        if center is not None:
            held=float(center)
        output.append(held)
    return output
