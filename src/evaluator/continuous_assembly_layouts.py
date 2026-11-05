"""Public layouts for the indexing table, latch and camera mount."""
import numpy as np
from .continuous_assembly_contracts import part,hole,fasteners


def relation(name,group,left,right,axis,bounds=('low','high'),gap=0.):
    return {'id':name,'group':group,'roles':[left,right],'axis':axis,'bounds':list(bounds),'difference_m':gap/1000}


def layout(number,parts,groups,relations,negative_role,negative_axes,negative_group,position_group='base'):
    centers=np.array([p['center_m'] for p in parts]);extents=np.array([p['extent_m'] for p in parts])
    span=(centers+extents/2).max(0)-(centers-extents/2).min(0)
    return {'task_id':'L1/Text2Code/task_L1_Text2Code_'+number,'parts':parts,'relations':relations,
            'numeric_groups':['part_roles',*groups,'assembly_clearance'],'tolerance_m':.0003,
            'state_separation_half_scale_m':float(span.max()*.01),
            'negative_dimension_role':negative_role,'negative_dimension_axes':negative_axes,
            'negative_dimension_group':negative_group,'negative_position_group':position_group,
            'control_overlap_roles':['washer-0','bolt-0'],'control_overlap_shift_m':[0.,0.,.002],
            'assignment':'one-to-one extent and public world-centre cost; no object-name target',
            'registration':'fixed_format_conversion_only','physics_scoring':False}


def indexing_table():
    mount=[(x,y) for x in (-40,40) for y in (-40,40)]
    parts=[part('base','base','box',[0,0,4],[100,100,8],holes=[hole('spindle',2,16.4,[0,0,4]),
        *[hole('mount-'+str(i),2,6.4,[x,y,4]) for i,(x,y) in enumerate(mount)]]),
        part('sleeve','sleeve','tube',[0,0,13.5],[28,28,11],axis=2,diameter=28,holes=[hole('spindle',2,16.4,[0,0,13.5])]),
        part('spindle','spindle','cylinder',[0,0,17],[16,16,26],axis=2,diameter=16),
        part('disk','disk','tube',[0,0,23],[84,84,8],axis=2,diameter=84,holes=[hole('spindle',2,16.4,[0,0,23]),
            *[hole('index-'+str(i),2,6.4,[32*np.cos(i*np.pi/3),32*np.sin(i*np.pi/3),23]) for i in range(6)]]),
        part('pin','index_pin','cylinder',[32,0,22],[6,6,18],axis=2,diameter=6),
        part('ring','retaining_ring','tube',[0,0,30],[26,26,3],axis=2,diameter=26,holes=[hole('spindle',2,16.4,[0,0,30])]),
        *fasteners(mount,8,9.5)]
    relations=[relation('sleeve_on_base','axial_layout','sleeve','base',2),
               relation('disk_on_sleeve','axial_layout','disk','sleeve',2),
               relation('upper_ring_gap','axial_layout','ring','disk',2,gap=1.5)]
    return layout('006',parts,['base','sleeve','spindle','disk','index_pin','retaining_ring','fasteners','axial_layout'],
                  relations,'spindle',[0,1],'spindle')


def latch():
    mount=[(x,y) for x in (-68,68) for y in (-19,19)]
    parts=[part('plate','plate','box',[0,0,2.5],[150,50,5],
        holes=[hole('mount-'+str(i),2,6.4,[x,y,2.5]) for i,(x,y) in enumerate(mount)])]
    for i,x in enumerate((-45,5,55)):
        parts.append(part('block-'+str(i),'blocks','box',[x,0,17.5],[14,26,25],holes=[hole('slider',0,10.4,[x,0,20.5])]))
    parts+=[part('slider','sliding_bolt','cylinder',[5,0,20.5],[118,10,10],axis=0,diameter=10),
            part('handle','handle','cylinder',[-15,0,37.5],[6,6,24],axis=2,diameter=6),
            part('grip','grip','cylinder',[-15,0,54.5],[14,14,10],axis=2,diameter=14)]
    for i,x in enumerate((-30,25)):
        parts.append(part('ring-'+str(i),'stop_rings','tube',[x,0,20.5],[4,16,16],axis=0,diameter=16,
                          holes=[hole('slider',0,10.4,[x,0,20.5])]))
    parts+=fasteners(mount,5,6.5)
    relations=[relation('handle_touches_slider','handle','handle','slider',2),
               relation('grip_touches_handle','grip','grip','handle',2),
               *[relation('block_on_plate-'+str(i),'blocks','block-'+str(i),'plate',2) for i in range(3)]]
    return layout('007',parts,['plate','blocks','sliding_bolt','handle','grip','stop_rings','fasteners'],
                  relations,'slider',[1,2],'sliding_bolt','plate')


def camera_mount():
    mount=[(x,y) for x in (-35,35) for y in (-35,35)]
    parts=[part('base','base','box',[0,0,4],[90,90,8],holes=[hole('spindle',2,16.4,[0,0,4]),
        *[hole('mount-'+str(i),2,6.4,[x,y,4]) for i,(x,y) in enumerate(mount)]]),
        part('sleeve','pan_sleeve','tube',[0,0,18],[36,36,20],axis=2,diameter=36,holes=[hole('spindle',2,16.4,[0,0,18])]),
        part('spindle','spindle','cylinder',[0,0,21],[16,16,30],axis=2,diameter=16),
        part('fork_base','fork_base','box',[0,0,31],[64,50,6],holes=[hole('spindle',2,16.4,[0,0,31])]),
        part('platform','platform','box',[0,0,69],[48,64,10],holes=[hole('tilt',0,8.4,[0,0,69])])]
    for i,x in enumerate((-28,28)):
        parts+=[part('upright-'+str(i),'uprights','box',[x,0,59],[6,50,50],holes=[hole('tilt',0,14.4,[x,0,69])]),
                part('bushing-'+str(i),'bushings','tube',[x,0,69],[6,14,14],axis=0,diameter=14,
                     holes=[hole('tilt',0,8.4,[x,0,69])]),
                part('pin-'+str(i),'tilt_pins','cylinder',[x/abs(x)*24,0,69],[16,8,8],axis=0,diameter=8)]
    parts+=fasteners(mount,8,9.5)
    relations=[relation('fork_on_sleeve','fork_base','fork_base','sleeve',2),
               *[relation('upright_on_fork-'+str(i),'uprights','upright-'+str(i),'fork_base',2) for i in range(2)],
               relation('left_platform_gap','platform','platform','upright-0',0,gap=1),
               relation('right_platform_gap','platform','upright-1','platform',0,gap=1)]
    return layout('011',parts,['base','pan_sleeve','spindle','fork_base','uprights','bushings','platform','tilt_pins','fasteners'],
                  relations,'spindle',[0,1],'spindle')
