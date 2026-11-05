import shlex
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from src.ue5.runtime import UE5Config, UE5Error, build_smoke_command
from harness.L3.MinecraftVillage.runtime import run, isolated
from harness.L3.MinecraftVillage.protocol import tree_digest, write_json


class RuntimeResourceTests(unittest.TestCase):
    def test_project_build_receives_budget_in_both_backends(self):
        for mode in ('local', 'docker'):
            config = UE5Config(mode=mode, root=Path('/engine'),
                               editor=Path('/engine/Engine/Binaries/Linux/UnrealEditor'),
                               runuat=Path('/engine/Engine/Build/BatchFiles/RunUAT.sh'))
            command = build_smoke_command(config, Path('/project with spaces/Pilot.uproject'),
                                          Path('/output'), max_parallel_actions=16, disable_uba=True)
            args = shlex.split(command[-1])
            self.assertIn('-MaxParallelActions=16', args)
            self.assertIn('-NoUBA', args)
            self.assertIn('-corelimit=16', args)
            self.assertIn('/project with spaces/Pilot.uproject' if mode == 'local'
                          else '/project/Pilot.uproject', args)

    def test_invalid_build_budget_rejected(self):
        for value in (True, 0, -1, 1.5):
            with self.assertRaises(UE5Error):
                build_smoke_command(UE5Config(), Path('/p/P.uproject'), Path('/o'),
                                    max_parallel_actions=value)

    def test_invalid_run_resources_rejected_before_creating_output(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            for options in ({'graphics_adapter': -1}, {'graphics_adapter': True},
                            {'build_jobs': 0}, {'timeout': float('inf')}, {'timeout': 0},
                            {'nvidia_device': -1}, {'nvidia_device': 3, 'graphics_adapter': 2}):
                with self.assertRaises(ValueError):
                    run(root/'submission', None, root/'output', **options)
                self.assertFalse((root/'output').exists())

    def test_source_build_writes_only_dedicated_engine_copy(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            base, clone, project, output = [root/n for n in ('base', 'clone', 'project', 'output')]
            for p in (base, clone, project, output): p.mkdir()
            with patch('harness.L3.MinecraftVillage.runtime.shutil.which', return_value='/usr/bin/bwrap'):
                build = isolated(['/bin/true'], base, project, output, engine_copy=clone, building=True)
                render = isolated(['/bin/true'], base, project, output, engine_copy=clone)
            source_mount=render.index('--ro-bind',render.index(str(output))+1)
            self.assertEqual(render[source_mount+1:source_mount+3],[str(project),str(project)])
            self.assertTrue((project/'Intermediate').is_dir())
            self.assertIn('UE_LocalDataCachePath', render)
            self.assertIn(str(output/'derived-data-cache'), render)
            i = build.index(str(clone))
            self.assertEqual(build[i-1:i+2], ['--bind', str(clone), str(base)])
            j = render.index(str(clone))
            self.assertEqual(render[j-1:j+2], ['--ro-bind', str(clone), str(base)])

    def test_cache_seed_cannot_cross_submissions_or_follow_symlinks(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);project=root/'submission';project.mkdir()
            (project/'source.txt').write_text('fixed candidate')
            seed=root/'seed';seed.mkdir();cache=seed/'derived-data-cache';cache.mkdir()
            version={'MajorVersion':5,'MinorVersion':8,'PatchVersion':3}
            write_json(seed/'environment.json',{'version':version})
            write_json(seed/'run.json',{'submission_sha256':'another submission'})
            with patch('harness.L3.MinecraftVillage.runtime.doctor',return_value={'status':'engine_present_unverified','version':version}):
                with self.assertRaisesRegex(ValueError,'exact same submission'):
                    run(project,None,root/'run1',cache_from_run=seed)
                write_json(seed/'run.json',{'submission_sha256':tree_digest(project)})
                (cache/'outside').symlink_to(project/'source.txt')
                with self.assertRaisesRegex(ValueError,'symlinks'):
                    run(project,None,root/'run2',cache_from_run=seed)
                self.assertFalse((root/'run2/derived-data-cache').exists())
