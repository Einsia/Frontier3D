"""Select hash-bound screenshots rendered by the independent view episode."""
from pathlib import Path
from .policy import read
from harness.L3.MinecraftVillage.protocol import digest

def selected_views(folder):
    folder=Path(folder)
    metadata=read(folder/'views-metadata.json')
    selected=[(name,m) for name,m in metadata.items() if m.get('kind')=='view']
    if not selected:
        selected=[(name,m) for name,m in metadata.items()
                  if m.get('kind')=='reference' and m.get('yaw_delta')==0]
    if not selected:
        raise RuntimeError('No independent views')
    record=read(folder/'run.json')
    if record.get('status')!='collected' or not read(folder/'workspace/episodes/views/completed.json').get('completed'):
        raise RuntimeError('Independent view episode incomplete')
    for name,metadata in selected:
        if Path(name).name!=name or name in ('.','..'):
            raise ValueError('Invalid independent capture name')
        relative='workspace/episodes/views/'+name+'.png'
        path=folder/relative
        if not path.is_file() or record['evidence_sha256'].get(relative)!=digest(path):
            raise ValueError('Independent capture hash mismatch: '+name)
    return selected
