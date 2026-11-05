"""Published model-to-native-CLI routing, shared by generation and preflight."""

import json
import re
from pathlib import Path

POLICY_PATH = Path(__file__).resolve().parents[2] / "configs/release/generator-harnesses.json"
CLAUDE_VERSION = "2.1.268"
CLAUDE_DOCKER_IMAGE = "3dbench-claude:" + CLAUDE_VERSION
NATIVE_DOCKER_IMAGE = "3dbench-native:contract-v1"
REGISTRY_PATH = POLICY_PATH.with_name('model-harness-contract.json')


def validate_model_id(model):
    if not isinstance(model,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*(?:/[A-Za-z0-9][A-Za-z0-9._-]*)*',model):
        raise ValueError('Model ID must contain safe, relative identifier segments')
    return model


def model_contract(model):
    return next((r for r in json.loads(REGISTRY_PATH.read_text())['models']
                 if r['model'].casefold() == str(model).casefold()), None)


def model_effort(model):
    row = model_contract(model)
    return row['effort'] if row else 'max'


def generator_harness(model):
    row = model_contract(model)
    if row:
        return row['harness_id']
    policy = json.loads(POLICY_PATH.read_text())
    name = str(model).casefold()
    return next((harness for prefix, harness in policy["model_prefixes"].items()
                 if name.startswith(prefix.casefold())), policy["default"])


def native_harness(model):
    policy = json.loads(POLICY_PATH.read_text())
    return policy["native_names"][generator_harness(model)]


def native_metadata(harness):
    return json.loads(POLICY_PATH.read_text())['cli'][harness]
