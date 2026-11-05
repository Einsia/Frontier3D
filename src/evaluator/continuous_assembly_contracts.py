"""Task-specific public dimensions; no reference mesh is used as a hidden target."""
import numpy as np


def part(role,group,kind,center,extent,*,axis=None,diameter=None,holes=()):
    result={'role':role,'group':group,'kind':kind,'center_m':(np.asarray(center)/1000).tolist(),
            'extent_m':(np.asarray(extent)/1000).tolist(),'holes':list(holes)}
    if axis is not None:result['axis']=axis
    if diameter is not None:result['diameter_m']=diameter/1000
    return result


def hole(name,axis,diameter,center,**extra):
    return {'id':name,'axis':axis,'diameter_m':diameter/1000,'center_m':(np.asarray(center)/1000).tolist(),**extra}


def stage():
    parts=[part('base','base','box',[0,0,3],[170,100,6])]
    for i,y in enumerate((-30,30)):
        parts+=[part('guide-'+str(i),'guide_rods','cylinder',[0,y,26],[150,8,8],axis=0,diameter=8),
                part('sleeve-'+str(i),'guide_sleeves','tube',[0,y,26],[40,18,18],axis=0,diameter=18,
                     holes=[hole('guide',0,8.4,[0,y,26])])]
    parts+=[part('lead','lead_rod','cylinder',[0,0,26],[182,10,10],axis=0,diameter=10),
            part('nut','nut_block','box',[0,0,26],[24,22,18],holes=[hole('drive',0,10.4,[0,0,26])]),
            part('platform','platform','box',[0,0,38],[58,86,6])]
    for i,x in enumerate((-76,76)):
        parts.append(part('support-'+str(i),'end_supports','box',[x,0,24],[12,90,36],
                          holes=[hole('passage-'+str(j),0,d,[x,y,26]) for j,(y,d) in enumerate(((-30,8.4),(0,10.4),(30,8.4)))]))
    parts.append(part('handwheel','handwheel','tube',[88,0,26],[6,36,36],axis=0,diameter=36,
                      holes=[hole('drive',0,10.4,[88,0,26])]))
    relations=[{'id':'platform-'+r,'group':'platform','roles':['platform',r],
                'axis':2,'bounds':['low','high'],'difference_m':0.} for r in ('nut','sleeve-0','sleeve-1')]
    relations.append({'id':'lead_reaches_outer_wheel','group':'handwheel','roles':['lead','handwheel'],
                      'axis':0,'bounds':['high','high'],'difference_m':0.})
    return {'task_id':'L1/Text2Code/task_L1_Text2Code_003','parts':parts,'relations':relations,
            'numeric_groups':['part_roles','base','guide_rods','guide_sleeves','lead_rod','nut_block',
                              'platform','end_supports','handwheel','assembly_clearance'],
            'tolerance_m':.0003,'state_separation_half_scale_m':.00182,
            'negative_dimension_role':'lead','negative_dimension_axes':[1,2],
            'negative_dimension_group':'lead_rod','control_overlap_roles':['platform','nut'],
            'control_overlap_shift_m':[0.,0.,-.002],
            'assignment':'one-to-one extent and public world-centre cost; no object-name target',
            'registration':'fixed_format_conversion_only','physics_scoring':False}


def vise():
    parts=[part('base','base','box',[0,0,5],[160,90,10])]
    for i,(x,lx) in enumerate(((-60,-49.5),(20,9.5))):
        parts+=[part('jaw-'+str(i),'jaws','box',[x,0,35],[18,76,50],
                    holes=[hole('passage-'+str(j),0,d,[x,y,27]) for j,(y,d) in enumerate(((-25,8.4),(0,10.4),(25,8.4)))]),
                part('liner-'+str(i),'liners','box',[lx,0,50],[3,76,20])]
    for i,y in enumerate((-25,25)):
        parts.append(part('guide-'+str(i),'guide_rods','cylinder',[0,y,27],[130,8,8],axis=0,diameter=8))
    parts.append(part('drive','drive_rod','cylinder',[0,0,27],[150,10,10],axis=0,diameter=10))
    # 0.3 mm margins exclude only the public intersection windows and the
    # curved outer rim where a complete transverse circle cannot exist.
    x_spans=[[-.006,-.0035],[.0035,.006]]
    outer_y=float(np.sqrt(.010**2-.0032**2)-.0003)
    y_spans=[[-outer_y,-.0055],[.0055,outer_y]]
    hub=part('hub','hub','tube',[81,0,27],[12,20,20],axis=0,diameter=20,
        holes=[hole('drive',0,10.4,[81,0,27],section_spans_offset_m=x_spans),
               hole('crossbar',1,6.4,[81,0,27],section_spans_offset_m=y_spans)])
    hub['outer_section_spans_offset_m']=x_spans;parts.append(hub)
    parts.append(part('crossbar','crossbar','cylinder',[81,0,27],[6,70,6],axis=1,diameter=6))
    relations=[{'id':'left_liner_face','group':'liners','roles':['liner-0','jaw-0'],'axis':0,'bounds':['low','high'],'difference_m':0.},
               {'id':'right_liner_face','group':'liners','roles':['jaw-1','liner-1'],'axis':0,'bounds':['low','high'],'difference_m':0.},
               {'id':'drive_meets_hub','group':'hub','roles':['hub','drive'],'axis':0,'bounds':['low','high'],'difference_m':0.}]
    return {'task_id':'L1/Text2Code/task_L1_Text2Code_004','parts':parts,'relations':relations,
            'numeric_groups':['part_roles','base','jaws','liners','guide_rods','drive_rod','hub','crossbar','assembly_clearance'],
            'tolerance_m':.0003,'state_separation_half_scale_m':.00167,
            'negative_dimension_role':'drive','negative_dimension_axes':[1,2],
            'negative_dimension_group':'drive_rod','control_overlap_roles':['liner-0','jaw-0'],
            'control_overlap_shift_m':[-.002,0.,0.],
            'assignment':'one-to-one extent and public world-centre cost; no object-name target',
            'registration':'fixed_format_conversion_only','physics_scoring':False}


def fasteners(centers,base_top,shank_length,*,diameter=6,head_diameter=10.8,head_height=4):
    parts=[]
    for i,(x,y) in enumerate(centers):
        bolt=part('bolt-'+str(i),'fasteners','bolt',[x,y,(shank_length+head_height)/2],
                  [head_diameter,head_diameter,shank_length+head_height])
        bolt.update(shank_diameter_m=diameter/1000,shank_length_m=shank_length/1000,
                    head_diameter_m=head_diameter/1000,head_height_m=head_height/1000)
        parts+=[bolt,part('washer-'+str(i),'fasteners','tube',[x,y,base_top+.75],[12,12,1.5],axis=2,diameter=12,
                         holes=[hole('bolt',2,6.4,[x,y,base_top+.75])])]
    return parts


def pulley():
    centers=[(x,y) for x in (-30,30) for y in (-24,24)]
    parts=[part('base','base','box',[0,0,4],[80,70,8],
                holes=[hole('bolt-'+str(i),2,6.4,[x,y,4]) for i,(x,y) in enumerate(centers)])]
    for i,x in enumerate((-20,20)):
        parts.append(part('cheek-'+str(i),'cheeks','box',[x,0,40],[8,42,64],holes=[hole('axle',0,10.4,[x,0,50])]))
    wheel=part('pulley','pulley','stepped_rotary',[0,0,50],[24,50,50],axis=0,
               holes=[hole('bushing',0,16.4,[0,0,50])])
    wheel['outer_profile']=[{'id':'barrel','diameter_m':.040,'span_offset_m':[-.009,.009]},
                            {'id':'left_rim','diameter_m':.050,'span_offset_m':[-.012,-.009]},
                            {'id':'right_rim','diameter_m':.050,'span_offset_m':[.009,.012]}]
    wheel['axial_profile_probes']=[{'id':'rim_edges','radius_m':.0225,'boundary_offsets_m':[-.012,-.009,.009,.012]}]
    parts+=[wheel,part('bushing','bushing','tube',[0,0,50],[24,16,16],axis=0,diameter=16,
                      holes=[hole('axle',0,10.4,[0,0,50])]),
            part('axle','axle','cylinder',[0,0,50],[58,10,10],axis=0,diameter=10)]
    for i,x in enumerate((-28,28)):
        parts.append(part('collar-'+str(i),'collars','tube',[x,0,50],[3,18,18],axis=0,diameter=18,
                          holes=[hole('axle',0,10.4,[x,0,50])]))
    parts+=fasteners(centers,8,9.5)
    relations=[{'id':'left_wheel_gap','group':'wheel_clearance','roles':['pulley','cheek-0'],
                'axis':0,'bounds':['low','high'],'difference_m':.004},
               {'id':'right_wheel_gap','group':'wheel_clearance','roles':['cheek-1','pulley'],
                'axis':0,'bounds':['low','high'],'difference_m':.004}]
    return {'task_id':'L1/Text2Code/task_L1_Text2Code_005','parts':parts,'relations':relations,
            'numeric_groups':['part_roles','base','cheeks','pulley','bushing','axle','collars','fasteners','wheel_clearance','assembly_clearance'],
            'tolerance_m':.0003,'state_separation_half_scale_m':.0008,
            'negative_dimension_role':'axle','negative_dimension_axes':[1,2],
            'negative_dimension_group':'axle','control_overlap_roles':['washer-0','bolt-0'],
            'control_overlap_shift_m':[0.,0.,.002],
            'assignment':'one-to-one extent and public world-centre cost; no object-name target',
            'registration':'fixed_format_conversion_only','physics_scoring':False}


def contract(number):
    if number=='003':return stage()
    if number=='004':return vise()
    if number=='005':return pulley()
    from .continuous_assembly_layouts import indexing_table,latch,camera_mount
    if number=='006':return indexing_table()
    if number=='007':return latch()
    if number=='011':return camera_mount()
    from .continuous_assembly_cavity_contracts import electronics_box,filter_display,telescopic_tube,roller_guide
    if number=='008':return electronics_box()
    if number=='009':return filter_display()
    if number=='010':return telescopic_tube()
    if number=='012':return roller_guide()
    if number=='015':
        from .continuous_assembly_coupling import coupling
        return coupling()
    raise ValueError('Public assembly adapter pending: '+number)
