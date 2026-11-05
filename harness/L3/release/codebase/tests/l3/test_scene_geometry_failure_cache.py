import copy
from unittest.mock import patch
import numpy as np
from tests.l3.test_scene_geometry import cube,item
from harness.L3.MinecraftVillage.scene_geometry import Scene,static_measure

def fixture():
    plane={'vertices_cm':[[0,0,0],[10,0,10],[0,10,10]],'indices':[0,1,2]}
    return {'meshes':{'plane':plane,'cube':cube()},'instances':[
        dict(item('a','plane'),mesh='plane'),item('b','cube'),item('c','cube',(3,0,0))]}

def test_failed_static_validation_reused_but_stays_unresolved():
    s=Scene(fixture())
    with patch.object(s,'_solid',wraps=s._solid) as build:
        for other in [1,2,1]:
            result=s.overlap(0,other,2)
            assert result['violates'] is None and result['method']=='unresolved'
        assert sum(call.args[0]==0 for call in build.call_args_list)==1

def test_transformed_pose_does_not_reuse_static_failure():
    s=Scene(fixture())
    s.overlap(0,1,2)
    with patch.object(s,'_solid',wraps=s._solid) as build:
        s.overlap(0,1,2,transform_i=(np.eye(3),np.zeros(3)))
        assert build.call_count>=1

def test_static_result_identical_to_uncached_validation():
    cached=Scene(fixture());baseline=Scene(fixture())
    baseline.solid=baseline._solid
    assert static_measure(cached)==static_measure(baseline)
