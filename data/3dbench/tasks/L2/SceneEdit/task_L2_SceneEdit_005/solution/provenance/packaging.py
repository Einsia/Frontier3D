from pathlib import Path
import json,shutil,sys,hashlib
from PIL import Image,ImageDraw,ImageFont
from cc0_author_cases import CASES
R=Path(__file__).resolve().parents[1];REPO=R/'dist/gitlab-3dbench';OUT=R/'docs/resource-expansion-20260918';ARC=R/'drafts/replaced-attribution-tasks-20260921'
AUTHORS={'home-bedroom':'DREAM_SEARCH_REPEAT','home-kitchen':'DREAM_SEARCH_REPEAT','3d-city':'zonked','medieval-blacksmith':'Daniel Andersson','medieval-dungeon-interior':'cheerful sprite'}
def write(p,t):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(t,encoding='utf-8')
def copy(p,q):q.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,q)
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
contracts={}
for lang,fn in [('en','instruction.md'),('zh','instruction.zh.md')]:
 t=(REPO/'tasks/L2/Reference2Scene'/fn).read_text(encoding='utf-8');contracts[lang]=t[t.index('## Submission contract'):] if lang=='en' else t[t.rfind('## '):]
rows=[]
for c in CASES:
 if c['key']=='attic-hideout':c['difficulty']='easy'
 base=R/'assets/cc0-replacements-20260921'/c['key'];prep=base/'prepared';edit=c['category']=='SceneEdit';brief=c['category']=='Brief2Scene';data=base/'pair' if edit else prep
 assert (data/('reference.blend' if edit else 'scene.blend')).is_file()
 if edit:assert json.loads((data/'pair-audit.json').read_text())['preserved_objects_equal']
 dest=REPO/'tasks/L2'/c['slug'];dest.mkdir(parents=True,exist_ok=True)
 source=json.loads((base/'source.json').read_text(encoding='utf-8'));source['author']=source.get('author',AUTHORS.get(c['key'],'Unknown'));assert source['author']!='Unknown'
 source['license']='CC0-1.0';source['resource_family']='upstream/'+c['key'];url=source['source_page'];img=data/('reference.png' if edit else 'main.png');w,h=Image.open(img).size
 copy(data/('reference.blend' if edit else 'scene.blend'),dest/'solution/reference/scene.blend');copy(img,dest/'solution/reference/main.png')
 for p in [base/'publisher.html',prep/'preparation.json',prep/'resource-deduplication.json']:
  if p.exists():copy(p,dest/'solution/provenance'/p.name)
 native=OUT/'native-scenes'/('final-cc0-'+c['key']+'.json');copy(native,dest/'solution/reference/native-audit.json')
 audit=json.loads(native.read_text(encoding='utf-8'));assert not audit['libraries'];assert all(im['packed'] or im['external_exists'] for im in audit['images'])
 source['packaged_scene_sha256']=sha(dest/'solution/reference/scene.blend');source['changes']='Author geometry/layout retained; render normalization and documented exclusions of shared resources. SceneEdit additionally removes listed target objects or perturbs existing lighting. No generated replacement assets.'
 write(dest/'solution/provenance/source.json',json.dumps(source,ensure_ascii=False,indent=2));copy(Path(__file__),dest/'solution/provenance/packaging.py');copy(R/'scripts/prepare_cc0_author_scene.py',dest/'solution/provenance/preparation.py')
 credit=f"{source.get('title',c['key'])}\nAuthor: {source['author']}\nSource: {url}\nCC0-1.0; attribution is not required.\nhttps://creativecommons.org/publicdomain/zero/1.0/\n"
 write(dest/'solution/provenance/LICENSE.txt',credit)
 env=[]
 if not brief:
  copy(img,dest/'environment/input/reference.png');env=['input/reference.png']
  write(dest/'environment/input/SOURCE.txt',credit);env+=['input/SOURCE.txt']
 else:write(dest/'environment/input/.gitkeep','')
 if edit:
  copy(data/'initial.blend',dest/'environment/input/initial.blend');env.insert(0,'input/initial.blend');copy(data/'initial.png',dest/'solution/reference/initial.png')
  for name in ['pair-audit.json','preserved-baseline.json']:copy(data/name,dest/'solution/annotations'/name)
  copy(R/'scripts/build_cc0_author_edit_pairs.py',dest/'solution/provenance/pair-preparation.py');copy(R/'scripts/cc0_author_cases.py',dest/'solution/provenance/cases.py')
  a=Image.open(img).convert('RGB');b=Image.open(data/'initial.png').convert('RGB');width=800;height=round(a.height*width/a.width);plate=Image.new('RGB',(width*2,height+42),'white');plate.paste(a.resize((width,height)),(0,42));plate.paste(b.resize((width,height)),(width,42));d=ImageDraw.Draw(plate);font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',24);d.text((12,8),'COMPLETE REFERENCE',fill='black',font=font);d.text((width+12,8),'ACTUAL MODEL INPUT SCENE',fill='black',font=font);plate.save(dest/'solution/reference/comparison.png')
 for lang,fn in [('en','instruction.md'),('zh','instruction.zh.md')]:
  if edit:
   common=('Start from input/initial.blend. Use the single reference image. Preserve all scene data outside the changes explicitly allowed above, including cameras and render/color settings. Render main.png from the supplied camera. Duplicate that camera and move it 0.30 m along its local positive X axis without changing lens or rotation to render alternate.png. Keep both cameras in the same edited scene. Pack all dependencies. Hidden details may be completed plausibly.' if lang=='en' else '从 input/initial.blend 开始，使用唯一参考图。保留上文允许修改范围以外的全部场景数据，包括相机和渲染、色彩设置。给定主相机渲染 main.png；复制主相机，沿局部 X 正方向平移 0.30 m，镜头及旋转不变，渲染 alternate.png。两个相机保存在同一编辑后的场景中，全部依赖打包。隐藏细节可合理补全。')
  elif not brief:
   cam='orthographic' if c['key'] in ['3d-city','voxel-atolls'] else 'perspective';camzh='正交' if cam=='orthographic' else '透视';engine='Eevee' if audit['engine'].startswith('BLENDER') else 'Cycles'
   common=(f'Use metres and Z up. The stated size is a task convention, not a measurement of the author scene. Keep main objects independently editable and pack texture dependencies. Complete unseen areas plausibly; exact source object names, hidden dimensions and topology are not required. Match the supplied composition with a {cam} main camera. Duplicate it and translate it 0.30 m along local positive X, retaining projection, lens/orthographic scale and rotation, to make an alternate camera. Keep both cameras and render both views from the same scene at {w} by {h} pixels with {engine}, {audit["view_transform"]}, exposure {audit["exposure"]:g}, gamma 1. The alternate view has no target image and checks 3D consistency.' if lang=='en' else f'使用米制和 Z 向上。给定尺寸是任务约定，不是源场景测量值。主要物体独立可编辑，纹理依赖打包。隐藏区域合理补全，不要求源对象名称、隐藏尺寸或原拓扑。以{camzh}主相机匹配构图；复制相机，沿局部 X 正方向平移 0.30 m，投影方式、镜头或正交尺度及旋转保持不变，作为备用相机。保留两个相机，从同一场景以 {engine}、{audit["view_transform"]}、曝光 {audit["exposure"]:g}、gamma 1 渲染 {w}×{h} 双图。备用视角没有目标图，仅检查三维一致性。')
  else:common=('Keep both cameras in the native scene, keep major structures independently editable and pack dependencies.' if lang=='en' else '原生场景保留两个相机，主要结构独立可编辑，依赖打包。')
  restriction=('Use only supplied inputs to establish this scene. Do not retrieve the original complete model or additional views online. Do not replace three-dimensional structures with the entire reference projected onto planes.' if lang=='en' else '仅用提供的输入确定此场景，不联网取回原完整工程或额外视图，不能将完整参考图投到平面上代替三维结构。')
  write(dest/fn,c[lang]+'\n\n'+common+'\n\n'+restriction+'\n\n'+contracts[lang])
 files=['output/solution.py','output/scene.blend','output/main.png','output/alternate.png','output/README.md']
 write(dest/'task.toml',f'''version = 1
id = "L2/{c['slug']}"
level = 2
category = "{c['category']}"
title = "{c['title']}"
difficulty = "{c['difficulty']}"
status = "ready_for_review"
instruction = "instruction.md"
review_instruction = "instruction.zh.md"
environment = "environment"
solution = "solution"
harness = "harness"
harness_status = "not_implemented"
resource_family = "upstream/{c['key']}"
environment_files = {json.dumps(env)}
submission_root = "output"
submission_files = {json.dumps(files)}
entrypoint = "output/solution.py"
''');write(dest/'harness/.gitkeep','')
 io=('输入：修改后的原生场景、单张完整参考图和文字修改要求。输出：编辑代码、Blender 工程和双视图。' if edit else '输入：纯文字要求，不给参考图和原模型。输出：生成代码、Blender 工程和双视图。' if brief else '输入：单张场景渲染参考图及文字要求。输出：生成代码、Blender 工程和双视图。')
 image=dest/'solution/reference/comparison.png' if edit else dest/'solution/reference/main.png' if brief else dest/'environment/input/reference.png'
 scope=('原生完整工程及目标参数仅供评测侧；先检查非目标内容保持，再评价局部修改。' if edit else '作者原场景仅供理解风格和设计复杂度，不是布局或像素 GT；按公开题面约束评价允许的不同布局。' if brief else '原生工程为私有参考；单视图重建不唯一，隐藏几何和源拓扑不能作为硬性答案。')
 write(dest/'README.md',f'''# {c['title']}

{c['features']}。{io}

| 内容 | 路径与用途 |
|---|---|
| 模型输入 | instruction.md；environment/input 映射为工作区 input；{', '.join(env) if env else '无输入资产'} |
| 统一交付 | output/solution.py、scene.blend、main.png、alternate.png、README.md；可选 output/assets/ |
| 私有参考 | solution/reference/scene.blend、main.png、native-audit.json；{'annotations 内保存删除目标或原参数及保持性基线' if edit else 'provenance 保存来源、许可与处理记录'} |
| 筛选与评测 | instruction.zh.md 是等价中文；solution/EVALUATION.md 是 evaluator 接口说明；harness 暂空 |

{scope} solution 不提供给模型。

![{'左为完整参考，右为实际输入状态' if edit else '仅供评审的原作者场景，不提供给模型' if brief else '唯一图像输入'}]({image.relative_to(dest).as_posix()})

来源：[{source['author']}]({url})，CC0-1.0，无署名义务。使用网上已有作者资产；原始几何不是本轮生成。依赖修复、取景、重复资产剔除及删件/参数扰动记录在 provenance。数据已做原生完整性检查，尚未模型实测。
''')
 write(dest/'solution/EVALUATION.md',f'''# 评测接口：{c['title']}

公开要求全部在 instruction.md。重点：{c['features']}。{scope}

| 维度 | 要测什么 | evaluator 如何接入 |
|---|---|---|
| 文件与可执行性 | 固定输出齐全；脚本能从干净输入执行；无缺失依赖 | 按 instruction 命令执行，离线重开 scene.blend 并重新渲染两张图；核对提交图来自该工程。 |
| 需求覆盖 | 上述语义结构和明确尺寸/编辑范围 | 将题面清单映射为评测侧区域或几何测量，不依赖模型自取对象名。 |
| 几何与空间 | 有体积的结构、开口与厚度、支撑/接触、穿透和空间层次 | 表面采样、BVH 和连通/间距测量。{'根据完整参考按可见目标分区，避免全图平均掩盖局部失误。' if edit else '按题目尺度和可见地标对齐后比较可见表面；隐藏面允许合理解。' if not brief else '检查通道连通、最小净宽、岩拱净跨与植被分区；不要求和示例布局相同。'} |
| 视觉 | 构图、轮廓、材质颜色、受光和阴影层次 | 使用提交工程重渲染；分别报告区域轮廓、Lab 色彩及亮暗分布。允许简化的文字或小细节不按像素硬判。 |
| {'非目标保持' if edit else '跨视角一致'} | {'保留对象、几何、变换、材质、相机及灯的非允许参数' if edit else '同一真实三维场景形成双图，相机满足题面'} | {'先对 initial.blend 和 annotations/preserved-baseline.json 做哈希粗查，再检查语义等价。允许目标编辑引起的自然反射和阴影变化；不能把它算成改了保留资产。' if edit else '检查相机矩阵与几何视差，防止图像平面或分别为两张图建立不同场景。'} |
| 可复现与可编辑 | 重复执行稳定、主要结构可编辑、资产自包含 | 第二次从干净目录执行，比较场景结构及渲染；不能读取私有 solution 或从网络取回源工程。 |
| 效率 | 时间、token、调用次数、失败重试 | Harness 统一采集，和质量分开汇报。 |

所有指标是实现接口，不是已完成评分。参考源的对象名、网格拆分或灯光精确数值只供诊断，不作为唯一合法答案。容差、区域权重和通过阈值须在 evaluator 实现后用 pilot 校准。
''')
 old=REPO/'tasks/L2'/c['old']
 if old.exists():
  ARC.mkdir(exist_ok=True);target=ARC/old.name;assert not target.exists();assert old.resolve().is_relative_to((REPO/'tasks/L2').resolve());shutil.move(str(old),str(target))
 rows.append({**{k:c[k] for k in ['key','slug','category','title','difficulty','features']},'old_slug':c['old'],'image':image.relative_to(R).as_posix(),'source':url,'author':source['author'],'license':'CC0-1.0','io':io+scope})
 print('MANAGED_AUTHOR_REPLACEMENT',c['slug'],flush=True)
write(OUT/'cc0-author-replacements.json',json.dumps(rows,ensure_ascii=False,indent=2))
