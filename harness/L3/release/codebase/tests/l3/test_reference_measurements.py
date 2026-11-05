import unittest
import numpy as np
from harness.L3.MinecraftVillage.reference import polygon_mask, match_instances, rendered_mask_color
from harness.L3.MinecraftVillage.protocol import reference_plan, BUILDINGS, validate_plan


class ReferenceMeasurementTests(unittest.TestCase):
    def test_missing_object_and_extra_object_remain_in_denominator(self):
        left=np.zeros((12,12),bool);left[:4,:4]=True
        right=np.zeros((12,12),bool);right[8:,8:]=True
        refs=[dict(id='r1',mask=left,**{'class':'house'}),dict(id='r2',mask=right,**{'class':'house'})]
        candidates=[dict(id='c1',mask=left,**{'class':'house'})]
        measured=match_instances(refs,candidates)
        self.assertEqual(measured['unmatched_reference'],1)
        self.assertEqual(measured['mean_visible_iou_with_missing_and_extra_penalty'],.5)
        candidates.extend([dict(id='c2',mask=right,**{'class':'house'}),dict(id='extra',mask=left,**{'class':'house'})])
        measured=match_instances(refs,candidates)
        self.assertEqual(measured['unmatched_candidate'],1)
        self.assertAlmostEqual(measured['mean_visible_iou_with_missing_and_extra_penalty'],2/3)

    def test_wrong_category_cannot_pass_by_matching_silhouette(self):
        a=np.ones((8,8),bool)
        r=match_instances([dict(id='house',mask=a,**{'class':'house'})],[dict(id='tree',mask=a,**{'class':'tree'})])
        self.assertEqual(r['mean_visible_iou_with_missing_and_extra_penalty'],0)

    def test_empty_candidate_is_zero_not_unmeasured(self):
        r=match_instances([dict(id='house',mask=np.ones((8,8),bool),**{'class':'house'})],[])
        self.assertEqual(r['mean_visible_iou_with_missing_and_extra_penalty'],0)
        with self.assertRaises(ValueError):match_instances([],[])

    def test_mask_color_codec_uses_fixed_renderer_transfer(self):
        # UE native render regression measured these 8-bit output codes.
        np.testing.assert_allclose(rendered_mask_color([40,220,240],'ue_srgb_linear_display_gamma_2_2'),[44,218,239],atol=1,rtol=0)
        with self.assertRaises(ValueError):rendered_mask_color([40,220,240],'unknown')

    def test_polygon_does_not_allow_out_of_image_coordinates(self):
        with self.assertRaises(ValueError):polygon_mask([[0,0],[2,0],[0,1]],(100,100))

    def test_rgb_and_masks_use_one_frozen_camera_without_view_search(self):
        plan=reference_plan({'views':{'overview':{'position_cm':[100,200,300],'look_cm':[0,0,0],'horizontal_fov_deg':70}}})
        cameras=[s for s in plan['steps'] if s['op']=='camera']
        self.assertEqual(len(cameras),1)
        self.assertEqual(cameras[0]['horizontal_fov_deg'],70)
        masks=next(s for s in plan['steps'] if s['op']=='instance_masks')
        self.assertEqual([g['id'] for g in masks['groups']],BUILDINGS)
        masks['groups'][1]['rgb']=masks['groups'][0]['rgb']
        with self.assertRaises(ValueError):validate_plan(plan)


if __name__=='__main__':unittest.main()
