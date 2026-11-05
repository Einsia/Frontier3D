"""Make rectilinear reference views from real photographic equirectangular panoramas."""
import argparse,hashlib,json,math
from pathlib import Path
import numpy as np
from PIL import Image
from scipy.ndimage import map_coordinates

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def project(source,output):
 manifest=output/'projections.json'
 if manifest.exists():
  data=json.loads(manifest.read_text())
  if data['source_sha256']!=sha(source):raise ValueError('Panorama changed')
  if not all(sha(Path(r['path']))==r['sha256'] for r in data['views']):raise ValueError('Projection changed')
  return data
 output.mkdir(parents=True,exist_ok=True);im=np.asarray(Image.open(source).convert('RGB'));height,width=800,1280
 xx,yy=np.meshgrid((np.arange(width)+.5-width/2)/(width/2),-(np.arange(height)+.5-height/2)/(width/2));zz=np.ones_like(xx)
 vectors=np.stack([xx,yy,zz],axis=-1);vectors/=np.linalg.norm(vectors,axis=-1,keepdims=True);rows=[]
 for i,yaw in enumerate([0,90,180,270],1):
  a=math.radians(yaw);p=math.radians(-10)
  right=np.array([math.cos(a),0,-math.sin(a)]);up=np.array([-math.sin(a)*math.sin(p),math.cos(p),-math.cos(a)*math.sin(p)]);forward=np.array([math.sin(a)*math.cos(p),math.sin(p),math.cos(a)*math.cos(p)])
  ray=vectors[...,0,None]*right+vectors[...,1,None]*up+vectors[...,2,None]*forward
  u=(np.arctan2(ray[...,0],ray[...,2])/(2*np.pi)+.5)*im.shape[1]-.5;v=(.5-np.arcsin(np.clip(ray[...,1],-1,1))/np.pi)*im.shape[0]-.5
  # Extend the seam explicitly; latitude stays inside the panorama.
  wrapped=np.concatenate([im[:,-1:],im,im[:,:1]],axis=1)
  coords=np.stack([np.clip(v,0,im.shape[0]-1),np.mod(u,im.shape[1])+1])
  rgb=np.stack([map_coordinates(wrapped[...,c],coords,order=1,mode='nearest') for c in range(3)],axis=-1)
  out=output/f'view-{i:02}.jpg';Image.fromarray(rgb.astype(np.uint8)).save(out,quality=94)
  rows.append({'path':str(out.resolve()),'yaw_deg':yaw,'pitch_deg':-10,'horizontal_fov_deg':90,'width':width,'height':height,'sha256':sha(out)})
 data={'source_sha256':sha(source),'projection':'rectilinear_from_same_photographic_panorama','views':rows};manifest.write_text(json.dumps(data,indent=2)+'\n');return data
if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('source',type=Path);p.add_argument('--output',type=Path,required=True);a=p.parse_args();print(json.dumps(project(a.source,a.output),indent=2))
