import tomllib
import pytest
from tools.prepare_l3_trial import codex_config


@pytest.mark.parametrize("model", ["gpt-6-luna", "gpt-6-sol"])
def test_fallback_models_use_supported_tool_families_and_high_effort(model):
    config = tomllib.loads(codex_config(model))
    assert config["model"] == model
    assert config["model_reasoning_effort"] == "high"
    assert config["web_search"] == "disabled"
    assert config["features"]["multi_agent"] is False
    assert config["agents"]["max_threads"] == 1
    provider = config["model_providers"]["l3"]
    assert provider["wire_api"] == "responses"
    assert provider["base_url"] == "http://127.0.0.1:8765/v1"
    assert provider["env_key"] == "L3_MODEL_API_KEY"
    assert "api_key" not in config


def test_other_models_keep_their_existing_configuration():
    for model in ["gpt-6-astra"]:
        config = tomllib.loads(codex_config(model))
        assert config["model"] == model
        assert config["model_reasoning_effort"] == "high"
        assert "web_search" not in config
        assert "features" not in config
