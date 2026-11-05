from pathlib import Path
import pytest
from harness.L3.MinecraftVillage.generate import generate

def test_unequipped_launcher_cannot_silently_create_benchmark_attempt(tmp_path):
    output=tmp_path/'trial'
    with pytest.raises(RuntimeError,match='no engine/preview'):
        generate(output)
    assert not output.exists()
