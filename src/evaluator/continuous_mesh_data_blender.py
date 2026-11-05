"""Native mesh attributes and skinning observations for protected scene data."""
import numpy as np


def attributes(data):
    arrays={};metadata=[]
    for i,attribute in enumerate(data.attributes):
        prefix='attribute_'+str(i);item={'name':attribute.name,'domain':attribute.domain,
            'type':attribute.data_type,'count':len(attribute.data),'fields':[]}
        if attribute.data:
            entry=attribute.data[0]
            names=[name for name in ('value','vector','color') if hasattr(entry,name)]
            if not names:raise ValueError('Unsupported protected attribute '+attribute.name)
            for name in names:
                sample=np.asarray(getattr(entry,name));shape=(len(attribute.data),*sample.shape)
                if sample.dtype.kind not in 'biufUS':raise ValueError('Unsupported attribute field '+name)
                dtype=np.float64 if sample.dtype.kind=='f' else np.int64 if sample.dtype.kind in 'iu' else sample.dtype
                if sample.dtype.kind in 'US':value=np.asarray([getattr(x,name) for x in attribute.data])
                else:
                    value=np.empty(shape,dtype=dtype);attribute.data.foreach_get(name,value.reshape(-1))
                arrays[prefix+'_'+name]=value;item['fields'].append(name)
        metadata.append(item)
    # Sparse (vertex, group, weight) entries retain zero weights and group IDs.
    entries=[(v.index,g.group,g.weight) for v in data.vertices for g in v.groups]
    arrays['deform_indices']=np.asarray([(v,g) for v,g,w in entries],dtype=np.int64).reshape(-1,2)
    arrays['deform_weights']=np.asarray([w for v,g,w in entries],dtype=np.float64)
    return arrays,metadata
