"""Extract a user-provided official Epic Linux archive into a fresh directory."""
import argparse, hashlib, os, shutil, stat, tarfile, zipfile
from pathlib import Path, PurePosixPath


def install(archive: Path, destination: Path, expected_sha256: str):
    h=hashlib.sha256()
    with archive.open('rb') as f:
        for block in iter(lambda:f.read(8*1024*1024),b''): h.update(block)
    if h.hexdigest()!=expected_sha256: raise ValueError('Archive checksum mismatch')
    destination=destination.resolve()
    if destination.exists(): raise ValueError('Destination must not already exist')
    destination.parent.mkdir(parents=True,exist_ok=True)
    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as z:
            infos=z.infolist();names=set()
            for i in infos:
                p=PurePosixPath(i.filename)
                if p.is_absolute() or '..' in p.parts or i.filename in names: raise ValueError('Unsafe or duplicate archive path')
                names.add(i.filename)
                if stat.S_ISLNK(i.external_attr>>16):
                    target=z.read(i).decode()
                    if not (destination/p.parent/target).resolve().is_relative_to(destination): raise ValueError('Escaping archive symlink')
            needed=sum(i.file_size for i in infos)
            if shutil.disk_usage(destination.parent).free<needed+5*1024**3: raise ValueError('Insufficient disk space')
            destination.mkdir()
            links=[]
            for i in infos:
                p=destination/i.filename;mode=i.external_attr>>16
                if stat.S_ISLNK(mode): links.append((p,z.read(i).decode()));continue
                if i.is_dir(): p.mkdir(parents=True,exist_ok=True);continue
                p.parent.mkdir(parents=True,exist_ok=True)
                with z.open(i) as src,p.open('wb') as dst: shutil.copyfileobj(src,dst)
                p.chmod((mode&0o777) or 0o644)
            for p,target in links: p.parent.mkdir(parents=True,exist_ok=True);p.symlink_to(target)
    else:
        # Python >=3.12 data filter rejects escaping links, devices and unsafe paths.
        with tarfile.open(archive) as t:
            if shutil.disk_usage(destination.parent).free<sum(m.size for m in t.getmembers())+5*1024**3: raise ValueError('Insufficient disk space')
            destination.mkdir();t.extractall(destination,filter='data')
    roots=list(destination.glob('**/Engine/Build/Build.version'))
    if len(roots)!=1: raise ValueError('Expected exactly one Engine/Build/Build.version')
    return roots[0].parents[2]

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--archive',type=Path,required=True);p.add_argument('--destination',type=Path,required=True);p.add_argument('--sha256',required=True)
    a=p.parse_args();print(install(a.archive,a.destination,a.sha256))
