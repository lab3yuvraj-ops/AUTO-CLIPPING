import numpy as np
import pytest
from reel_engine.camera import ease_camera


def test_pan_and_zoom_step_becomes_monotonic_ease_without_overshoot():
    raw=[[.3,.5,1.]]*30+[[.7,.65,.55]]*30
    path=np.array(ease_camera(raw,[i/30 for i in range(60)]))
    assert path[0]==pytest.approx(raw[0])
    assert path[-1]==pytest.approx(raw[-1])
    assert np.all(np.diff(path[:,0])>=-1e-10)
    assert np.all(np.diff(path[:,2])<=1e-10)
    assert np.max(np.diff(path[:,0]))<.04
    assert path[29,0]<path[30,0]<path[31,0]


@pytest.mark.parametrize('cuts,times',[
    ([1.],[i/30 for i in range(60)]),
    ([],[i/30 for i in range(30)]+[5+i/30 for i in range(30)])])
def test_easing_does_not_cross_scene_or_edit_cut(cuts,times):
    raw=[[.3,.5,1.]]*30+[[.7,.65,.55]]*30
    assert np.array(ease_camera(raw,times,cuts))==pytest.approx(np.array(raw))
