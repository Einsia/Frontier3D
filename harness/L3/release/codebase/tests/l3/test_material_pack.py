"""Offline pack integrity and PBR convention regression checks."""
import hashlib
import json
from pathlib import Path
import importlib.util
import pytest

spec = importlib.util.spec_from_file_location('materials', Path(__file__).parents[2]/'tools/prepare_l3_materials.py')
materials = importlib.util.module_from_spec(spec)
spec.loader.exec_module(materials)

def source_maps(normal='nor_dx'):
    entry={'png':{'url':'https://example.org/a.png','size':3,'md5':'abc'}}
    return {name:{'2k':entry} for name in ['Diffuse',normal,'Rough']}

def test_gl_normal_keeps_convention():
    data=materials.select_maps(source_maps('nor_gl'),'2k')
    assert data['normal']['normal_convention']=='OpenGL'

def test_dx_preferred_when_both_available():
    maps=source_maps(); maps['nor_gl']=maps['nor_dx']
    assert materials.select_maps(maps,'2k')['normal']['normal_convention']=='DirectX'

def test_missing_map_rejected():
    maps=source_maps(); del maps['Rough']
    with pytest.raises(ValueError,match='roughness'):
        materials.select_maps(maps,'2k')

def test_alternative_color_retains_provenance():
    maps=source_maps(); maps['coll1']=maps.pop('Diffuse')
    assert materials.select_maps(maps,'2k')['basecolor']['source_channel']=='coll1'

@pytest.fixture
def pack(tmp_path):
    (tmp_path/'map.png').write_bytes(b'abc')
    data={'status':'complete','assets':[{'maps':{'basecolor':{'path':'map.png'}}}],
          'files':[{'path':'map.png','bytes':3,'sha256':hashlib.sha256(b'abc').hexdigest()}]}
    p=tmp_path/'manifest.json'; p.write_text(json.dumps(data)); return p

def test_verified_pack(pack):
    materials.verify(pack)

def test_corrupt_file_rejected(pack):
    (pack.parent/'map.png').write_bytes(b'bad')
    with pytest.raises(ValueError,match='modified'):
        materials.verify(pack)

def test_partial_pack_rejected(pack):
    data=json.loads(pack.read_text()); data['status']='incomplete'; pack.write_text(json.dumps(data))
    with pytest.raises(ValueError,match='incomplete'):
        materials.verify(pack)

def test_omitted_file_record_rejected(pack):
    data=json.loads(pack.read_text()); data['files']=[]; pack.write_text(json.dumps(data))
    with pytest.raises(ValueError,match='coverage'):
        materials.verify(pack)
