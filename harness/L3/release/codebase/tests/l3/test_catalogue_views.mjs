import test from 'node:test';
import assert from 'node:assert/strict';
import {l3Content} from '../../website/l3-catalog/public/l3-design.js';

const models=['gpt-6-astra','gpt-6-luna','gpt-6-sol'];
function task(){
 return {key:'l3-g01',input_mode:'image',generation_as_of_utc:'2026-10-27T00:00:00Z',
 generation_runs:models.map(model=>({model,images:[],score:25,status_label:'已生成',seconds:60,usage:{reported_tokens:{input_tokens:100,output_tokens:20}}})),
 evaluation_results:models.map(model=>({model,score_100:25,weights:{layout:1},axes:{layout:{score:.25}},
 evidence_links:{'summary.json':'/downloads/'+model},source:{trial:'/data/'+model},protocol:'l3-test'}))};
}
test('MC current cohort overrides legacy views and displays each model score',()=>{
 const t=task();
 for(const tab of ['overview','scores','notes']){
  const html=l3Content(t,tab,'cn');
  assert.ok(!html.includes('gpt-5.6-luna'));
  assert.ok(!html.includes('undefined'));
  if(tab!=='notes')for(const model of models)assert.ok(html.includes(model));
 }
 const scores=l3Content(t,'scores','cn');
 assert.equal((scores.match(/总分 25.00 \/ 100/g)||[]).length,3);
 assert.ok(scores.includes('拟合参考相机'));
 assert.ok(!scores.includes('文字题不计'));
});
test('suite counts remain per model and text tasks omit reference scoring',()=>{
 const t=task();t.key='l3-e05';t.input_mode='text';
 t.evaluation_results.forEach((r,i)=>{r.counts={required_entities:i+1,navigation_segments:4,workflow_passed_predicates:2,workflow_predicates:3};});
 const scores=l3Content(t,'scores','cn');
 for(const count of [1,2,3])assert.ok(scores.includes(count+' 个规定交互对象'));
 assert.ok(scores.includes('文字题不计参考图一致性分'));
});
