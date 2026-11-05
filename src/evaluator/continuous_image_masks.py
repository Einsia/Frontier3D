"""Fixed-grid silhouette measurements and explicitly reviewed cutout backgrounds."""
import numpy as np
from scipy.ndimage import binary_propagation


def reviewed_cutout(rgb,background_rgb,max_channel_error=0):
    """Only for a reference already reviewed as an exact-color cutout.

    Boundary-connected empty background, including reviewed quantization noise,
    is excluded. Interior dark material and
    enclosed black pixels remain foreground. This is not a general photo mask.
    """
    pixels=np.asarray(rgb)
    if pixels.ndim!=3 or pixels.shape[2]!=3 or pixels.dtype!=np.uint8:
        raise ValueError('Original RGB8 reference grid required')
    color=np.asarray(background_rgb)
    if color.shape!=(3,) or np.any(color<0) or np.any(color>255):raise ValueError('Reviewed RGB8 background required')
    if not isinstance(max_channel_error,int) or not 0<=max_channel_error<=1:
        raise ValueError('Only an explicitly reviewed one-level RGB8 dither tolerance is supported')
    same=np.max(np.abs(pixels.astype(np.int16)-color),axis=2)<=max_channel_error
    boundary=np.zeros(same.shape,bool)
    boundary[0]=boundary[-1]=True;boundary[:,0]=boundary[:,-1]=True
    background=binary_propagation(same&boundary,mask=same)
    if not background.any() or background.all():raise ValueError('Reviewed cutout requires visible foreground and exterior background')
    return ~background


def intersection_union(candidate,reference,region=None):
    candidate,reference=np.asarray(candidate),np.asarray(reference)
    if candidate.ndim!=2 or candidate.shape!=reference.shape or candidate.dtype!=bool or reference.dtype!=bool:
        raise ValueError('Two boolean masks on the same original pixel grid required; resizing is prohibited')
    if region is None:region=np.ones(reference.shape,bool)
    region=np.asarray(region)
    if region.shape!=reference.shape or region.dtype!=bool or not region.any():raise ValueError('Nonempty fixed evaluation region required')
    if not np.any(reference&region):raise ValueError('Reference has no annotated foreground in this region')
    return {'intersection':int(np.count_nonzero(candidate&reference&region)),
            'union':int(np.count_nonzero((candidate|reference)&region)),
            'reference_pixels':int(np.count_nonzero(reference&region)),
            'candidate_pixels':int(np.count_nonzero(candidate&region)),
            'evaluation_pixels':int(region.sum())}
