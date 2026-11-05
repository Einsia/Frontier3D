"""Distinguish an authoring attempt from a failed initial model connection."""
import json

def has_authoring_activity(events):
    for line in events.read_text(errors="replace").splitlines():
        try:
            event=json.loads(line)
        except json.JSONDecodeError:
            continue
        item=event.get("item",{})
        if event.get("type") in {"item.started","item.completed"} and item.get("type") in {"command_execution","file_change"}:
            return True
    return False


def completion_evidence(workspace, timing):
    """Delivery evidence only; build/visual/functional correctness requires verification."""
    project = workspace / 'project'
    required = ['README.md', 'bindings.json', 'assets_used.json']
    missing = [name for name in required if not (project / name).is_file()]
    if len(list(project.glob('*.uproject'))) != 1:
        missing.append('exactly one .uproject')
    final = workspace / 'agent-final.txt'
    if not final.is_file() or not final.read_text().strip():
        missing.append('agent-final.txt')
    previews = [str(p.relative_to(workspace)) for p in (workspace / 'checks').rglob('*.png')
                if not any(part.startswith('preflight') for part in p.relative_to(workspace / 'checks').parts)]
    if not previews:
        missing.append('scene preview')
    return {'agent_turn_completed': timing.get('generation_status') == 'completed'
            and timing.get('terminal_event') == 'turn.completed',
            'missing_delivery_evidence': missing, 'scene_previews': previews,
            'delivery_complete': timing.get('generation_status') == 'completed'
            and timing.get('terminal_event') == 'turn.completed' and not missing,
            'quality_verified': False}
