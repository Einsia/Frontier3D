"""Public delivery checks shared by fresh and resumed generation."""
import json,hashlib

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def terminal_complete(timing):
    return (timing.get('generation_status')=='completed'
            and timing.get('terminal_event')=='turn.completed'
            and timing.get('return_code')==0)

def delivery_feedback(workspace,timing,complete_delivery=True,initial_project=None):
    project=workspace/"project"
    from tools.l3_trial_status import completion_evidence
    evidence=completion_evidence(workspace,timing);missing=list(evidence['missing_delivery_evidence'])
    if not terminal_complete(timing):missing.append('normal agent completion after finishing delivery')
    for name in ['bindings.json','assets_used.json']:
        file=workspace/'project'/name
        if file.exists():
            try:json.loads(file.read_text())
            except ValueError:missing.append(name+' must contain valid JSON')
    if complete_delivery:
        sources=[p.stat().st_mtime for p in (workspace/'project/Source').rglob('*') if p.is_file() and p.suffix in {'.cpp','.h','.hpp','.cs','.c'}]
        descriptors=list((workspace/'project').glob('*.uproject'))
        try:
            modules=json.loads(descriptors[0].read_text()).get('Modules',[]) if len(descriptors)==1 else []
            binaries=[workspace/'project/Binaries/Linux'/('libUnrealEditor-'+m['Name']+'.so') for m in modules]
            if not binaries or not all(p.is_file() for p in binaries) or sources and max(sources)>max(p.stat().st_mtime for p in binaries):missing.append('successful C++ build after the final source edits')
        except (ValueError,KeyError):missing.append('valid project descriptor and compiled project modules')
    if initial_project is not None:
        files={str(p.relative_to(project)):sha(p) for p in project.rglob('*')
               if p.is_file() and not set(p.relative_to(project).parts)&{'Binaries','Intermediate','Saved','DerivedDataCache','.git'}}
        scene=lambda k:k.startswith(('Source/','Content/','Config/')) or k.endswith('.uproject')
        if not any(scene(k) and files.get(k)!=initial_project.get(k) for k in set(files)|set(initial_project)):
            missing.append('replace the generic equipment fixture with the requested scene')
    return 'Missing or unfinished public delivery requirements: '+', '.join(missing) if missing else None
