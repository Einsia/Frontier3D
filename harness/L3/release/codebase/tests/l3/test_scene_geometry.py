import json
from pathlib import Path
import tempfile
import unittest
import importlib.util
import numpy as np
from harness.L3.MinecraftVillage.scene_geometry import Scene, static_measure, motion_measure, broad_pairs


def cube():
    return {'vertices_cm':[[-1,-1,-1],[1,-1,-1],[1,1,-1],[-1,1,-1],[-1,-1,1],[1,-1,1],[1,1,1],[-1,1,1]],
            'indices':[0,2,1,0,3,2,4,5,6,4,6,7,0,1,5,0,5,4,1,2,6,1,6,5,2,3,7,2,7,6,3,0,4,3,4,7]}


def item(actor,component,position=(0,0,0),scale=(10,10,10),blocking=True):
    return dict(actor=actor,component=component,instance=0,mesh='cube',origin_cm=list(position),
                axis_x=[scale[0],0,0],axis_y=[0,scale[1],0],axis_z=[0,0,scale[2]],blocks_pawn=blocking)


def scene(*items):
    return Scene({'meshes':{'cube':cube()},'instances':list(items)})


class SceneGeometryTests(unittest.TestCase):
    @unittest.skipUnless(importlib.util.find_spec('manifold3d'),'Manifold is required for closed non-cuboid solids')
    def test_closed_nonbox_containment_uses_intersection_volume(self):
        tetra={'vertices_cm':[[0,0,0],[6,0,0],[0,6,0],[0,0,6]],'indices':[0,2,1,0,1,3,0,3,2,1,2,3]}
        export={'meshes':{'cube':cube(),'tetra':tetra},'instances':[item('a','cube'),dict(item('b','tetra',scale=(1,1,1)),mesh='tetra')]}
        r=static_measure(Scene(export))
        self.assertEqual(r['overlap_pair_count'],1)
        self.assertAlmostEqual(r['overlaps'][0]['intersection_cm3'],36)
    def test_same_actor_and_nonblocking_geometry_are_not_exempt(self):
        s=scene(item('room','wall'),item('room','cabinet',(10,0,0),blocking=False))
        result=static_measure(s)
        self.assertEqual(result['overlap_pair_count'],1)
        self.assertEqual(result['non_pawn_blocking_instances'],1)

    def test_touching_blocks_are_allowed_but_containment_is_detected(self):
        self.assertEqual(static_measure(scene(item('a','box'),item('b','box',(20,0,0))))['overlap_pair_count'],0)
        r=static_measure(scene(item('a','box'),item('b','box',scale=(3,3,3))))
        self.assertEqual(r['overlap_pair_count'],1)
        self.assertAlmostEqual(r['overlaps'][0]['depth_cm'],13)

    def test_contact_exception_is_bounded_and_does_not_hide_other_parts(self):
        s=scene(item('a','wall'),item('a','beam',(15,0,0)),item('a','chair',(-15,0,0)))
        rule={'id':'joint','reason':'bounded structural joint','left':['a','wall',0],
              'right':['a','beam',0],'max_depth_cm':5}
        r=static_measure(s,allowed=[rule])
        self.assertEqual(len(r['allowed_contacts']),1)
        self.assertEqual(r['overlap_pair_count'],1)
        rule['max_depth_cm']=4
        self.assertEqual(static_measure(s,allowed=[rule])['overlap_pair_count'],2)

    def test_broad_phase_is_conservative_including_giant_instance(self):
        rng=np.random.default_rng(33);low=rng.uniform(-800,800,(120,3));high=low+rng.uniform(1,300,(120,3))
        low[0]=[-10000]*3;high[0]=[10000]*3
        b=np.stack([low,high],axis=1);pairs=set(broad_pairs(b,max_cells=20))
        for i in range(len(b)):
            for j in range(i+1,len(b)):
                if np.all(np.minimum(high[i],high[j])-np.maximum(low[i],low[j])>0):self.assertIn((i,j),pairs)

    def test_nonclosed_geometry_is_unresolved_not_pass(self):
        export={'meshes':{'plane':{'vertices_cm':[[0,0,0],[10,0,10],[0,10,10]],'indices':[0,1,2]},'cube':cube()},
                'instances':[item('a','cube'),dict(item('b','plane'),mesh='plane')]}
        r=static_measure(Scene(export))
        self.assertEqual(r['unresolved_pair_count'],1)
        self.assertFalse(r['measurement_complete'])

    def test_chest_lid_checks_own_base_and_closed_pose(self):
        lid=item('house01.chest','lid');base=item('house01.chest','base',(10,0,0))
        s=scene(lid,base)
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)/'house01_chest';folder.mkdir()
            for i,x in enumerate([0,40,0]):
                parts=[]
                for obj in [lid,base]:
                    parts.append(dict(name=obj['component'],position_cm=[x,0,0] if obj is lid else obj['origin_cm'],
                                      axis_x=obj['axis_x'],axis_y=obj['axis_y'],axis_z=obj['axis_z'],visible=True,instances=1))
                (folder/f'trajectory_{i:04}.json').write_text(json.dumps(dict(time=i*.1,entities=[dict(id='house01.chest',components=parts)])))
            result=motion_measure(s,Path(tmp),targets=['house01.chest','storehouse.chest'])
            measured=result['targets']['house01.chest']
            self.assertFalse(measured['sampled_clear'])
            self.assertEqual(measured['moving_components'],['lid'])
            self.assertEqual(len(measured['overlaps']),2)
            self.assertIsNone(result['targets']['storehouse.chest']['sampled_clear'])
            self.assertFalse(measured['continuous_clearance_certified'])
            fast=motion_measure(s,Path(tmp),targets=['house01.chest'],stop_on_failure=True)['targets']['house01.chest']
            self.assertEqual(fast['sampled_clear'],measured['sampled_clear'])
            self.assertTrue(fast['stopped_after_counterexample'])
            self.assertLess(fast['evaluated_frames'],measured['evaluated_frames'])

    def test_instanced_obstacle_keeps_its_local_offset(self):
        lid=item('house01.chest','lid');far=item('terrain','single_instance',(1000,0,0))
        s=scene(lid,far)
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)/'house01_chest';folder.mkdir()
            for n,x in enumerate([0,40]):
                moving=dict(name='lid',position_cm=[x,0,0],axis_x=[10,0,0],axis_y=[0,10,0],axis_z=[0,0,10],visible=True,instances=1)
                # An HISM with one instance still has a local translation relative
                # to its component. Its component origin must not replace it.
                obstacle=dict(name='single_instance',position_cm=[0,0,0],axis_x=[1,0,0],axis_y=[0,1,0],axis_z=[0,0,1],visible=True,instances=1)
                frame=dict(time=n*.1,entities=[dict(id='house01.chest',components=[moving]),dict(id='terrain',components=[obstacle])])
                (folder/f'trajectory_{n:04}.json').write_text(json.dumps(frame))
            measured=motion_measure(s,Path(tmp),targets=['house01.chest'])['targets']['house01.chest']
            self.assertTrue(measured['sampled_clear'])
            fast=motion_measure(s,Path(tmp),targets=['house01.chest'],stop_on_failure=True)['targets']['house01.chest']
            self.assertTrue(fast['sampled_clear'])
            self.assertFalse(fast['stopped_after_counterexample'])
            self.assertEqual(fast['evaluated_frames'],measured['evaluated_frames'])


if __name__=='__main__':unittest.main()
