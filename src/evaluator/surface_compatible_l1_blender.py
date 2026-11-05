"""Inspect curves and text through evaluated meshes under the frozen CAD rules.

This isolated adapter uses the existing surface conversion and exact self-alias
check. It keeps solid audits, genuine-instance limits, and every scoring rule.
It never writes the submitted scene or executes its scripts.
"""
import hashlib
import importlib.util
import os
from pathlib import Path
import sys
import traceback

BASE_SHA256='eaffdfb9a2edf06d07d91743dcee7f2185a7d3993c535d7873c047ce31c53ac3'


def main():
    path=Path(__file__).with_name('l1_blender.py')
    if hashlib.sha256(path.read_bytes()).hexdigest()!=BASE_SHA256:
        raise ValueError('Pinned L1 inspection implementation changed')
    spec=importlib.util.spec_from_file_location('surface_adapter_base',path)
    base=importlib.util.module_from_spec(spec);spec.loader.exec_module(base)
    original=base._collect
    def collect(*args,**kwargs):
        kwargs['image_surfaces']=True
        facts,trees=original(*args,**kwargs)
        facts['surface_adapter']={'version':'l1-evaluated-surfaces-v1',
            'base_worker_sha256':BASE_SHA256,'candidate_scene_modified':False,
            'solid_audit_preserved':True,'genuine_instances_supported':False}
        return facts,trees
    base._collect=collect
    base.main()


if __name__=='__main__':
    try:main()
    except BaseException:
        traceback.print_exc();sys.stdout.flush();sys.stderr.flush();os._exit(1)
    else:
        sys.stdout.flush();sys.stderr.flush();os._exit(0)
