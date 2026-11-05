"""Resolve candidate identity independently from the fixed Astra judge."""
import os
from benchmark.resources import resource, blender_path, env_path, judge_key, judge_model, read_public_methods

import json

def tested_model(root):
    campaign = json.loads((root / 'campaign.json').read_text())
    models = campaign.get('models', ['gpt-6-astra'])
    if len(models) != 1:
        raise ValueError('Legacy evaluation needs one candidate model per campaign')
    return models[0]
