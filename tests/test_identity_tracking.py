import numpy as np
import pytest
from reel_engine.tracking import associate,follow
from reel_engine.visual_focus import TargetMotionTracker,validate_targets


def test_three_characters_body_motion_does_not_win_speaker_assignment():
    samples=[dict(t=t,scene=0,characters=[
        dict(id='moving-parent',mouth_motion=.12,face_motion=.115),
        dict(id='speaking-bride',mouth_motion=.085,face_motion=.01),
        dict(id='silent-parent',mouth_motion=.003,face_motion=.002)]) for t in [0,.2,.4,.6,.8]]
    mapping,_=associate(samples,[dict(start=0,end=1,speaker='voice-7')])
    assert mapping['0:voice-7']=='speaking-bride'
    for sample in samples:sample['characters'][2].update(mouth_motion=.085,face_motion=.01)
    assert associate(samples,[dict(start=0,end=1,speaker='voice-7')])[0]['0:voice-7'] is None


def test_reviewed_identity_anchors_ignore_distractor_motion():
    item=dict(start=0,end=2,box=[.2,.1,.2,.7],kind='character',confidence=.9,reason='bride',evidence='reviewed',
              box_keyframes=[dict(t=0,box=[.2,.1,.2,.7]),dict(t=2,box=[.4,.1,.2,.7])])
    validate_targets([item],0,2)
    tracker=TargetMotionTracker()
    for i in range(3):
        frame=np.random.default_rng(i).integers(0,255,(180,320,3),dtype=np.uint8)
        box=tracker.update(frame,item,i)['box']
        assert box==pytest.approx([.2+.1*i,.1,.2,.7])
    assert tracker.anchored_frames==3 and tracker.failed_frames==0
    item['box_keyframes'][1]['box']=[.9,.1,.2,.7]
    with pytest.raises(ValueError,match='anchor box'):validate_targets([item],0,2)


def test_missing_texture_holds_identity_instead_of_switching_to_distractor():
    tracker=TargetMotionTracker()
    frame=np.zeros((180,320,3),np.uint8)
    target=dict(start=0,end=3,box=[.1,.1,.2,.6],kind='character')
    expected=tracker.update(frame,target,0)['box']
    for i in range(1,15):
        # An unrelated moving character elsewhere must not attract the tracker.
        frame[:]=0;frame[40:100,150+i:190+i]=255
        assert tracker.update(frame,target,i/30)['box']==expected
    assert tracker.failed_frames==14


def test_lost_character_id_is_retained_without_fabricating_lip_evidence():
    frame=np.zeros((180,320),np.uint8)
    item=dict(id='bride',face=[.1,.1,.2,.3],mouth=[.15,.2,.05,.05],confidence=.9,mouth_motion=.5)
    held=follow(frame,frame,[item])
    assert held[0]['id']=='bride' and held[0]['tracking_lost']
    samples=[dict(scene=0,t=t,characters=held) for t in [0,.2,.4,.6,.8]]
    assert associate(samples,[dict(start=0,end=1,speaker='voice-7')])[0]['0:voice-7'] is None
