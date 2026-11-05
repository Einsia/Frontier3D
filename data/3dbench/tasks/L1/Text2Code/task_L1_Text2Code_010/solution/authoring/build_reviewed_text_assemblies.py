"""Repair documented assembly-fit issues in selected existing CC0 candidates."""
import sys,json
from pathlib import Path
R=Path(__file__).resolve().parents[1];sys.path.insert(0,str(R/'scripts'))
import build_assemblies as b
from assembly_catalog import assemblies
from mechanical_catalog import cyl
FAMILIES=['bearing_cartridge','camera_pan_tilt','filter_cartridge','lead_screw_stage','machine_vise','pulley_axle','roller_guide','rotary_table','sealed_enclosure','sliding_latch','telescopic_tube']
out=R/'assets/expansion/reviewed-text-assemblies';out.mkdir(parents=True,exist_ok=True)
# Reuse the verified builder without overwriting historical candidate files.
b.ROOT=out
for s in assemblies():
 if s['family'] not in FAMILIES:continue
 dest=out/'pilot-v2/assemblies'/s['family']
 if (dest/'qa.json').exists():continue
 parts={p['id']:p for p in s['parts']};changes=[]
 if s['family']=='camera_pan_tilt':
  p=parts['pan_bearing'];p['operations'][0]['height']=20;p['operations'][1]['height']=24;p['at'][2]=18
  p=parts['camera_platform'];p['operations'][0]['size'][2]=10;p['at'][2]=69;p['operations'][1]['at'][2]=0
  changes=['Pedestal extended from z=8 to 28 to support fork base.','Camera plate made 10 mm thick and centered on the tilt axis, giving a closed pin bore.']
 if s['family']=='lead_screw_stage':
  parts['lead_screw']['operations'][0]['height']=182
  for k in ['guide_bushing_0','guide_bushing_1']:parts[k]['operations'][0]['radius']=9
  changes=['Lead rod extended to 182 mm to enter the handwheel.','Guide sleeve OD increased to 18 mm so the sleeves support the platform underside at z=35.']
 if s['family']=='roller_guide':
  for i in range(4):
   p=parts[f'pin_{i}'];p['operations'][0]['height']=46;p['at'][2]=29
   parts['base']['operations'].append(cyl(4.2,4,(p['at'][0],p['at'][1],3),'difference'))
   p=parts[f'spacer_{i}'];p['operations'][0]['height']=13;p['operations'][1]['height']=17;p['at'][2]=14.5
  changes=['Pins start at z=6 in matching base recesses; 13 mm spacers now rest on the base and support the rollers at z=21.']
 if s['family']=='rotary_table':
  p=parts['sleeve'];p['operations'][0]['height']=11;p['operations'][1]['height']=15;p['at'][2]=13.5
  changes=['Sleeve supports disk underside at z=19.']
 if s['family']=='sealed_enclosure':
  for i in range(4):
   p=parts[f'standoff_{i}'];p['operations'][0]['height']=32.5;p['operations'][1]['height']=36.5;p['at'][2]=20.75
  changes=['Standoffs extend from the 4.5 mm floor to the lid underside at z=37.']
 b.build(s)
 (dest/'adaptation.json').write_text(json.dumps({'source':'pilot-v2/assemblies/'+s['family'],'license':'CC0-1.0','changes':changes,'review_scope':'Original candidate retained with stated fit repairs; not a manufacturing-certified mechanism.'},indent=2),encoding='utf-8')
