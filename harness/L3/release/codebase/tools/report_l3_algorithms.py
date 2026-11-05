"""Verify source/evidence bindings and publish replayable pilot metric reports."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from harness.L3.MinecraftVillage.protocol import read_json,write_json,digest,tree_digest
from harness.L3.MinecraftVillage.algorithm_scores import summarize,POLICY
from harness.L3.MinecraftVillage.evaluate import journey_diagnostics


def optional(p):return read_json(p) if p.exists() else {'status':'not_measured'}


def report(trial,run,output):
    r=read_json(run/'run.json');source=tree_digest(trial/'workspace/project')
    if r['source_sha256']!=source:raise ValueError('Candidate changed')
    visual=optional(output/'visual/summary.json');cap=optional(output/'capture/capture.json')
    for manifest in [r,cap]:
        for rel,sha in manifest.get('evidence_sha256',{}).items():
            p=(run/rel).resolve()
            if not p.is_relative_to(run.resolve()) or digest(p)!=sha:raise ValueError('Evidence changed '+rel)
    if visual.get('status')=='measured':
        if visual['source_sha256']!=source:raise ValueError('Visual judgment belongs to another candidate')
        for name,sha in visual['original_images'].items():
            if digest(Path(name))!=sha:raise ValueError('Visual source changed')
    reference=optional(output/'capture/reference-fitted/scores.json')
    if reference.get('method'):
        folder=run/'workspace/algorithm-v1/fitted_reference'
        if reference['candidate_sha256']!=digest(folder/'reference_rgb.png') or reference['mask_sha256']!=digest(folder/'reference_mask.png'):
            raise ValueError('Reference score does not bind captured evidence')
    flow=optional(output/'capture/workflow.json');doors=optional(output/'capture/door-walk.json')
    score_run=run/'run.json';score_geometry=output/'geometry/geometry.json';resource=optional(run/'resource-chain.json')
    runtime=output/'runtime-geometry-v2';runtime_record=optional(runtime/'run.json')
    if runtime_record.get('status')=='measured':
        if runtime_record['source_sha256']!=source or runtime_record['verification_source_sha256']!=r['verification_source_sha256']:
            raise ValueError('Runtime geometry-pose evidence belongs to another candidate')
        for rel,sha in runtime_record['evidence_sha256'].items():
            p=(run/rel).resolve()
            if not p.is_relative_to(run.resolve()) or digest(p)!=sha:raise ValueError('Runtime evidence changed '+rel)
        for rel,sha in runtime_record['diagnostics_sha256'].items():
            p=(runtime/rel).resolve()
            if not p.is_relative_to(runtime.resolve()) or digest(p)!=sha:raise ValueError('Runtime diagnostics changed '+rel)
        effective={**r,'episodes':{**r['episodes'],**runtime_record['episodes']}}
        geometry=read_json(score_geometry);geometry['motion']=read_json(runtime/'motion.json')
        score_run=runtime/'effective-run.json';score_geometry=runtime/'effective-geometry.json'
        write_json(score_run,effective);write_json(score_geometry,geometry)
        flow=read_json(runtime/'workflow.json');doors=read_json(runtime/'door-walk.json');resource=read_json(runtime/'resource-chain.json')
    else:
        raise ValueError('Complete geometry-derived runtime measurement is required before publishing interaction scores')
    journey=journey_diagnostics(run/'workspace/episodes/journey') if r.get('episodes',{}).get('journey',{}).get('completed') else None
    result=summarize(score_run,output/'geometry/physical-scene.json',score_geometry,flow,reference,visual,
                     resource,door_walk=doors,journey=journey)
    result['runtime_measurement']={'method':'geometry_derived_interaction_poses_v1','path':str(runtime),
        'run_sha256':digest(runtime/'run.json'),'seconds':runtime_record.get('elapsed_seconds')} if runtime_record.get('status')=='measured' else None
    result.update(trial=str(trial),model=read_json(trial/'trial.json')['model'],source_sha256=source,
                  verification=str(run),reference=reference,visual=visual,workflow=flow,doors=doors,
                  submitted_reference=optional(output/'capture/reference-submitted/scores.json'),
                  generation_seconds=read_json(trial/'trial.json').get('elapsed_seconds'),
                  source_scope='Frozen final submission, independent evaluator copy; no manual candidate edits')
    root=Path(__file__).resolve().parents[1]
    files=list((root/'harness/L3/MinecraftVillage').glob('algorithm_*.py'))+[root/'tools/capture_l3_algorithms.py',Path(__file__)]
    files += [root/name for name in ['src/evaluator/l2_reference_image.py','src/evaluator/l2_reference_boxes.py',
        'src/evaluator/l2_physical.py','harness/L3/MinecraftVillage/scene_geometry.py',
        'harness/L3/MinecraftVillage/support.py','harness/L3/MinecraftVillage/inventory.py',
        'harness/L3/MinecraftVillage/resource_chain.py','harness/L3/MinecraftVillage/evaluate.py',
        'tools/verify_l3_submission.py','tools/repair_l3_runtime.py','harness/L3/MinecraftVillage/geometry_routes.py'] if (root/name).exists()]
    result['implementation_sha256']={str(p.relative_to(root)):digest(p) for p in files}
    result['evaluation_timing']={'geometry_seconds':optional(output/'geometry/geometry.json').get('elapsed_seconds'),
        'supplemental_capture_seconds':cap.get('elapsed_seconds'),'capture_episodes':cap.get('episodes'),
        'visual_seconds':visual.get('elapsed_seconds'),
        'scope':'Stage wall times; supplemental captures exclude base build/21 episodes and are not end-to-end evaluation latency.'}
    result['evaluation_usage']=[a.get('usage') for a in visual.get('attempts',[])]
    result['formal_score_reason']='Reference annotations and cross-level human calibration pending.'
    write_json(output/'report.json',result)
    labels={'layout':'空间与布局','interaction':'交互正确性','environment':'整体参考复刻','objects':'关键建筑一致性','rubric':'主观质量与需求'}
    lines=['# Minecraft L3 评测报告','',f"模型：{result['model']}。协议：{POLICY['version']}。",'',

           '| 板块 | 权重 | 分项 /100 | 总分贡献 |','|---|---:|---:|---:|']
    for key,weight in POLICY['image_weights'].items():
        value=result['axes'][key]['score']
        lines.append(f"| {labels[key]} | {weight:.0%} | {'待测/证据不足' if value is None else f'{100*value:.2f}'} | {'—' if value is None else f'{100*weight*value:.2f}'} |")
    score=result['pilot_score_100'];lo,hi=result['partial_bounds_100']
    lines+=['',f"总分：{score:.2f}/100。" if score is not None else "总分：待补测。连续流程未完整测量，已测分项如下；缺测项不补零。",'',
            '## 测量范围','',
            '- 几何：支撑连通、独立物体与活动部件交叠；静态结构组合按冻结规则处理。',
            '- 交互：真实角色通行、机构运动、资源状态、连续流程；返回成功字符串不构成通过证据。',
            '- 参考：全局相机拟合后计算图像、定位与局部一致性；保留提交相机结果。仅公开可见二维内容，关键物体范围为 11 个标注建筑。',
            '- 视觉：gpt-6-astra / medium，一次整表判断，技术重试留档；Astra 作品存在同模型裁判条件。','',
            f"完整逐项证据：[report.json](report.json)。源工程 SHA256：`{source}`。"]
    (output/'report.zh.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps({'model':result['model'],'pilot_score_100':score,'partial_bounds_100':[lo,hi],'missing_axes':result['missing_axes']},ensure_ascii=False))
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser()
    for k in ['trial','run','output']:p.add_argument('--'+k,type=Path,required=True)
    a=p.parse_args();report(a.trial.resolve(),a.run.resolve(),a.output.resolve())
