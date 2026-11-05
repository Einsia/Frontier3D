import copy, json, hashlib
from harness.L3.MinecraftVillage.physical_scene import physical_scene, SKY_SIGNATURE


def fixture(root):
    hashes={}
    for name in ['project/Content/L3Environment/M_DefaultSky.uasset','project/Source/L3Environment/L3DefaultEnvironment.h']:
        p=root/'workspace'/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'known organizer file')
        hashes[name]=hashlib.sha256(p.read_bytes()).hexdigest()
    (root/'preflight-complete.json').write_text(json.dumps({'input_and_material_hashes':hashes}))
    return dict(SKY_SIGNATURE,actor='sky',component='sphere',instance=0)


def test_exact_background_only_and_original_evidence_retained(tmp_path):
    sky=fixture(tmp_path);small=copy.deepcopy(sky);small['axis_x']=[1,0,0]
    blocking=copy.deepcopy(sky);blocking['blocks_pawn']=True
    original={'instances':[sky,small,blocking]};saved=copy.deepcopy(original)
    filtered,audit=physical_scene(original,tmp_path)
    assert original==saved
    assert filtered['instances']==[small,blocking]
    assert len(audit['excluded'])==1


def test_modified_equipment_is_not_exempt(tmp_path):
    sky=fixture(tmp_path)
    (tmp_path/'workspace/project/Content/L3Environment/M_DefaultSky.uasset').write_bytes(b'changed')
    filtered,audit=physical_scene({'instances':[sky]},tmp_path)
    assert filtered['instances']==[sky]
    assert audit['status']=='organizer_background_modified_or_unverified'


def test_lighting_helper_edit_does_not_make_unchanged_sky_a_solid(tmp_path):
    sky=fixture(tmp_path)
    (tmp_path/'workspace/project/Source/L3Environment/L3DefaultEnvironment.h').write_bytes(b'adapted lighting')
    filtered,audit=physical_scene({'instances':[sky]},tmp_path)
    assert filtered['instances']==[]
    assert audit['daylight_helper_changed'] is True
    assert len(audit['excluded'])==1
