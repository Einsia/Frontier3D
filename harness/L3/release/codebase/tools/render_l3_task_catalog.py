"""Render a self-contained server-side task review catalogue and delivery archive."""
from pathlib import Path
import html,json,shutil,tarfile,hashlib
ROOT=Path(__file__).resolve().parents[1];BASE=ROOT/'data/l3/preparation/l3-suite-20261023'
def esc(v):return html.escape(str(v),quote=True)
def main():
 out=BASE/'review';out.mkdir(exist_ok=True);idx=json.loads((ROOT/'tasks/L3/task-index.json').read_text());parts=[]
 for t in idx['tasks']:
  folder=ROOT/t['path'];meta=json.loads((folder/'task.json').read_text());inp=folder/'environment/input';refs=json.loads((inp/'references.json').read_text());contract=json.loads((inp/'interaction-contract.json').read_text());sel=json.loads((inp/'asset-selection.json').read_text());dest=out/'tasks'/t['key']
  if dest.exists():shutil.rmtree(dest)
  shutil.copytree(folder,dest)
  figures=[]
  for im in refs['images']:
   source=im['provenance'];credit=source.get('author',source.get('copyright','Poly Haven'));license=source.get('license','see source')
   url='tasks/'+t['key']+'/environment/input/'+im['path']
   figures.append(f'<figure><a href="{esc(url)}"><img src="{esc(url)}" loading="lazy" alt="{esc(t["title"])} {im["id"]}"></a><figcaption>{esc(im["id"])} · {im["width"]}×{im["height"]}<br><a href="{esc(source["source"])}">{esc(credit)}</a> · {esc(license)}</figcaption></figure>')
  mode='截图复刻' if refs['images'] else '文字生成'
  parts.append(f'''<article id="{t['key']}"><header><span>{t['key']} · {mode} · {len(contract['entities'])} 个指定交互对象</span><h2>{esc(t['title'])}</h2></header><div class="images">{''.join(figures) or '<p>按文字需求设计场景，无参考图片。</p>'}</div><div class="statements"><section><h3>中文题面</h3><pre>{esc((folder/'instruction.zh.md').read_text())}</pre></section><section><h3>English — actual task statement</h3><pre lang="en">{esc((folder/'instruction.md').read_text())}</pre></section></div><details><summary>公开交互接口与初始状态</summary><pre>{esc(json.dumps(contract,ensure_ascii=False,indent=2))}</pre></details><details><summary>离线素材推荐</summary><pre>{esc(json.dumps(sel,ensure_ascii=False,indent=2))}</pre></details><p><a href="tasks/{t['key']}/PROMPT.md">完整英文输入</a> · <a href="tasks/{t['key']}/environment/input/INTEGRATION.md">UE 接口</a> · <a href="tasks/{t['key']}/environment/input/ASSETS.md">素材使用</a> · <a href="tasks/{t['key']}/package-manifest.json">文件清单</a></p><p>待生成 · 待评测 · 暂无成绩</p></article>''')
 nav=''.join(f'<a href="#{t["key"]}">{esc(t["title"])}</a>' for t in idx['tasks'])
 doc='''<!doctype html><html lang="zh"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>L3 · 14 道任务输入</title><style>body{font:16px/1.65 system-ui,sans-serif;background:#f3f5f8;color:#18243b;margin:0}main{max-width:1500px;margin:auto;padding:32px}h1{font-size:34px}h2{font-size:25px}h3{font-size:17px}a{color:#1956a5}nav{display:flex;flex-wrap:wrap;gap:8px}nav a{background:white;border:1px solid #d3dce7;border-radius:8px;padding:5px 10px;text-decoration:none}article{background:#fff;border:1px solid #d6dfe8;border-radius:14px;margin:28px 0;padding:25px;scroll-margin-top:12px}header span{font-size:14px;color:#576d86}.images{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:16px}figure{margin:0}img{width:100%;aspect-ratio:1.6;object-fit:contain;background:#e8edf2}figcaption{font-size:12px;color:#5c6c80}.statements{display:grid;grid-template-columns:1fr 1fr;gap:26px}pre{font:14px/1.8 system-ui,sans-serif;white-space:pre-wrap;overflow-wrap:anywhere}summary{cursor:pointer;font-weight:600;margin-top:14px}details pre{background:#f5f7fa;padding:14px}@media(max-width:850px){.statements{grid-template-columns:1fr}main{padding:16px}article{padding:16px}}</style><main><h1>L3 · 14 道任务输入</h1><p>全套共 15 题：游戏 6、具身 6、现实 3。Minecraft 有独立成品与成绩；此页提供其余 14 题的双语题面、23 张参考图及公开交互要求。</p><p>实际输入使用英文。共享离线库包含 869 套 PBR 材质、1,015 个模型。每题分别由 Luna 和 Astra 生成，共 28 次，使用相同输入与资源。</p><nav>'''+nav+'</nav>'+''.join(parts)+'</main></html>'
 (out/'index.html').write_text(doc)
 archive=BASE/'l3-fourteen-task-inputs.tar.gz'
 with tarfile.open(archive,'w:gz') as tar:
  tar.add(out,arcname='review');tar.add(BASE/'generation-batch.json',arcname='generation-batch.json')
  for t in idx['tasks']:tar.add(ROOT/t['path'],arcname=t['path'])
  for name in ['README.md','COMMON.md','COMMON.zh.md','task-index.json','generation-batch.json','RUNNING.md']:tar.add(ROOT/'tasks/L3'/name,arcname='tasks/L3/'+name)
 files={'archive':str(archive),'sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'bytes':archive.stat().st_size,'contains':'14 bilingual tasks, public integration, reference images, sources, asset selection and batch manifest; shared libraries are already installed on server'}
 (BASE/'delivery.json').write_text(json.dumps(files,ensure_ascii=False,indent=2)+'\n');print(json.dumps(files,ensure_ascii=False))
if __name__=='__main__':main()
