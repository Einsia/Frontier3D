"""Public polynomial sweep dimensions, path sections and transported edge probes."""
import numpy as np
from scipy.special import logsumexp
from .continuous_numeric import line_probe,scalar_error
from .l1_sweep import reference_mesh,validate_reference
from .l1_sweep_measurements import section_frames,section_rectangle,rectangular_bound

WIDTH=.0093
DEPTH=.0069
TOLERANCE=.00015


def grouped(groups,evidence,**metadata):
    if not groups or any(not rows for rows in groups.values()) or not evidence:
        raise ValueError('Fixed nonempty groups and evidence required')
    quantities=[]
    for name,rows in groups.items():
        if any(r['status']=='technical_failure' for r in rows):
            return {'status':'technical_failure','reason':'A required probe could not be measured','evidence':evidence}
        logs=[]
        for row in rows:
            if row['status']=='absent':continue
            errors=np.asarray(row['normalized_errors'],float)
            if not len(errors) or not np.isfinite(errors).all() or (errors<0).any():
                raise ValueError('Finite nonnegative probe errors required')
            logs.append(float(logsumexp(-errors*np.log(2))-np.log(len(errors))))
        if logs:
            error=max(0.,float(-(logsumexp(logs)-np.log(len(rows)))/np.log(2)))
            value={'status':'measured','normalized_errors':[error]}
        else:value={'status':'absent','reason':'All declared probes in this quantity are absent'}
        quantities.append({'id':name,**value,'observations':rows})
    return {'status':'measured','quantities':quantities,'evidence':evidence,
            'normalization':'equal_quantity_groups_then_mean_declared_probe_kernels',**metadata}


def query_contract(reference):
    mesh,approximation=reference_mesh(reference,error_m=TOLERANCE/64)
    eligible,omitted=[],[]
    for frame in section_frames(reference):
        measured=section_rectangle(mesh,frame)
        ok=(measured['status']=='measured'
            and abs(measured['width_m']-WIDTH)<TOLERANCE/8
            and abs(measured['depth_m']-DEPTH)<TOLERANCE/8
            and rectangular_bound(measured,TOLERANCE/8))
        (eligible if ok else omitted).append(frame)
    if len(eligible)<5:raise ValueError('Insufficient fixed unambiguous reference sections')
    spans,depth=validate_reference(reference);points=[];groups=[]
    for span in spans:
        for fraction in np.linspace(0,1,257):
            work=span.copy()
            while work.shape[1]>1:work=(1-fraction)*work[:,:-1]+fraction*work[:,1:]
            for x,z in work[:,0]:
                for y in (-depth/2,depth/2):points.append([float(x),y,float(z)]);groups.append('transported_longitudinal_edges')
    for ends in (spans[0][:,0],spans[-1][:,-1]):
        for u in (np.arange(16)+.5)/16:
            x,z=ends[0]*(1-u)+ends[1]*u
            for v in (np.arange(16)+.5)/16:
                points.append([float(x),float((v-.5)*depth),float(z)]);groups.append('end_faces')
    return mesh,{'frames':eligible,'omitted_reference_sections':omitted,'reference_approximation':approximation,
        'points_m':points,'point_groups':groups,'width_m':WIDTH,'depth_m':DEPTH,'tolerance_m':TOLERANCE,
        'frame_eligibility':'declared_reference_only; never candidate-dependent',
        'registration':'none','basis':'public OCC interpolation and corrected-Frenet polynomial boundary'}


def section_measurements(vertices,triangles,contract,evidence):
    path_rows=[];dimensions={'width':[],'depth':[]}
    for frame in contract['frames']:
        rows={}
        for name,axis,expected in (('width',frame['width_axis'],WIDTH),('depth',[0,1,0],DEPTH)):
            definition={'kind':'line','origin_m':frame['center_m'],'axis':axis,'mode':'bracket',
                        'window_m':[-4*max(WIDTH,DEPTH),4*max(WIDTH,DEPTH)]}
            observed=line_probe(vertices,triangles,definition);rows[name]=observed
            raw={'frame':frame,'definition':definition,'observation':observed,'status':observed['status']}
            if observed['status']=='measured':raw['normalized_errors']=scalar_error(observed['distance_m'],expected,TOLERANCE)
            else:raw['reason']=observed['reason']
            dimensions[name].append(raw)
        if any(r['status']=='absent' for r in rows.values()):
            path_rows.append({'status':'absent','reason':'Required centered sweep section absent','frame':frame,'observations':rows})
        else:
            center=np.asarray(frame['center_m'])
            delta=sum(np.asarray(row['center_world_m'])-center for row in rows.values())
            path_rows.append({'status':'measured','center_offset_m':delta.tolist(),'frame':frame,'observations':rows,
                              'normalized_errors':scalar_error(float(np.linalg.norm(delta)),0.,TOLERANCE)})
    return {'numeric_interpolated_path':grouped({'path_centres':path_rows},evidence),
            'numeric_rectangular_section':grouped(dimensions,evidence)}


def distance_measurements(surface,queries,contract,evidence):
    result={}
    if surface['status']=='absent':
        result['numeric_surface_accuracy']={'status':'absent','reason':'Candidate sweep surface absent','evidence':evidence}
    elif surface['status']=='measured':
        groups={key:[{'status':'measured','normalized_errors':(
            np.maximum(np.asarray(surface[key+'_distances_m'])-TOLERANCE,0)/TOLERANCE).tolist(),
            'raw_distance_field':key+'_distances_m'}] for key in ('candidate','reference')}
        result['numeric_surface_accuracy']=grouped(groups,evidence,raw_surface=surface,
                                                   reference_approximation=contract['reference_approximation'])
    else:raise ValueError('Sweep surface measurement failed')
    if queries['status']=='absent':
        result['numeric_sweep_transport']={'status':'absent','reason':'Candidate sweep edges and ends absent','evidence':evidence}
    elif queries['status']=='measured':
        groups={name:[] for name in dict.fromkeys(contract['point_groups'])}
        if len(queries['distances_m'])!=len(contract['points_m']):raise ValueError('Complete sweep query population required')
        for index,(name,point,distance) in enumerate(zip(contract['point_groups'],contract['points_m'],queries['distances_m'])):
            groups[name].append({'status':'measured','query_index':index,'point_world_m':point,'distance_m':distance,
                                'normalized_errors':scalar_error(distance,0.,TOLERANCE)})
        result['numeric_sweep_transport']=grouped(groups,evidence,point_measurement=queries['measurement'])
    else:raise ValueError('Sweep edge/end query failed')
    return result
