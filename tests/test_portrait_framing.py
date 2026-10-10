import numpy as np
import pytest
from reel_engine.tracking import crop_centers,fill_missing_centers
from reel_engine.render import compose
from reel_engine.visual_focus import focus_geometry,camera_frame
from reel_engine.camera import ease_camera


def test_small_subjects_keep_full_source_height_and_only_pan_horizontally():
    frame=np.zeros((180,320,3),dtype=np.uint8)
    frame[0]=[0,0,255];frame[-1]=[255,0,0]
    raw=[]
    for x,y,size in [(0,.1,.02),(.45,.8,.01),(.9,.2,.06)]:
        target=dict(box=[x,y,size,size],kind='character')
        geometry=focus_geometry(frame,.5,target)
        assert geometry[1:]==[.5,1.]
        half_width=180/320*9/16/2
        assert half_width<=geometry[0]<=1-half_width
        crop=camera_frame(frame,geometry,ow=101,oh=180)
        assert np.all(crop[0]==[0,0,255])
        assert np.all(crop[-1]==[255,0,0])
        raw.extend([geometry]*30)
    eased=np.array(ease_camera(raw,[i/30 for i in range(90)],duration=1.2))
    assert eased[:,1]==pytest.approx(np.full(90,.5))
    assert eased[:,2]==pytest.approx(np.ones(90))
    assert np.max(np.abs(np.diff(eased[:,0])))<.04


def test_character_switch_and_smooth_follow_respect_shot_boundaries():
    tracking={'crop_keyframes':[{'t':10,'center':.2,'cut':True},
                              {'t':12,'center':.3,'cut':False},
                              {'t':13,'center':.8,'cut':True}]}
    result=crop_centers(tracking,[],[10,11,12,12.9,13])
    assert result==pytest.approx([.2,.25,.3,.3,.8])


def test_uncertain_turn_holds_crop_and_new_scene_resets():
    tracking={'samples':[{'t':0,'scene':0,'characters':[]},
                         {'t':3,'scene':1,'characters':[{'face':[.7,.1,.2,.3]}]}]}
    result=fill_missing_centers([.25,None,None,None],tracking,[0,1,2,3])
    assert result==pytest.approx([.25,.25,.25,.8])


def test_portrait_fills_edges_and_switches_left_to_right_character():
    frame=np.zeros((180,320,3),dtype=np.uint8)
    frame[:,:160]=[20,50,230];frame[:,160:]=[230,50,20]
    for center,color in [(.2,[20,50,230]),(.8,[230,50,20])]:
        portrait=compose(frame,center,ow=90,oh=160)
        assert portrait.shape==(160,90,3)
        assert np.all(portrait==color)


def test_invalid_manual_focus_is_rejected():
    with pytest.raises(ValueError):
        crop_centers({'crop_keyframes':[{'t':0,'center':float('nan')}]},[],[0])


def test_caption_position_changes_at_shot_boundary_without_changing_speech(tmp_path):
    from reel_engine.captions import make_ass
    words=[{'id':0,'roman':'Lena','speaker':'A','start':0,'end':.5},
           {'id':1,'roman':'tum','speaker':'A','start':.6,'end':1}]
    events=make_ass(words,tmp_path/'captions.ass',positions=[{'start':.3,'end':.8,'y':400}])
    assert all(e['y']==400 if .3<=(e['start']+e['end'])/2<.8 else e['y']==1420 for e in events)
    assert all(e['active_ids']==[0] for e in events if e['end']<=.5)


