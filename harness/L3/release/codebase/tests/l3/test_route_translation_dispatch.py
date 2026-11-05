from harness.L3.Suite.route_translation import needs_translation

def test_descriptive_mapping_is_not_silently_empty():
    assert needs_translation({'workflow': {'task_waypoints': [{'position_cm': [1,2,3]}], 'interaction_steps': [{'entity': 'door', 'action': 'open'}]}})

def test_waypoints_and_notes_request_translation():
    assert needs_translation({'workflow': [{'op': 'waypoint', 'position_cm': [1,2,3]}, {'op': 'interact', 'target': 'door', 'action': 'open'}]})
    assert needs_translation({'workflow': {'steps': [{'op': 'note', 'text': 'walk to the gate'}]}})

def test_executable_routes_pass_through():
    for route in [[{'op': 'walk_to', 'target_cm': [1,2,3]}], {'steps': [{'op': 'interact', 'target': 'door', 'action': 'open'}]}]:
        assert not needs_translation({'workflow': route})

def test_empty_routes_do_not_invent_work():
    for binding in [{}, {'workflow': []}, {'workflow': {}}, {'workflow': {'steps': []}}]:
        assert not needs_translation(binding)

def test_forbidden_executable_operations_still_rejected_downstream():
    for op in ['fixture', 'teleport', 'reset', 'unknown']:
        assert not needs_translation({'workflow': [{'op': op}]})

def test_existing_text_translation_remains_enabled():
    assert needs_translation({'workflow': 'Walk to the door.'})
    assert needs_translation({'workflow': ['Walk to the door.']})

def test_unexpressible_location_is_reported_not_invented(tmp_path,monkeypatch):
    import copy
    from harness.L3.Suite import vlm
    from harness.L3.Suite.route_translation import executable_bindings
    from harness.L3.Suite.plans import workflow_plan
    (tmp_path/'instruction.md').write_text('Walk to supplied locations.')
    rows=[{'op':'walk_to','target_cm':None,'seconds':1},
          {'op':'walk_to','target_cm':[1,2,3],'seconds':1}]
    monkeypatch.setattr(vlm,'call',lambda *args: {'steps':rows})
    b={'workflow':'Go to a missing destination, then a supplied one.'};original=copy.deepcopy(b)
    result=executable_bindings(b,{'entities':[]},tmp_path,tmp_path)
    plan,meta=workflow_plan(result,{'entities':[]})
    assert b==original and len(result['workflow']['steps'])==1
    assert result['workflow']['steps'][0]['target_cm']==[1,2,3]
    assert len(meta['rejected'])==1 and 'no executable' in meta['rejected'][0]['reason']
