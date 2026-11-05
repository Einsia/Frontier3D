"""Public dimensions and fixed probes for serviceable boxes and hollow assemblies."""
import numpy as np
from .continuous_assembly_contracts import part,hole
from .continuous_assembly_layouts import layout,relation


def rectangle(item,width,depth,sections,clearance):
    item['rectangular_cavity']={'size_m':[width/1000,depth/1000],
        'section_spans_offset_m':(np.asarray(sections)/1000).tolist(),
        'clearance_span_offset_m':(np.asarray(clearance)/1000).tolist()}
    area=item['extent_m'][0]*item['extent_m'][1]-width*depth/1e6
    item['plane_area_overrides_m2']={'2/low':area,'2/high':area}
    return item


def electronics_box():
    mount=[(x,y) for x in (-40,40) for y in (-25,25)]
    body=part('body','body','box',[0,0,17.5],[100,70,35],holes=[
        hole('mount-'+str(i),2,4.4,[x,y,2.25],section_spans_offset_m=[[-.0175,-.013]],
             corridor_span_offset_m=[-.0175,-.013]) for i,(x,y) in enumerate(mount)])
    rectangle(body,92,62,[[-13,17.5]],[-12.69999,17.50001])
    body['plane_area_overrides_m2']['2/low']=.100*.070-4*np.pi*.0022**2
    body['line_probes']=[{'id':'floor-'+str(i)+'-'+str(j),'quantity_id':'floor_boundaries','axis':2,
        'origin_offset_m':[x*.046,y*.031,0.],'boundary_offsets_m':[-.0175,-.013]}
        for i,x in enumerate((-.75,-.25,.25,.75)) for j,y in enumerate((-.75,-.25,.25,.75))]
    gasket=rectangle(part('gasket','gasket','box',[0,0,36],[100,70,2]),92,62,[[-1,1]],[-1.00001,1.00001])
    lid=part('lid','lid','box',[0,0,39],[100,70,4],holes=[hole('mount-'+str(i),2,4.4,[x,y,39]) for i,(x,y) in enumerate(mount)])
    parts=[body,gasket,lid]
    for i,(x,y) in enumerate(mount):
        screw=part('bolt-'+str(i),'screws','bolt',[x,y,37.75],[7.2,7.2,17.5])
        screw.update(shank_diameter_m=.004,shank_length_m=.0135,head_diameter_m=.0072,head_height_m=.004)
        parts+=[part('standoff-'+str(i),'standoffs','tube',[x,y,20.75],[9,9,32.5],axis=2,diameter=9,
                     holes=[hole('screw',2,4.4,[x,y,20.75])]),screw,
                part('washer-'+str(i),'washers','tube',[x,y,41.75],[8,8,1.5],axis=2,diameter=8,
                     holes=[hole('screw',2,4.4,[x,y,41.75])])]
    relations=[relation('gasket_on_body','gasket','gasket','body',2),relation('lid_on_gasket','lid','lid','gasket',2),
        *[relation('standoff_meets_lid-'+str(i),'standoffs','lid','standoff-'+str(i),2) for i in range(4)]]
    return layout('008',parts,['body','gasket','lid','standoffs','screws','washers'],relations,
                  'standoff-0',[0,1],'standoffs','body')


def filter_display():
    housing=part('housing','housing','stepped_rotary',[0,0,43],[60,60,70],axis=2,holes=[hole('through',2,52,[0,0,43]),
        hole('lower_recess',2,59.4,[0,0,9.05],section_spans_offset_m=[[-.035,-.03320001]],corridor_span_offset_m=[-.035,-.03320001]),
        hole('upper_recess',2,59.4,[0,0,76.95],section_spans_offset_m=[[.03320001,.035]],corridor_span_offset_m=[.03320001,.035])])
    housing['outer_profile']=[{'id':'outside','diameter_m':.060,'span_offset_m':[-.035,.035]}]
    housing['axial_profile_probes']=[{'id':'recess_depths','radius_m':.02785,'boundary_offsets_m':[-.0329,.0329]}]
    parts=[housing,part('filter','filter','tube',[0,0,43],[42,42,62],axis=2,diameter=42,holes=[hole('rod',2,14,[0,0,43])])]
    for i,z in enumerate((4,82)):
        parts.append(part('cap-'+str(i),'caps','tube',[0,0,z],[68,68,8],axis=2,diameter=68,holes=[hole('rod',2,10.4,[0,0,z])]))
    for i,z in enumerate((9,77)):
        parts.append(part('seal-'+str(i),'seals','tube',[0,0,z],[59,59,2],axis=2,diameter=59,holes=[hole('opening',2,52.6,[0,0,z])]))
    parts+=[part('rod','tie_rod','cylinder',[0,0,43],[10,10,90],axis=2,diameter=10),
            part('nut','nut','tube',[0,0,90],[18,18,5],axis=2,diameter=18,holes=[hole('rod',2,10.4,[0,0,90])]),
            part('washer','washer','tube',[0,0,-3],[22,22,2],axis=2,diameter=22,holes=[hole('rod',2,10.4,[0,0,-3])])]
    result=layout('009',parts,['housing','filter','caps','seals','tie_rod','nut','washer'],
        [relation('lower_cap_contact','caps','housing','cap-0',2),relation('upper_cap_contact','caps','cap-1','housing',2)],
        'rod',[0,1],'tie_rod','housing')
    result.update(control_overlap_roles=['cap-1','housing'],control_overlap_shift_m=[0.,0.,-.002])
    return result


def telescopic_tube():
    outer=rectangle(part('outer','outer_tube','box',[0,0,40],[44,44,80],holes=[hole('pin',0,6.4,[0,0,66],group='pin_clearance',
        section_spans_offset_m=[[-.022,-.018],[.018,.022]])]),36,36,[[-40,40]],[-40.00001,40.00001])
    inner=rectangle(part('inner','inner_tube','box',[0,0,85],[32,32,90],holes=[hole('pin',0,6.4,[0,0,66],group='pin_clearance',
        section_spans_offset_m=[[-.016,-.013],[.013,.016]])]),26,26,[[-45,45]],[-45.00001,45.00001])
    lower=rectangle(part('guide-0','guides','box',[0,0,8],[35.6,35.6,8]),32.4,32.4,[[-4,4]],[-4.00001,4.00001])
    upper=rectangle(part('guide-1','guides','box',[0,0,70],[35.6,35.6,8],holes=[
        hole('pin_notch',0,6.4,[0,0,66],kind='open_notch',group='pin_clearance',face_area_fraction=.5,
             section_spans_offset_m=[[-.0178,-.0162],[.0162,.0178]])]),32.4,32.4,[[-.49999,4]],[-4.00001,4.00001])
    upper['plane_area_overrides_m2']['2/low']-=2*.0064*.0016
    parts=[outer,inner,lower,upper,
        part('plug','plug','box',[0,0,-2.5],[43,43,5]),part('cap','cap','box',[0,0,132],[34,34,4]),
        part('pin','pin','cylinder',[0,0,66],[58,6,6],axis=0,diameter=6)]
    for i,x in enumerate((-30,30)):
        parts.append(part('retainer-'+str(i),'retainers','tube',[x,0,66],[2,12,12],axis=0,diameter=12,
                          holes=[hole('pin',0,6.4,[x,0,66])]))
    result=layout('010',parts,['outer_tube','inner_tube','guides','plug','cap','pin','pin_clearance','retainers'],
        [relation('bottom_plug_contact','plug','outer','plug',2),relation('top_cap_contact','cap','cap','inner',2)],
        'pin',[1,2],'pin','outer_tube')
    result.update(control_overlap_roles=['pin','outer'],control_overlap_shift_m=[0.,.002,0.])
    return result


def roller_guide():
    centers=[(-28,0),(28,0),(0,-28),(0,28)]
    base=part('base','base','box',[0,0,4],[120,120,8],holes=[
        hole('blind-'+str(i),2,8.4,[x,y,6.5],also_groups=['bore_topology'],
             section_spans_offset_m=[[.00130001,.004]],corridor_span_offset_m=[.00130001,.00400001])
        for i,(x,y) in enumerate(centers)])
    base['plane_area_overrides_m2']={'2/low':.120**2}
    base['line_probes']=[]
    for i,(x,y) in enumerate(centers):
        for j,angle in enumerate(np.arange(16)*2*np.pi/16):
            base['line_probes'].append({'id':'blind-'+str(i)+'-'+str(j),'quantity_id':'blind_floor-'+str(i),'axis':2,
                'origin_offset_m':[x/1000+.002*np.cos(angle),y/1000+.002*np.sin(angle),0.],
                'boundary_offsets_m':[-.004,.001],'also_groups':['bore_topology']})
    parts=[base,part('workpiece','workpiece','box',[0,0,33],[30,30,50])];relations=[]
    for i,(x,y) in enumerate(centers):
        parts+=[part('roller-'+str(i),'rollers','tube',[x,y,35],[25,25,28],axis=2,diameter=25,
                     holes=[hole('pin',2,8.4,[x,y,35],also_groups=['bore_topology'])]),
                part('pin-'+str(i),'pins','cylinder',[x,y,29],[8,8,46],axis=2,diameter=8),
                part('spacer-'+str(i),'spacers','tube',[x,y,14.5],[14,14,13],axis=2,diameter=14,
                     holes=[hole('pin',2,8.4,[x,y,14.5],also_groups=['bore_topology'])])]
        axis=0 if x else 1;positive=x>0 or y>0
        left,right=('roller-'+str(i),'workpiece') if positive else ('workpiece','roller-'+str(i))
        relations+=[relation('workpiece_gap-'+str(i),'rollers',left,right,axis,gap=.5),
                    relation('roller_on_spacer-'+str(i),'spacers','roller-'+str(i),'spacer-'+str(i),2)]
    result=layout('012',parts,['base','workpiece','rollers','pins','spacers','bore_topology'],relations,
                  'pin-0',[0,1],'pins')
    result.update(control_overlap_roles=['spacer-0','roller-0'],control_overlap_shift_m=[0.,0.,.002])
    return result
