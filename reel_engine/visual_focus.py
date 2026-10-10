"""Source-timed editorial targets: dialogue context plus visible evidence.

These targets override face following only during their evidenced interval.
Every output frame is one source crop; wide writing uses a reading pan, never an inset or rewritten OCR.
"""
import hashlib
import json
import math
import cv2
import numpy as np

from .tracking import frame_at, jpg


KINDS = {'text', 'object', 'action', 'reaction', 'character'}


def validate_targets(targets, start, end):
    if not isinstance(targets, list) or len(targets)>500:
        raise ValueError('Invalid visual targets.')
    result=[]
    for item in targets:
        box=item.get('box',[])
        values=[item.get('start'),item.get('end'),*box,item.get('confidence',0),item.get('inset_y',.12)]
        if len(box)!=4 or any(not isinstance(v,(int,float)) or not math.isfinite(v) for v in values):
            raise ValueError('Visual target coordinates and times must be finite.')
        x,y,w,h=box
        if not start<=item['start']<item['end']<=end or not (0<=x<1 and 0<=y<1 and w>0 and h>0 and x+w<=1.000001 and y+h<=1.000001):
            raise ValueError('Visual target is outside the source passage or image.')
        if item.get('kind') not in KINDS or not 0<=item.get('confidence',0)<=1 or not 0<=item.get('inset_y',.12)<=.7:
            raise ValueError('Invalid visual target kind, confidence or inset position.')
        if not str(item.get('reason','')).strip() or not str(item.get('evidence','')).strip():
            raise ValueError('Visual targets need a reason and visible evidence.')
        anchors=item.get('box_keyframes',[])
        last=-math.inf
        for anchor in anchors:
            stamp=anchor.get('t');box=anchor.get('box',[])
            if not isinstance(stamp,(int,float)) or not math.isfinite(stamp) or not item['start']<=stamp<=item['end'] or stamp<=last or len(box)!=4:
                raise ValueError('Invalid visual identity anchor time.')
            if any(not isinstance(v,(int,float)) or not math.isfinite(v) for v in box) or min(box[:2])<0 or min(box[2:])<=0 or box[0]+box[2]>1.000001 or box[1]+box[3]>1.000001:
                raise ValueError('Invalid visual identity anchor box.')
            last=stamp
        result.append(dict(item))
    return sorted(result,key=lambda item:item['start'])


def active_target(targets,t):
    eligible=[target for target in targets if target['start']<=t<target['end'] and target.get('confidence',0)>=.75]
    priority={'text':5,'object':4,'action':3,'reaction':2,'character':1}
    return max(eligible,key=lambda target:(priority[target['kind']],target['confidence']),default=None)


class TargetMotionTracker:
    """Follow texture in the selected object region; no human-face assumption.

    A failed estimate holds its last box and records a review warning. A new
    target or discontinuous source time resets tracking rather than drifting
    across a cut. This is visual motion evidence, not semantic identity proof.
    """
    def __init__(self):
        self.key=None;self.gray=None;self.box=None;self.time=None
        self.failed_frames=0;self.tracked_frames=0;self.anchored_frames=0
        self.template=None;self.misses=0;self.reacquired_frames=0

    def update(self,frame,target,t):
        if target is None:
            self.key=None;self.gray=None;self.time=None
            return None
        anchors=target.get('box_keyframes',[])
        if anchors:
            # Reviewed identity anchors constrain animated morphing and camera
            # moves. They refer to this subject, not the nearest moving texture.
            stamps=[a['t'] for a in anchors]
            box=[float(np.interp(t,stamps,[a['box'][axis] for a in anchors])) for axis in range(4)]
            self.anchored_frames+=1
            self.key=None;self.gray=None;self.time=None
            return dict(target,box=box,motion_evidence='reviewed identity anchors')
        h,w=frame.shape[:2]
        gray=cv2.cvtColor(cv2.resize(frame,(640,round(h*640/w))),cv2.COLOR_BGR2GRAY)
        key=(target['start'],target['end'],tuple(target['box']))
        if self.key!=key or self.time is None or t-self.time>.12 or t<=self.time:
            self.key=key;self.box=list(target['box']);self.gray=gray;self.time=t
            x,y,bw,bh=self.box;gh,gw=gray.shape
            self.template=gray[int(y*gh):int((y+bh)*gh),int(x*gw):int((x+bw)*gw)].copy()
            self.misses=0
            return dict(target,box=list(self.box))
        gh,gw=gray.shape;x,y,bw,bh=self.box
        mask=np.zeros_like(gray)
        mask[int(y*gh):max(int((y+bh)*gh),int(y*gh)+1),int(x*gw):max(int((x+bw)*gw),int(x*gw)+1)]=255
        points=cv2.goodFeaturesToTrack(self.gray,maxCorners=70,qualityLevel=.02,minDistance=4,mask=mask)
        accepted=False
        if points is not None and len(points)>=6:
            nxt,status,error=cv2.calcOpticalFlowPyrLK(self.gray,gray,points,None)
            if nxt is not None:
                back,back_status,_=cv2.calcOpticalFlowPyrLK(gray,self.gray,nxt,None)
                if back is not None:
                    valid=(status.ravel()==1)&(back_status.ravel()==1)&(np.linalg.norm((points-back).reshape(-1,2),axis=1)<1.5)
                    if valid.sum()>=6:
                        matrix,inliers=cv2.estimateAffinePartial2D(points[valid],nxt[valid],method=cv2.RANSAC,ransacReprojThreshold=2)
                        if matrix is not None and inliers.sum()>=6:
                            scale=float(np.linalg.norm(matrix[0,:2]))
                            # Rotation and facial deformation must not grow the
                            # bounding rectangle every frame. Trust translation
                            # from the inliers; allow only small supported scale.
                            keep=inliers.ravel().astype(bool)
                            shift=np.median((nxt[valid]-points[valid]).reshape(-1,2)[keep],axis=0)
                            scale=scale if .995<=scale<=1.005 and keep.sum()>=10 else 1.
                            cx=(x+bw/2)*gw+shift[0];cy=(y+bh/2)*gh+shift[1]
                            moved=np.array([[cx-bw*gw*scale/2,cy-bh*gh*scale/2],[cx+bw*gw*scale/2,cy+bh*gh*scale/2]])
                            lo=moved.min(axis=0)/[gw,gh];hi=moved.max(axis=0)/[gw,gh]
                            candidate=[float(lo[0]),float(lo[1]),float(hi[0]-lo[0]),float(hi[1]-lo[1])]
                            if keep.mean()>=.6 and max(abs(lo[0]-x),abs(lo[1]-y))<.04 and np.all(lo>=0) and np.all(hi<=1):
                                self.box=candidate;accepted=True
        if not accepted and self.misses>=2 and self.template is not None and min(self.template.shape)>=8 and self.template.std()>8:
            # Reacquire the SAME appearance near the held location. Ambiguous
            # peaks are rejected, rather than jumping to another character.
            pad=.12;left=max(0,int((x-pad)*gw));top=max(0,int((y-pad)*gh))
            right=min(gw,int((x+bw+pad)*gw));bottom=min(gh,int((y+bh+pad)*gh))
            region=gray[top:bottom,left:right];template=self.template
            if region.shape[0]>=template.shape[0] and region.shape[1]>=template.shape[1]:
                scores=cv2.matchTemplate(region,template,cv2.TM_CCOEFF_NORMED)
                _,score,_,location=cv2.minMaxLoc(scores)
                px,py=location;other=scores.copy();r=max(4,min(template.shape)//3)
                other[max(0,py-r):py+r+1,max(0,px-r):px+r+1]=-1
                if score>.88 and score-float(other.max())>.08:
                    self.box=[(left+px)/gw,(top+py)/gh,template.shape[1]/gw,template.shape[0]/gh]
                    accepted=True;self.reacquired_frames+=1
        if accepted:self.tracked_frames+=1;self.misses=0
        else:self.failed_frames+=1;self.misses+=1
        self.gray=gray;self.time=t
        return dict(target,box=list(self.box))


def focus_geometry(frame,center,target,ow=1080,oh=1920,source_time=None):
    """Normalized camera center and height, shared by planning and rendering."""
    h,w=frame.shape[:2]
    if target is None:
        if center is None:return None
        pw=h/w*ow/oh
        return [float(np.clip(center,pw/2,1-pw/2)),.5,1.]
    x,y,bw,bh=target['box']
    # Full-height portrait is the widest permissible edge-to-edge source crop.
    portrait_width=h/w*ow/oh
    wide=bw*1.12>portrait_width
    cx=x+bw/2
    # Never insert a second video window. Wide writing is read across the
    # primary crop, holding each end briefly rather than shrinking the scene.
    if wide and target['kind']=='text' and source_time is not None:
        progress=(source_time-target['start'])/max(.001,target['end']-target['start'])
        u=float(np.clip((progress-.15)/.7,0,1));u=u*u*(3-2*u)
        first=x+portrait_width/2-.015
        last=x+bw-portrait_width/2+.015
        cx=first+(last-first)*u
    # The approved framing spans the entire source height. Subject boxes guide
    # horizontal placement only; small faces/props must not trigger extra zoom.
    return [float(np.clip(cx,portrait_width/2,1-portrait_width/2)),.5,1.]


def camera_frame(frame,geometry,ow=1080,oh=1920):
    h,w=frame.shape[:2];cx,cy,ch=geometry
    crop_h=min(h,round(ch*h));crop_w=min(w,round(crop_h*ow/oh))
    left=int(np.clip(cx*w-crop_w/2,0,w-crop_w))
    top=int(np.clip(cy*h-crop_h/2,0,h-crop_h))
    return cv2.resize(frame[top:top+crop_h,left:left+crop_w],(ow,oh),interpolation=cv2.INTER_LANCZOS4)


def focus_frame(frame,center,target,ow=1080,oh=1920,source_time=None):
    from .render import compose
    if target is None:return compose(frame,center,ow,oh)
    return camera_frame(frame,focus_geometry(frame,center,target,ow,oh,source_time),ow,oh)
