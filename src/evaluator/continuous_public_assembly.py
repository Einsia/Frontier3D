"""Continuous feature measurements from explicit public assembly dimensions.

The declarative part and relation population is fixed before reading a candidate.
Matching identifies parts in world coordinates and never transforms their meshes.
"""
import numpy as np
from scipy.optimize import linear_sum_assignment
from .continuous_assembly_features import quantity,circular_rows,bore_rows
from .continuous_sweep import grouped
from .l1_sections import axial_corridor
from .continuous_assembly_profiles import bolt,stepped_rotary
from .continuous_assembly_cavities import rectangular_cavity,notch,line_boundaries
from .continuous_assembly_coupling import with_observed_datum,pattern


def hole_measurements(part,definition,hole):
    if hole.get('kind')=='open_notch':return notch(part,definition,hole)
    center=part.center+np.asarray(hole['center_m'])-np.asarray(definition['center_m'])
    if 'section_spans_offset_m' not in hole:
        return bore_rows(part,center,hole['diameter_m'],axis=hole['axis'])
    axis=hole['axis'];rows=[]
    # Public intersecting holes remove part of each other's wall. Fixed spans
    # sample the surviving cylindrical wall; the complete corridor is still
    # checked across the entire part, including the intersection region.
    for offset in hole['section_spans_offset_m']:
        span=part.center[axis]+np.asarray(offset)
        rows+=bore_rows(part,center,hole['diameter_m'],axis=axis,span=span)[:-1]
    center[axis]=0.;diameter=hole['diameter_m']
    span=part.center[axis]+np.asarray(hole['corridor_span_offset_m']) if 'corridor_span_offset_m' in hole else [float(part.low[axis]),float(part.high[axis])]
    corridor=axial_corridor(part.mesh,center,np.eye(3)[axis],span,max(diameter/2-.00015,1e-8))
    radius=corridor['minimum_boundary_radius_m'];observed=all(r['status']=='measured' for r in rows)
    opening=None if not observed or radius is None or radius<=1e-9 else max(0.,diameter-2*radius)
    rows.append(quantity(opening,0.,{'full_triangle_corridor':corridor,'cavity_sections_observed':observed,
                                    'public_section_spans_offset_m':hole['section_spans_offset_m']}))
    return rows


def assignment(parts,contract):
    definitions=contract['parts'];mapping={d['role']:None for d in definitions}
    if not parts:return mapping,[]
    cost=[]
    for d in definitions:
        extent=np.asarray(d['extent_m']);center=np.asarray(d['center_m'])
        cost.append([float(np.abs(np.log(np.maximum(p.high-p.low,1e-12)/extent)).mean())+
                     float(np.linalg.norm((p.center-center)/np.maximum(extent,.01))) for p in parts])
    # Every declared role is a three-dimensional solid. An exactly collapsed
    # axis cannot supply that role or an axial bore. Keep such geometry in the
    # scene population/count diagnostics, without assigning it to a solid role.
    # No thickness threshold is used: arbitrarily thin positive extents remain.
    eligible=[i for i,p in enumerate(parts) if np.all(p.high>p.low)]
    if not eligible:return mapping,cost
    rows,cols=linear_sum_assignment(np.asarray(cost)[:,eligible])
    for i,j in zip(rows,cols):mapping[definitions[int(i)]['role']]=eligible[int(j)]
    return mapping,cost


def planes(part,definition):
    xyz=part.mesh.xyz;cross=np.cross(xyz[:,1]-xyz[:,0],xyz[:,2]-xyz[:,0])
    norms=np.linalg.norm(cross,axis=1)
    normal=np.divide(cross,norms[:,None],out=np.zeros_like(cross),where=norms[:,None]>0)
    rows=[];extent=definition['extent_m']
    for axis in range(3):
        public_area=float(np.prod([x for i,x in enumerate(extent) if i!=axis]))
        public_area-=sum(np.pi*(h['diameter_m']/2)**2*h.get('face_area_fraction',1.) for h in definition.get('holes',[]) if h['axis']==axis)
        for side,plane in (('low',part.low[axis]),('high',part.high[axis])):
            expected_area=definition.get('plane_area_overrides_m2',{}).get(str(axis)+'/'+side,public_area)
            if expected_area<=0:raise ValueError('Public exterior plane area must be positive')
            distance=np.abs(xyz[:,:,axis]-plane).max(1)
            selected=(distance<=.0003)&(np.abs(normal[:,axis])>.99)
            area=float(np.sum(part.mesh.areas[selected]*np.abs(normal[selected,axis])))
            coverage=min(1.,area/expected_area)
            rows.append({'status':'measured','normalized_errors':[-float(np.log2(coverage))] if coverage else [1074.],
                'axis':axis,'side':side,'observed_planar_area_m2':area,'public_plane_area_m2':expected_area,
                'coverage':coverage,'observed_plane_m':float(plane)})
            if not coverage:rows[-1].update(status='absent',reason='Required outside planar face absent')
    return rows


def features(parts,contract,evidence):
    if contract.get('free_origin_and_pattern_phase'):contract=with_observed_datum(parts,contract)
    mapping,cost=assignment(parts,contract)
    groups={name:{} for name in contract['numeric_groups'] if name!='assembly_clearance'}
    placements=[];openings=[];records={}
    for definition in contract['parts']:
        role=definition['role'];index=mapping[role];kind=definition['kind'];group=groups[definition['group']]
        names=['extent','position']
        if kind=='box':names+=['outside_planes']
        if kind in ('cylinder','tube'):names+=['outer_circular_sections','axial_length']
        if kind=='bolt':names+=['shank_diameter','hex_head','shank_length','head_height']
        if kind=='stepped_rotary':
            names+=['profile/'+s['id'] for s in definition['outer_profile']]
            names+=['profile_edges/'+s['id'] for s in definition['axial_profile_probes']]
        if 'rectangular_cavity' in definition:names+=['rectangular_sections','rectangular_opening']
        if index is None:
            absent={'status':'absent','reason':'Required '+role+' absent','role':role}
            for name in names:group[role+'/'+name]=[absent]
            for h in definition.get('holes',[]):
                for target in [h.get('group',definition['group']),*h.get('also_groups',[])]:groups[target][role+'/hole/'+h['id']]=[absent]
            for probe in definition.get('line_probes',[]):
                for target in [probe.get('group',definition['group']),*probe.get('also_groups',[])]:
                    groups[target].setdefault(role+'/probe/'+probe.get('quantity_id',probe['id']),[]).append(absent)
            groups['part_roles'][role]=[absent];placements.append(absent)
            openings.extend([{**absent,'hole':h['id']} for h in definition.get('holes',[])])
            if 'rectangular_cavity' in definition:openings.append({**absent,'hole':'rectangular_opening'})
            if 'hole_pattern' in definition:
                for label in ('count','pitch','spacing'):groups[definition['hole_pattern']['group']][role+'/pattern/'+label]=[absent]
            continue
        part=parts[index]
        raw={'role':role,'object_index':index,'object':part.metadata.get('object'),
             'actual_center_m':part.center.tolist(),'actual_extent_m':(part.high-part.low).tolist(),'definition':definition}
        records[role]=raw;position=quantity(part.center.tolist(),definition['center_m'],raw)
        group[role+'/extent']=[quantity(float(part.high[2]-part.low[2]),definition['extent_m'][2],raw)
                              if kind=='bolt' else quantity((part.high-part.low).tolist(),definition['extent_m'],raw)]
        group[role+'/position']=[position];placements.append({**position,'role':role});proof=[]
        if kind=='box':
            rows=planes(part,definition);group[role+'/outside_planes']=rows;proof+=rows
        elif kind in ('cylinder','tube'):
            spans=definition.get('outer_section_spans_offset_m');axis=definition['axis']
            if spans:
                rows=[r for offset in spans for r in circular_rows(part,definition['diameter_m'],axis=axis,
                    span=part.center[axis]+np.asarray(offset))]
            else:rows=circular_rows(part,definition['diameter_m'],axis=axis)
            group[role+'/outer_circular_sections']=rows;proof+=rows
            group[role+'/axial_length']=[quantity(float((part.high-part.low)[definition['axis']]),
                definition['extent_m'][definition['axis']],raw)]
        elif kind in ('bolt','stepped_rotary'):
            rows_by_feature=(bolt if kind=='bolt' else stepped_rotary)(part,definition)
            for name,rows in rows_by_feature.items():group[role+'/'+name]=rows;proof+=rows
        else:raise ValueError('Unsupported public part kind: '+kind)
        if 'rectangular_cavity' in definition:
            cavity=rectangular_cavity(part,definition)
            for name,rows in cavity.items():group[role+'/'+name]=rows;proof+=rows
            opening=grouped({'fixed_opening_rays':cavity['rectangular_opening']},evidence)
            if opening['status']=='measured':opening=opening['quantities'][0]
            openings.append({**opening,'role':role,'hole':'rectangular_opening'})
        if 'hole_pattern' in definition:
            for label,rows in pattern(part,definition).items():
                groups[definition['hole_pattern']['group']][role+'/pattern/'+label]=rows;proof+=rows
        for hole in definition.get('holes',[]):
            rows=hole_measurements(part,definition,hole)
            for target in [hole.get('group',definition['group']),*hole.get('also_groups',[])]:groups[target][role+'/hole/'+hole['id']]=rows
            proof+=rows
            openings.append({**rows[-1],'role':role,'hole':hole['id']})
        for probe in definition.get('line_probes',[]):
            row=line_boundaries(part,probe)
            for target in [probe.get('group',definition['group']),*probe.get('also_groups',[])]:
                groups[target].setdefault(role+'/probe/'+probe.get('quantity_id',probe['id']),[]).append(row)
            proof.append(row)
        editable=bool(part.metadata.get('editable',False)) and not part.metadata.get('instance',False)
        proof.append(quantity(0. if editable else None,0.,{'independent_editability':editable}))
        groups['part_roles'][role]=proof
    groups['part_roles']['total_count']=[quantity(len(parts) if parts else None,len(contract['parts']),
        {'observed_parts':len(parts)},tolerance=0.,half_scale=1.)]
    relations=[]
    for relation in contract.get('relations',[]):
        a,b=(mapping[r] for r in relation['roles']);value=None
        if a is not None and b is not None:
            axis=relation['axis']
            value=float(getattr(parts[a],relation['bounds'][0])[axis]-getattr(parts[b],relation['bounds'][1])[axis])
        row=quantity(value,relation['difference_m'],{'public_relation':relation})
        groups[relation['group']]['relation/'+relation['id']]=[row];relations.append(row)
    measurements={'numeric_'+name:grouped(rows,evidence,public_contract=contract) for name,rows in groups.items()}
    measurements['numeric_assembly_clearance']={'status':'technical_failure',
        'reason':'Complete collector supplies pairwise overlap and public relations','evidence':evidence}
    return {'measurements':measurements,'assignment':mapping,'assignment_cost':cost,
            'part_observations':records,'placement_observations':placements,
            'opening_observations':openings,'relation_observations':relations,'contract':contract}
