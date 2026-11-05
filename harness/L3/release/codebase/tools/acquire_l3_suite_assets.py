"""Organizer-side offline source acquisition with immutable byte hashes."""
import concurrent.futures,hashlib,html,json,re,time,urllib.request,urllib.parse,urllib.error,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'data/l3/preparation/l3-suite-20261023'
LIB=ROOT.parent/'l3-assets/kenney-suite-20261023'
UA='3DBench-AssetPreparation/1.0 (offline research scene benchmark)'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,v):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
def fetch(url,path):
 path.parent.mkdir(parents=True,exist_ok=True)
 if path.exists() and path.stat().st_size:return path.read_bytes()
 for a in range(4):
  try:
   req=urllib.request.Request(url,headers={'User-Agent':UA})
   with urllib.request.urlopen(req,timeout=45) as r:data=r.read()
   tmp=path.with_suffix(path.suffix+'.partial');tmp.write_bytes(data);tmp.replace(path);return data
  except Exception as error:
   if isinstance(error,urllib.error.HTTPError) and error.code==429:raise
   if a==3:raise
   time.sleep(2**a)
def pack(name):
 url='https://kenney.nl/assets/'+name;folder=LIB/name
 page=fetch(url,OUT/'source-pages'/('kenney-'+name+'.html')).decode()
 links=list(dict.fromkeys(re.findall(r'https?[^\"\s<>]+\.zip',page)))
 if not links:raise ValueError('No official ZIP '+name)
 archive=LIB/'archives'/(name+'.zip');fetch(links[0],archive)
 folder.mkdir(parents=True,exist_ok=True)
 with zipfile.ZipFile(archive) as z:
  for f in z.infolist():
   dest=(folder/f.filename).resolve()
   if not dest.is_relative_to(folder.resolve()) or (f.external_attr>>16)&0o170000==0o120000:raise ValueError('Unsafe ZIP member')
   if not dest.exists():z.extract(f,folder)
 files=[{'path':str(p.relative_to(LIB)),'bytes':p.stat().st_size,'sha256':sha(p)} for p in folder.rglob('*') if p.is_file() and p.name!='asset-manifest.json']
 models=[x['path'] for x in files if Path(x['path']).suffix.lower() in {'.glb','.gltf','.fbx','.obj'}]
 if not models:raise ValueError('No models '+name)
 row={'id':name,'source':url,'download_url':links[0],'license':'CC0-1.0','license_url':'https://creativecommons.org/publicdomain/zero/1.0/','archive_sha256':sha(archive),'models':models,'files':files}
 write(folder/'asset-manifest.json',row);return row

def panorama(name):
 page='https://polyhaven.com/a/'+name
 meta=json.loads(fetch('https://api.polyhaven.com/files/'+name,OUT/'panoramas'/name/'files.json'))
 spec=meta['tonemapped'];p=OUT/'panoramas'/name/'panorama.jpg';fetch(spec['url'],p)
 if hashlib.md5(p.read_bytes()).hexdigest()!=spec['md5']:raise ValueError('MD5 mismatch '+name)
 try:fetch(page,OUT/'source-pages'/('polyhaven-'+name+'.html'))
 except Exception:pass
 return {'id':name,'source':page,'download_url':spec['url'],'path':str(p),'sha256':sha(p),'license':'CC0-1.0','license_url':'https://polyhaven.com/license','method':'photographic_equirectangular_panorama'}

def commons(name,task):
 filename=name.replace(' ','_');page='https://commons.wikimedia.org/wiki/File:'+urllib.parse.quote(filename)
 raw=fetch(page,OUT/'source-pages'/(task+'-'+filename+'.html')).decode()
 md5=hashlib.md5(filename.encode()).hexdigest();url='https://upload.wikimedia.org/wikipedia/commons/'+md5[0]+'/'+md5[:2]+'/'+urllib.parse.quote(filename)
 p=OUT/'references'/task/filename
 try:fetch(url,p)
 except urllib.error.HTTPError as error:
  if error.code!=429:raise
  links=[html.unescape(x) for x in re.findall(r'https://thumb\.wikimedia\.org/[^"<>\s]+',raw) if '/1280px-' in x]
  if not links:raise
  url=links[0];p=p.with_name(p.stem+'-1280'+p.suffix);fetch(url,p)
 decoded=html.unescape(raw)
 match=re.search(r'<td[^>]*id="fileinfotpl_aut"[^>]*>.*?</td>\s*<td[^>]*>(.*?)</td>',decoded,re.S)
 if not match:raise ValueError('Missing image author')
 author=re.sub(r'\s+',' ',re.sub('<[^>]+>',' ',match.group(1))).strip()
 licenses=['https://creativecommons.org/licenses/by-sa/4.0/']
 if 'CC-BY-SA-4.0' not in raw:raise ValueError('Unexpected Commons image license; inspect file page')
 return {'task':task,'path':str(p),'source':page,'download_url':url,'sha256':sha(p),'license_urls':licenses,'author':author,'kind':'photograph'}

def direct(task,name,url,source,owner):
 p=OUT/'references'/task/name;fetch(url,p)
 return {'task':task,'path':str(p),'source':source,'download_url':url,'sha256':sha(p),'copyright':owner,'license':'copyrighted_game_screenshot','usage':'visual_reference_only','kind':'game_screenshot'}

def main():
 OUT.mkdir(parents=True,exist_ok=True);jobs=[]
 for name in ['furniture-kit','food-kit','nature-kit','city-kit-industrial','space-kit','survival-kit','castle-kit']:jobs.append(('pack:'+name,lambda name=name:pack(name)))
 for name in ['blinds','university_workshop','cloudy_netted_nursery']:jobs.append(('panorama:'+name,lambda name=name:panorama(name)))
 for task,names in {'l3-e02':['Supermarket shelves.jpg'],'l3-r01':['20240111 Qinwang Gong.jpg','20240111 Zhonggong Men.jpg','20240111 Sihaiguiyi Dian.jpg'],'l3-r02':['Cheung Chau Ferry Pier 2026.jpg']}.items():
  for name in names:jobs.append((task+':'+name,lambda name=name,task=task:commons(name,task)))
 for i in [1,2,4,6,7]:
  url=f'https://www.powerpyx.com/wp-content/uploads/Sekiro-Shadows-Die-Twice-Ashina-Castle-{i}.jpg'
  jobs.append((f'l3-g02:{i}',lambda i=i,url=url:direct('l3-g02',f'candidate-{i:02}.jpg',url,'https://www.powerpyx.com/sekiro-shadows-die-twice-ashina-castle-walkthrough/','FromSoftware / Activision; screenshot source PowerPyx')))
 for i in [142,156]:
  jobs.append((f'l3-g02:castle{i}',lambda i=i:direct('l3-g02',f'castle-{i}.jpg',f'https://blog-imgs-125.fc2.com/g/o/d/godeaterlove/sekiro{i}.jpg','https://godeaterlove.blog.fc2.com/blog-entry-871.html','FromSoftware / Activision; screenshot source godeaterlove')))
 jobs.append(('l3-g03:street',lambda:direct('l3-g03','street.jpg','https://www.ireddead.com/content/images/busy-valentine-street-1573.jpg','https://www.ireddead.com/rdr2/images/busy-valentine-street-1573','Rockstar Games; official screenshot mirrored by iRedDead')))
 for i in [1,2,3]:
  url=f'https://www.philipk.net/portfolio/overwatch/Overwatch_Rialto_{i:02}.jpg'
  jobs.append((f'l3-g04:{i}',lambda i=i,url=url:direct('l3-g04',f'rialto-{i:02}.jpg',url,'https://www.philipk.net/portfolio/overwatch/overwatch_port.html','Blizzard Entertainment; environment artist Philip Klevestav portfolio')))
 records={};errors={}
 with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
  futures={pool.submit(fn):key for key,fn in jobs}
  for f in concurrent.futures.as_completed(futures):
   key=futures[f]
   try:records[key]=f.result();print('READY',key,flush=True)
   except Exception as e:errors[key]=str(e);print('FAILED',key,str(e),flush=True)
   write(OUT/'acquisition.json',{'records':records,'errors':errors,'completed':len(records)+len(errors),'total':len(jobs)})
 write(LIB/'manifest.json',{'schema':'l3-offline-model-library-v1','packs':[records[k] for k in sorted(records) if k.startswith('pack:')],'errors':{k:v for k,v in errors.items() if k.startswith('pack:')}})
 if errors:raise SystemExit(1)
if __name__=='__main__':main()
